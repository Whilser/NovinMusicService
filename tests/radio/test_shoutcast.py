import json
import tempfile
import unittest
from pathlib import Path

from app.radio import HybridRadioDirectory, RadioBrowserDirectory, ShoutcastDirectory


class ShoutcastDirectoryTests(unittest.TestCase):
    def test_unconfigured_directory_has_a_safe_empty_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = ShoutcastDirectory(Path(directory) / "radio.json", api_key="")
            result = catalog.list_stations()
            self.assertFalse(result["configured"])
            self.assertEqual(result["genre"], "All")
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

    def test_keyless_radio_browser_catalog_is_used_by_the_hybrid_directory(self):
        payload = [{"stationuuid": "8c0c551f-33bb-44cc-88dd-000000000001", "name": "Free Radio", "tags": "jazz", "url_resolved": "https://stream.example.net/live", "votes": 7, "bitrate": 128}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = RadioBrowserDirectory(root / "browser.json", fetch=lambda _: json.dumps(payload).encode(), servers=lambda: ["https://de1.api.radio-browser.info"])
            hybrid = HybridRadioDirectory(ShoutcastDirectory(root / "shoutcast.json", api_key=""), browser)
            result = hybrid.list_stations("Jazz")
            self.assertEqual(result["source"], "radio_browser")
            self.assertEqual(result["stations"][0]["name"], "Free Radio")
            self.assertEqual(hybrid.station("8c0c551f-33bb-44cc-88dd-000000000001")["bitrate"], 128)

    def test_radio_browser_uses_an_exact_tag_and_refreshes_on_genre_selection(self):
        payload = [{"stationuuid": "8c0c551f-33bb-44cc-88dd-000000000002", "name": "Strict Rock", "tags": "rock", "url_resolved": "https://stream.example.net/rock"}]
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            catalog = RadioBrowserDirectory(
                Path(directory) / "browser.json",
                fetch=lambda url: calls.append(url) or json.dumps(payload).encode(),
                servers=lambda: ["https://de1.api.radio-browser.info"],
            )
            catalog.list_stations("Rock")
            catalog.list_stations("Rock", refresh=True)
            self.assertEqual(len(calls), 8)
            self.assertTrue(all(any(path in url for path in ("/bytag/Rock?", "/topclick/8?", "/topvote/8?", "/lastclick/8?")) for url in calls))
