import json
import tempfile
import unittest
from pathlib import Path

from app.radio import ShoutcastDirectory


class ShoutcastDirectoryTests(unittest.TestCase):
    def test_unconfigured_directory_has_a_safe_empty_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = ShoutcastDirectory(Path(directory) / "radio.json", api_key="")
            result = catalog.list_stations()
            self.assertFalse(result["configured"])
            self.assertEqual(result["genre"], "Pop")
            self.assertIn("Rock", result["genres"])

    def test_directory_sanitizes_and_persists_a_cached_station(self):
        payload = {
            "stationlist": {
                "tunein": {"base": "/sbin/tunein-station.pls"},
                "station": [{"id": "42", "name": "  Novin   FM ", "genre": "Pop", "ct": "Artist - Song", "lc": "24", "br": "128"}],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "radio.json"
            calls = []
            catalog = ShoutcastDirectory(cache_path, api_key="key", fetch=lambda url: calls.append(url) or json.dumps(payload).encode())
            result = catalog.list_stations("Pop")
            self.assertTrue(result["configured"])
            self.assertEqual(result["stations"][0]["name"], "Novin FM")
            self.assertEqual(result["stations"][0]["stream_url"], "https://yp.shoutcast.com/sbin/tunein-station.pls?id=42")
            self.assertEqual(catalog.station("42")["name"], "Novin FM")
            self.assertEqual(len(calls), 1)
            restored = ShoutcastDirectory(cache_path, api_key="key", fetch=lambda _: self.fail("cache should be used"))
            self.assertEqual(restored.list_stations("Pop")["stations"][0]["id"], "42")

