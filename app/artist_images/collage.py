from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from app.catalog import Catalog


class ArtistCollageResolver:
    """Build and retain one compact four-cover collage per artist signature."""

    def __init__(self, catalog: Catalog, cache_dir: Path):
        self.catalog = catalog
        self.cache_dir = Path(cache_dir)

    def version(self, artist: str) -> Optional[str]:
        sources = self.catalog.artist_album_cover_urls(artist)
        return self._key(sources) if sources else None

    def resolve(self, artist: str) -> Optional[tuple[bytes, str]]:
        sources = self.catalog.artist_album_cover_urls(artist)
        if not sources:
            return None
        key = self._key(sources)
        cached = self._read(key)
        if cached:
            return cached, key
        images = [self._image(source) for source in sources]
        images = [image for image in images if image is not None]
        if not images:
            return None
        canvas = Image.new("RGB", (512, 512), "#e8e8ea")
        for index, image in enumerate(images[:4]):
            x, y = (index % 2) * 256, (index // 2) * 256
            canvas.paste(ImageOps.fit(image, (256, 256), method=Image.Resampling.LANCZOS), (x, y))
        output = io.BytesIO()
        canvas.save(output, format="JPEG", quality=82, optimize=True)
        payload = output.getvalue()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_dir / f".{key}.tmp"
        temporary.write_bytes(payload)
        os.replace(temporary, self.cache_dir / key)
        return payload, key

    @staticmethod
    def _key(sources: list[str]) -> str:
        payload = "artist-collage-v1\0" + "\0".join(sources)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _read(self, key: str) -> Optional[bytes]:
        try:
            data = (self.cache_dir / key).read_bytes()
        except OSError:
            return None
        return data if data.startswith(b"\xff\xd8\xff") else None

    def _image(self, source: str) -> Optional[Image.Image]:
        cover_id = source.rsplit("/", 1)[-1]
        if len(cover_id) != 64 or not cover_id.isalnum():
            return None
        try:
            with Image.open(self.cache_dir / cover_id) as image:
                return image.convert("RGB")
        except (OSError, ValueError):
            return None
