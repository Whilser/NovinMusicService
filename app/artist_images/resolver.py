from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.catalog import Catalog
from app.scanner.scanner import MAX_COVER_BYTES


WIKIPEDIA_API = "https://ru.wikipedia.org/w/api.php"
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _normal(value: str) -> str:
    return re.sub(r"[^\w]+", "", value.casefold(), flags=re.UNICODE)


def _matches_artist(artist: str, title: str) -> bool:
    normalized = _normal(artist)
    if not normalized or not any(character.isalpha() for character in normalized):
        return False
    stem = title.split("(", 1)[0].strip()
    return normalized == _normal(stem)


class ArtistImageResolver:
    """Fetch exact Wikipedia artist thumbnails once and retain them locally."""

    def __init__(
        self, catalog: Catalog, cache_dir: Path,
        fetch: Optional[Callable[[str, dict[str, str]], tuple[bytes, str]]] = None,
    ):
        self.catalog = catalog
        self.cache_dir = Path(cache_dir)
        self.fetch = fetch or self._fetch
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def resolve(self, artist: str) -> Optional[tuple[bytes, str, str]]:
        artist = artist.strip()
        if not artist or not any(character.isalpha() for character in artist):
            return None
        with self._lock_for(artist):
            cached = self.catalog.artist_image(artist)
            if cached and cached["status"] == "missing":
                return None
            if cached and cached.get("cover_id"):
                payload = self._read(cached["cover_id"])
                if payload:
                    return (*payload, cached["cover_id"])
            try:
                image_url = self._lookup(artist)
                if not image_url:
                    self.catalog.save_artist_image(artist, None, "missing", "wikimedia")
                    return None
                payload, mime_type = self.fetch(image_url, {"Accept": "image/avif,image/webp,image/*"})
                if mime_type not in IMAGE_TYPES or not payload or len(payload) > MAX_COVER_BYTES:
                    raise ValueError("unsupported artist image")
            except Exception:
                self.catalog.save_artist_image(artist, None, "missing", "wikimedia")
                return None
            cover_id = hashlib.sha256(payload).hexdigest()
            self._write(cover_id, payload)
            self.catalog.save_artist_image(artist, cover_id, "ready", "wikimedia")
            return payload, mime_type, cover_id

    def _lookup(self, artist: str) -> Optional[str]:
        params = {
            "action": "query", "generator": "search", "gsrsearch": artist,
            "gsrnamespace": "0", "gsrlimit": "1", "prop": "pageimages",
            "piprop": "thumbnail", "pithumbsize": "500", "format": "json", "formatversion": "2",
        }
        payload, mime_type = self.fetch(f"{WIKIPEDIA_API}?{urlencode(params)}", {"Accept": "application/json"})
        if mime_type != "application/json":
            return None
        pages = json.loads(payload.decode("utf-8")).get("query", {}).get("pages", [])
        if not pages:
            return None
        page = pages[0]
        if not _matches_artist(artist, str(page.get("title", ""))):
            return None
        thumbnail = page.get("thumbnail", {})
        return thumbnail.get("source") if isinstance(thumbnail, dict) else None

    def _lock_for(self, artist: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(artist.casefold(), threading.Lock())

    def _read(self, cover_id: str) -> Optional[tuple[bytes, str]]:
        try:
            payload = (self.cache_dir / cover_id).read_bytes()
        except OSError:
            return None
        if not payload or len(payload) > MAX_COVER_BYTES:
            return None
        return payload, self._mime(payload)

    def _write(self, cover_id: str, payload: bytes) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_dir / f".{cover_id}.tmp"
        temporary.write_bytes(payload)
        os.replace(temporary, self.cache_dir / cover_id)

    @staticmethod
    def _mime(payload: bytes) -> str:
        if payload.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    @staticmethod
    def _fetch(url: str, headers: dict[str, str]) -> tuple[bytes, str]:
        request = Request(url, headers={"User-Agent": "NovinMusicService/1.0", **headers})
        with urlopen(request, timeout=5) as response:  # nosec B310: fixed Wikimedia origin or returned thumbnail URL
            mime_type = response.headers.get_content_type()
            payload = response.read(MAX_COVER_BYTES + 1)
        return payload, mime_type
