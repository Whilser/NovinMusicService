import json
import tempfile
import unittest
from pathlib import Path

from app.artist_images import ArtistImageResolver
from app.catalog import Catalog


class ArtistImageResolverTests(unittest.TestCase):
    def test_exact_match_is_downloaded_once_and_reused_from_local_cache(self):
        requests = []

        def fetch(url, headers):
            requests.append(url)
            if url.startswith("https://ru.wikipedia.org/"):
                return json.dumps({"query": {"pages": [{"title": "A-Ha", "thumbnail": {"source": "https://images.example/a-ha.jpg"}}]}}).encode(), "application/json"
            return b"\xff\xd8\xffartist", "image/jpeg"

        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            resolver = ArtistImageResolver(catalog, Path(directory) / "covers", fetch=fetch)
            first = resolver.resolve("A-Ha")
            second = resolver.resolve("A-Ha")

            self.assertEqual(first[0], b"\xff\xd8\xffartist")
            self.assertEqual(second, first)
            self.assertEqual(len(requests), 2)
            self.assertEqual(catalog.artist_image("A-Ha")["status"], "ready")
            catalog.close()

    def test_non_artist_and_nonmatching_page_are_cached_as_missing(self):
        calls = []

        def fetch(url, headers):
            calls.append(url)
            return json.dumps({"query": {"pages": [{"title": "Queen (группа)", "thumbnail": {"source": "https://images.example/queen.jpg"}}]}}).encode(), "application/json"

        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / "catalog.sqlite3")
            resolver = ArtistImageResolver(catalog, Path(directory) / "covers", fetch=fetch)
            self.assertIsNone(resolver.resolve("2002"))
            self.assertIsNone(resolver.resolve("A-Ha"))
            self.assertIsNone(resolver.resolve("A-Ha"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(catalog.artist_image("A-Ha")["status"], "missing")
            catalog.close()


if __name__ == "__main__":
    unittest.main()
