import tempfile
import unittest
from pathlib import Path

from app.catalog import Catalog, ValidationError


class CatalogPersistenceTests(unittest.TestCase):
    def test_preferences_and_tracks_survive_reopening_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            catalog = Catalog(database)
            result = catalog.reconcile_tracks(
                [
                    {
                        "path": "Artist/Album/01 Song.flac",
                        "title": "Song",
                        "artist": "Artist",
                        "album": "Album",
                        "size": 123,
                        "mtime": 456,
                    }
                ]
            )
            track_id = result["track_ids"][0]
            catalog.set_preference(track_id, rating=5, favorite=True)
            catalog.close()

            reopened = Catalog(database)
            track = reopened.get_track(track_id)
            self.assertEqual(track["title"], "Song")
            self.assertEqual(track["rating"], 5)
            self.assertIs(track["favorite"], True)
            reopened.close()

    def test_scan_reconciliation_cascades_removed_tracks_from_playlists(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            first_id = catalog.reconcile_tracks([{"path": "gone.flac", "title": "Gone"}])["track_ids"][0]
            playlist_id = catalog.create_playlist("Temporary")["id"]
            catalog.add_playlist_track(playlist_id, first_id)

            result = catalog.reconcile_tracks([{"path": "kept.flac", "title": "Kept"}])

            self.assertEqual(result["removed"], 1)
            self.assertEqual(catalog.get_playlist(playlist_id)["tracks"], [])
            catalog.close()


class CatalogQueryTests(unittest.TestCase):
    def test_explicit_initialize_and_limit_offset_query_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3").initialize()
            catalog.reconcile_tracks(
                [
                    {"path": "a.flac", "title": "A"},
                    {"path": "b.flac", "title": "B"},
                    {"path": "c.flac", "title": "C"},
                ]
            )
            result = catalog.list_tracks(limit=1, offset=1)
            self.assertEqual(result["total"], 3)
            self.assertEqual([track["title"] for track in result["items"]], ["B"])
            catalog.close()

    def test_search_pagination_and_groups_use_public_catalog_results(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            catalog.reconcile_tracks(
                [
                    {"path": "one.flac", "title": "First", "artist": "Alpha", "album": "Shared"},
                    {"path": "two.flac", "title": "Second", "artist": "Alpha", "album": "Shared"},
                    {"path": "three.flac", "title": "Third", "artist": "Beta", "album": "Other"},
                ]
            )

            page = catalog.list_tracks(search="Alpha", page=2, page_size=1)
            self.assertEqual(page["total"], 2)
            self.assertEqual(len(page["items"]), 1)
            self.assertEqual(catalog.list_albums()["total"], 2)
            self.assertEqual(catalog.list_artists()["total"], 2)
            self.assertEqual(catalog.list_catalog_initials("songs"), ["A", "B"])
            catalog.close()

    def test_same_album_title_by_different_artists_forms_one_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            catalog.reconcile_tracks(
                [
                    {"path": "a.flac", "title": "A", "album": "Greatest Hits", "album_artist": "Alpha"},
                    {"path": "b.flac", "title": "B", "album": "Greatest Hits", "album_artist": "Beta"},
                ]
            )
            albums = catalog.list_albums()
            self.assertEqual(albums["total"], 1)
            self.assertEqual(albums["items"][0]["album_artist"], "Разные исполнители")
            catalog.close()

    def test_artists_return_cached_image_state_without_cover_fan_out(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            catalog.reconcile_tracks(
                [
                    {"path": f"alpha-{index}.flac", "title": str(index), "artist": "Alpha", "album": f"Album {index}", "cover_url": f"cover-{index}"}
                    for index in range(1, 6)
                ]
            )
            artist = catalog.list_artists()["items"][0]
            self.assertNotIn("album_cover_urls", artist)
            catalog.save_artist_image("Alpha", None, "missing", "wikimedia")
            self.assertEqual(catalog.list_artists()["items"][0]["artist_image_status"], "missing")
            catalog.close()


class PlaylistTests(unittest.TestCase):
    def test_agreed_update_and_set_tracks_contract_replaces_order_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            ids = catalog.reconcile_tracks(
                [
                    {"path": "a.flac", "title": "A"},
                    {"path": "b.flac", "title": "B"},
                    {"path": "c.flac", "title": "C"},
                ]
            )["track_ids"]
            playlist_id = catalog.create_playlist("Before")["id"]
            catalog.update_playlist(playlist_id, "After")
            catalog.set_playlist_tracks(playlist_id, [ids[2], ids[0]])

            stored = catalog.get_playlist(playlist_id)
            self.assertEqual(stored["name"], "After")
            self.assertEqual([track["id"] for track in stored["tracks"]], [ids[2], ids[0]])
            with self.assertRaises(ValidationError):
                catalog.set_playlist_tracks(playlist_id, [ids[0], 999999])
            self.assertEqual(
                [track["id"] for track in catalog.get_playlist(playlist_id)["tracks"]],
                [ids[2], ids[0]],
            )
            catalog.close()

    def test_playlist_crud_order_and_failed_reorder_are_persistent_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            catalog = Catalog(database)
            ids = catalog.reconcile_tracks(
                [{"path": "a.flac", "title": "A"}, {"path": "b.flac", "title": "B"}]
            )["track_ids"]
            playlist = catalog.create_playlist("Drive")
            catalog.add_playlist_track(playlist["id"], ids[0])
            catalog.add_playlist_track(playlist["id"], ids[1])
            catalog.reorder_playlist(playlist["id"], [ids[1], ids[0]])
            with self.assertRaises(ValidationError):
                catalog.reorder_playlist(playlist["id"], [ids[0]])
            catalog.rename_playlist(playlist["id"], "Night Drive")
            catalog.close()

            reopened = Catalog(database)
            stored = reopened.get_playlist(playlist["id"])
            self.assertEqual(stored["name"], "Night Drive")
            self.assertEqual([track["id"] for track in stored["tracks"]], [ids[1], ids[0]])
            reopened.delete_playlist(playlist["id"])
            self.assertEqual(reopened.list_playlists(), [])
            reopened.close()


class SettingsTests(unittest.TestCase):
    def test_only_known_non_secret_string_settings_are_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            self.assertEqual(
                catalog.update_settings({"mpd_host": "novin", "mpd_port": "6600"}),
                {"mpd_host": "novin", "mpd_port": "6600"},
            )
            with self.assertRaises(ValidationError):
                catalog.update_settings({"mpd_password": "placeholder"})
            with self.assertRaises(ValidationError):
                catalog.update_settings({"invented": "value"})
            self.assertEqual(catalog.get_settings(), {"mpd_host": "novin", "mpd_port": "6600"})

    def test_catalog_page_size_accepts_only_multiples_of_seven(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            self.assertEqual(catalog.update_settings({"catalog_page_size": "28"})["catalog_page_size"], "28")
            with self.assertRaises(ValidationError):
                catalog.update_settings({"catalog_page_size": "24"})
            catalog.close()


class PreferenceTests(unittest.TestCase):
    def test_rating_bounds_and_favorites_filter_are_enforced_by_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            track_id = catalog.reconcile_tracks([{"path": "favorite.flac", "title": "Favorite"}])["track_ids"][0]
            with self.assertRaises(ValidationError):
                catalog.set_preference(track_id, rating=6)
            catalog.set_preference(track_id, rating=0, favorite=True)
            favorites = catalog.list_tracks(favorite=True)
            self.assertEqual(favorites["total"], 1)
            self.assertEqual(favorites["items"][0]["rating"], 0)
            self.assertIs(favorites["items"][0]["favorite"], True)
            catalog.close()


class RadioStationPersistenceTests(unittest.TestCase):
    def test_found_and_favorite_radio_stations_survive_reopening_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            catalog = Catalog(database)
            station = {"id": "station-1", "name": "Novin FM", "genre": "Rock", "stream_url": "https://radio.example/live"}
            catalog.save_radio_stations([station])
            catalog.set_radio_favorite(station, True)
            catalog.close()

            reopened = Catalog(database)
            self.assertEqual(reopened.list_radio_stations(favorite=True)[0]["name"], "Novin FM")
            self.assertEqual(reopened.get_radio_station("station-1")["stream_url"], "https://radio.example/live")
            reopened.close()

    def test_recent_radio_station_is_hidden_after_mpd_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            station = {"id": "station-1", "name": "Novin FM", "stream_url": "https://radio.example/live"}
            catalog.save_radio_stations([station])
            catalog.mark_radio_playing("station-1")
            blocked = catalog.blacklist_recent_radio_station()
            self.assertEqual(blocked["id"], "station-1")
            self.assertTrue(blocked["blacklisted"])
            self.assertEqual(catalog.list_radio_stations(), [])
            self.assertIsNone(catalog.get_radio_station("station-1"))
            self.assertTrue(catalog.get_radio_station("station-1", include_blacklisted=True)["blacklisted"])
            catalog.close()

    def test_radio_catalog_snapshot_is_persisted_and_excludes_blacklisted_stations(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            stations = [
                {"id": "station-1", "name": "Novin FM", "stream_url": "https://radio.example/live"},
                {"id": "station-2", "name": "Novin Rock", "stream_url": "https://radio.example/rock"},
            ]
            catalog.save_radio_stations(stations)
            catalog.save_radio_snapshot({"genre": "All", "source": "radio_browser", "genres": ["All"], "stations": stations})
            self.assertEqual([item["id"] for item in catalog.get_radio_snapshot("All", "", 10)["stations"]], ["station-1", "station-2"])
            catalog.mark_radio_playing("station-1")
            catalog.blacklist_recent_radio_station()
            self.assertEqual([item["id"] for item in catalog.get_radio_snapshot("All", "", 10)["stations"]], ["station-2"])
            catalog.close()


if __name__ == "__main__":
    unittest.main()
