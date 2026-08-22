import hashlib
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.artist_images import ArtistCollageResolver
from app.catalog import Catalog


def image_data(color):
    output = BytesIO()
    Image.new("RGB", (20, 20), color).save(output, "JPEG")
    return output.getvalue()


class ArtistCollageResolverTests(unittest.TestCase):
    def test_creates_and_reuses_a_single_jpeg_for_album_covers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = Catalog(root / "catalog.sqlite3")
            covers = root / "covers"
            covers.mkdir()
            tracks = []
            for index, color in enumerate(("red", "blue"), start=1):
                payload = image_data(color)
                cover_id = hashlib.sha256(payload).hexdigest()
                (covers / cover_id).write_bytes(payload)
                tracks.append({"path": f"{index}.flac", "title": str(index), "artist": "Artist", "album": f"Album {index}", "cover_url": f"/api/covers/{cover_id}"})
            catalog.reconcile_tracks(tracks)
            resolver = ArtistCollageResolver(catalog, covers)
            first = resolver.resolve("Artist")
            self.assertIsNotNone(first)
            payload, key = first
            self.assertTrue(payload.startswith(b"\xff\xd8\xff"))
            self.assertTrue((covers / key).exists())
            self.assertEqual(resolver.resolve("Artist"), first)
            catalog.close()
