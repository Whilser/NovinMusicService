import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.player import get_mpd_client
from app.catalog import Catalog
from app.dependencies import get_catalog
from app.main import create_app
from app.mpd import MpdConnectionError


class FakeMpdClient:
    def __init__(self):
        self.offline = True
        self.calls = []

    def status(self):
        if self.offline:
            raise MpdConnectionError("connection refused")
        return {"online": True, "state": "play", "song": {"file": "one.flac"}}

    def command(self, name, **params):
        if self.offline:
            raise MpdConnectionError("connection refused")
        self.calls.append(("command", name, params))
        return {"online": True, "state": "pause", "song": None}

    def play_uris(self, paths, shuffle=False):
        if self.offline:
            raise MpdConnectionError("connection refused")
        self.calls.append(("play", list(paths), shuffle))
        return {"online": True, "state": "play", "song": {"file": paths[0]}}


class PlayerApiTests(unittest.TestCase):
    def test_player_http_contract_and_offline_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = Catalog(root / "catalog.sqlite3")
            track_ids = catalog.reconcile_tracks(
                [
                    {"path": "one.flac", "title": "One"},
                    {"path": "folder/two.flac", "title": "Two"},
                ]
            )["track_ids"]
            fake = FakeMpdClient()
            application = create_app(data_dir=root / "app")
            application.dependency_overrides[get_catalog] = lambda: catalog
            application.dependency_overrides[get_mpd_client] = lambda: fake

            with TestClient(application) as client:
                offline = client.get("/api/player/status")
                self.assertEqual(offline.status_code, 200)
                offline_contract = {
                    "online": False,
                    "state": "offline",
                    "song": None,
                    "message": "MPD is unavailable",
                }
                self.assertEqual(offline.json(), offline_contract)
                offline_command = client.post(
                    "/api/player/command",
                    json={"command": "next", "params": {}},
                )
                self.assertEqual(offline_command.status_code, 503)
                self.assertEqual(offline_command.json(), offline_contract)
                offline_play = client.post(
                    "/api/player/play",
                    json={"track_ids": track_ids, "shuffle": False},
                )
                self.assertEqual(offline_play.status_code, 503)
                self.assertEqual(offline_play.json(), offline_contract)

                fake.offline = False
                command = client.post(
                    "/api/player/command",
                    json={"command": "seek", "params": {"position": 12}},
                )
                self.assertEqual(command.status_code, 200)
                self.assertEqual(command.json()["state"], "pause")
                self.assertEqual(fake.calls[-1], ("command", "seek", {"position": 12}))
                played = client.post(
                    "/api/player/play",
                    json={"track_ids": track_ids, "shuffle": False},
                )
                self.assertEqual(played.status_code, 200)
                self.assertEqual(fake.calls[-1], ("play", ["one.flac", "folder/two.flac"], False))
                tested = client.post("/api/settings/test-mpd")
                self.assertEqual(tested.json()["online"], True)
                forbidden = client.post(
                    "/api/player/command",
                    json={"command": "save", "params": {"name": "nope"}},
                )
                self.assertEqual(forbidden.status_code, 422)
                self.assertEqual(forbidden.json()["error"]["code"], "invalid_player_command")

            application.dependency_overrides.clear()
            catalog.close()

    def test_mpd_client_dependency_uses_catalog_settings_and_environment_password(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            catalog.update_settings(
                {"mpd_host": "novin", "mpd_port": "7777", "mpd_uri_prefix": "nas/music"}
            )
            with patch.dict("os.environ", {"MPD_PASSWORD": "env-only-password"}):
                client = get_mpd_client(catalog)
            self.assertEqual(client.host, "novin")
            self.assertEqual(client.port, 7777)
            self.assertEqual(client.uri_prefix, "nas/music")
            self.assertEqual(client.password, "env-only-password")
            catalog.close()

    def test_invalid_mpd_port_is_reported_as_settings_validation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = Catalog(root / "catalog.sqlite3")
            catalog.update_settings({"mpd_port": "not-a-port"})
            application = create_app(data_dir=root / "app")
            application.dependency_overrides[get_catalog] = lambda: catalog
            with TestClient(application) as client:
                response = client.post("/api/settings/test-mpd")
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json(),
                    {
                        "error": {
                            "code": "invalid_mpd_settings",
                            "message": "mpd_port must be an integer between 1 and 65535",
                        }
                    },
                )
            application.dependency_overrides.clear()
            catalog.close()


if __name__ == "__main__":
    unittest.main()
