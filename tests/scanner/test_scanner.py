import tempfile
import unittest
from pathlib import Path

from app.scanner import Scanner


class ScannerTests(unittest.TestCase):
    def test_supported_files_become_normalized_rows_with_metadata_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "Artist" / "Album" / "01 Song.FLAC"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"audio")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            snapshot = Scanner(metadata_reader=lambda path: {"duration": 125.5}).scan(root)

            self.assertEqual(snapshot.counters, {"discovered": 1, "indexed": 1, "unreadable": 0, "unsupported": 1})
            self.assertEqual(snapshot.tracks[0]["path"], "Artist/Album/01 Song.FLAC")
            self.assertEqual(snapshot.tracks[0]["title"], "Без названия")
            self.assertEqual(snapshot.tracks[0]["artist"], "Неизвестный исполнитель")
            self.assertEqual(snapshot.tracks[0]["album"], "Album")
            self.assertEqual(snapshot.tracks[0]["duration"], 125.5)

    def test_missing_album_tag_uses_its_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "Compilation" / "Disc One" / "song.flac"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"audio")

            snapshot = Scanner(metadata_reader=lambda path: {"title": "Song"}).scan(root)

            self.assertEqual(snapshot.tracks[0]["album"], "Disc One")

    def test_named_folder_cover_wins_over_embedded_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "album" / "song.mp3"
            audio.parent.mkdir()
            audio.write_bytes(b"audio")
            (audio.parent / "cover.jpg").write_bytes(b"folder-cover")

            snapshot = Scanner(
                metadata_reader=lambda path: {"embedded_cover": (b"embedded-cover", "image/png")}
            ).scan(root)

            cover_id = snapshot.tracks[0]["cover_url"].rsplit("/", 1)[1]
            self.assertEqual(snapshot.covers[cover_id].data, b"folder-cover")
            self.assertEqual(snapshot.covers[cover_id].mime_type, "image/jpeg")

    def test_artist_image_from_parent_directory_is_published_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artist = root / "Тима Белорусских"
            album = artist / "2020 - Моя кассета"
            album.mkdir(parents=True)
            (album / "01 Песня.mp3").write_bytes(b"audio")
            (album / "cover.jpg").write_bytes(b"album-cover")
            (artist / "Artist.JPG").write_bytes(b"artist-picture")

            snapshot = Scanner(metadata_reader=lambda path: {"artist": "Тима Белорусских"}).scan(root)

            track = snapshot.tracks[0]
            album_id = track["cover_url"].rsplit("/", 1)[1]
            artist_id = track["artist_cover_url"].rsplit("/", 1)[1]
            self.assertEqual(snapshot.covers[album_id].data, b"album-cover")
            self.assertEqual(snapshot.covers[artist_id].data, b"artist-picture")

    def test_artist_image_at_collection_root_is_not_applied_to_every_artist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            album = root / "Artist" / "Album"
            album.mkdir(parents=True)
            (album / "song.mp3").write_bytes(b"audio")
            (root / "Artist.jpg").write_bytes(b"generic-picture")

            snapshot = Scanner(metadata_reader=lambda path: {"artist": "Artist"}).scan(root)

            self.assertNotIn("artist_cover_url", snapshot.tracks[0])

    def test_unreadable_file_is_counted_without_aborting_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.ogg").write_bytes(b"bad")
            (root / "good.opus").write_bytes(b"good")

            def read(path):
                if path.name == "bad.ogg":
                    raise ValueError("broken tags")
                return {"title": "Good"}

            snapshot = Scanner(metadata_reader=read).scan(root)

            self.assertEqual(snapshot.counters["unreadable"], 1)
            self.assertEqual([track["title"] for track in snapshot.tracks], ["Good"])

    def test_named_folder_covers_follow_cover_folder_front_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "song.wav").write_bytes(b"audio")
            (root / "front.jpg").write_bytes(b"front")
            (root / "folder.png").write_bytes(b"folder")
            (root / "cover.webp").write_bytes(b"cover")

            snapshot = Scanner(metadata_reader=lambda path: {}).scan(root)

            cover_id = snapshot.tracks[0]["cover_url"].rsplit("/", 1)[1]
            self.assertEqual(snapshot.covers[cover_id].data, b"cover")
            self.assertEqual(snapshot.covers[cover_id].mime_type, "image/webp")

    def test_scan_publishes_progress_and_placeholder_cover_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "song.aac").write_bytes(b"audio")
            progress = []

            snapshot = Scanner(metadata_reader=lambda path: {}).scan(root, progress=progress.append)

            self.assertEqual(progress[-1]["indexed"], 1)
            self.assertEqual(progress[-1]["discovered"], 1)
            self.assertEqual(snapshot.tracks[0]["cover_url"], "/api/covers/placeholder")

    def test_unchanged_files_reuse_catalog_metadata_without_reading_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "Artist" / "Album" / "song.mp3"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"audio")
            first = Scanner(metadata_reader=lambda path: {"title": "Original", "artist": "Artist"}).scan(root)

            calls = []
            second = Scanner(metadata_reader=lambda path: calls.append(path) or {"title": "Changed"}).scan(
                root, cached_tracks={first.tracks[0]["path"]: first.tracks[0]}
            )

            self.assertEqual(calls, [])
            self.assertEqual(second.tracks[0]["title"], "Original")
            self.assertEqual(second.changed, 0)

    def test_changed_files_are_reindexed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "song.mp3"
            audio.write_bytes(b"old")
            first = Scanner(metadata_reader=lambda path: {"title": "Old"}).scan(root)
            audio.write_bytes(b"new and larger")

            second = Scanner(metadata_reader=lambda path: {"title": "New"}).scan(
                root, cached_tracks={first.tracks[0]["path"]: first.tracks[0]}
            )

            self.assertEqual(second.tracks[0]["title"], "New")
            self.assertEqual(second.changed, 1)


if __name__ == "__main__":
    unittest.main()
