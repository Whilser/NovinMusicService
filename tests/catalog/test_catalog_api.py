import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.catalog import Catalog
from app.dependencies import get_catalog
from app.main import create_app


class CatalogApiTests(unittest.TestCase):
    def test_catalog_playlist_preferences_settings_and_errors_through_http(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = Catalog(root / "override.sqlite3")
            track_ids = catalog.reconcile_tracks(
                [
                    {"path": "one.flac", "title": "One", "artist": "Alpha", "album": "First", "cover_url": "alpha-cover"},
                    {"path": "two.flac", "title": "Two", "artist": "Beta", "album": "Second"},
                ]
            )["track_ids"]
            application = create_app(data_dir=root / "application")
            application.dependency_overrides[get_catalog] = lambda: catalog

            with TestClient(application) as client:
                health = client.get("/api/health")
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json(), {"status": "ok"})
                tracks = client.get("/api/tracks?limit=1&offset=1")
                self.assertEqual(tracks.status_code, 200)
                self.assertEqual(tracks.json()["total"], 2)
                self.assertEqual([track["title"] for track in tracks.json()["items"]], ["Two"])
                albums = client.get("/api/albums")
                self.assertEqual(albums.status_code, 200)
                self.assertEqual({item["name"] for item in albums.json()["items"]}, {"First", "Second"})
                album_favorite = client.put("/api/albums/favorite", json={"album": "First", "favorite": True})
                self.assertEqual(album_favorite.status_code, 200)
                self.assertTrue(album_favorite.json()["favorite"])
                self.assertEqual([item["name"] for item in client.get("/api/albums?favorite=true").json()["items"]], ["First"])
                recent_albums = client.get("/api/albums?sort=recent")
                self.assertEqual(recent_albums.status_code, 200)
                self.assertEqual(recent_albums.json()["sort"], "recent")
                artists = client.get("/api/artists")
                self.assertEqual(artists.status_code, 200)
                self.assertEqual({item["name"] for item in artists.json()["items"]}, {"Alpha", "Beta"})
                self.assertIsNone(next(item for item in artists.json()["items"] if item["name"] == "Alpha")["artist_image_status"])
                catalog.save_artist_image("Alpha", None, "missing", "wikimedia")
                alpha = next(item for item in client.get("/api/artists").json()["items"] if item["name"] == "Alpha")
                self.assertEqual(alpha["artist_image_status"], "missing")
                self.assertEqual(client.get("/api/catalog/initials?kind=songs").json()["items"], ["A", "B"])

                created = client.post("/api/playlists", json={"name": "Drive"})
                self.assertEqual(created.status_code, 201)
                playlist_id = created.json()["id"]
                playlists = client.get("/api/playlists")
                self.assertEqual(playlists.status_code, 200)
                self.assertEqual(len(playlists.json()), 1)
                playlist = client.get(f"/api/playlists/{playlist_id}")
                self.assertEqual(playlist.status_code, 200)
                self.assertEqual(playlist.json()["name"], "Drive")

                renamed = client.patch(f"/api/playlists/{playlist_id}", json={"name": "Night"})
                self.assertEqual(renamed.status_code, 200)
                self.assertEqual(renamed.json()["name"], "Night")
                added = client.post(
                    f"/api/playlists/{playlist_id}/tracks", json={"track_id": track_ids[0]}
                )
                self.assertEqual(added.status_code, 201)
                self.assertEqual([track["id"] for track in added.json()["tracks"]], [track_ids[0]])
                ordered = client.put(
                    f"/api/playlists/{playlist_id}/tracks",
                    json={"track_ids": [track_ids[1], track_ids[0]]},
                )
                self.assertEqual(ordered.status_code, 200)
                self.assertEqual(
                    [track["id"] for track in ordered.json()["tracks"]],
                    [track_ids[1], track_ids[0]],
                )
                removed = client.delete(f"/api/playlists/{playlist_id}/tracks/{track_ids[0]}")
                self.assertEqual(removed.status_code, 200)
                self.assertEqual([track["id"] for track in removed.json()["tracks"]], [track_ids[1]])

                preference = client.put(
                    f"/api/tracks/{track_ids[0]}/preference", json={"rating": 4, "favorite": True}
                )
                self.assertEqual(preference.status_code, 200)
                self.assertEqual(preference.json()["rating"], 4)
                invalid_preference = client.put(
                    f"/api/tracks/{track_ids[0]}/preference", json={"rating": 8}
                )
                self.assertEqual(invalid_preference.status_code, 422)
                self.assertEqual(invalid_preference.json()["error"]["code"], "validation_error")

                saved = client.patch("/api/settings", json={"mpd_host": "novin", "mpd_port": "6600"})
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(saved.json(), {"mpd_host": "novin", "mpd_port": "6600"})
                settings = client.get("/api/settings")
                self.assertEqual(settings.status_code, 200)
                self.assertEqual(settings.json(), {"mpd_host": "novin", "mpd_port": "6600"})
                rejected = client.patch("/api/settings", json={"mpd_password": "placeholder"})
                self.assertEqual(rejected.status_code, 422)
                self.assertEqual(rejected.json()["error"]["code"], "validation_error")

                self.assertEqual(client.delete(f"/api/playlists/{playlist_id}").status_code, 204)
                missing = client.get(f"/api/playlists/{playlist_id}")
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(missing.json()["error"]["code"], "not_found")

            application.dependency_overrides.clear()
            catalog.close()
