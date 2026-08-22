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
            self.assertEqual(snapshot.tracks[0]["album"], "Неизвестный альбом")
            self.assertEqual(snapshot.tracks[0]["duration"], 125.5)

    def test_embedded_cover_wins_over_named_folder_cover(self):
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
            self.assertEqual(snapshot.covers[cover_id].data, b"embedded-cover")
            self.assertEqual(snapshot.covers[cover_id].mime_type, "image/png")

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


if __name__ == "__main__":
    unittest.main()
