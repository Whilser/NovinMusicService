import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.player import get_mpd_client
from app.main import create_app
from app.radio import ShoutcastDirectory


class _RadioMpd:
    def __init__(self):
        self.stream = None

    def play_stream(self, stream_url):
        self.stream = stream_url
        return {"online": True, "state": "play", "song": {"file": stream_url}}


class RadioApiTests(unittest.TestCase):
    def test_catalog_and_station_play_use_cached_directory_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = create_app(data_dir=root)
            application.state.radio_directory = ShoutcastDirectory(
                root / "radio-cache.json", api_key="key", fetch=lambda _: b'{"stationlist":{"station":{"id":"7","name":"Radio Seven"}}}'
            )
            mpd = _RadioMpd()
            application.dependency_overrides[get_mpd_client] = lambda: mpd
            with TestClient(application) as client:
                catalog = client.get("/api/radio?genre=Pop")
                self.assertEqual(catalog.status_code, 200)
                self.assertEqual(catalog.json()["stations"][0]["id"], "7")
                station = catalog.json()["stations"][0]
                favorite = client.put("/api/radio/stations/7/favorite", json={"station": station, "favorite": True})
                self.assertEqual(favorite.status_code, 200)
                self.assertEqual(client.get("/api/radio/favorites").json()[0]["id"], "7")
                played = client.post("/api/radio/play", json={"station_id": "7"})
                self.assertEqual(played.status_code, 200)
                self.assertEqual(mpd.stream, "https://yp.shoutcast.com/sbin/tunein-station.pls?id=7")
            application.dependency_overrides.clear()
