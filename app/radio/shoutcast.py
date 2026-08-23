from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen


class RadioDirectoryError(Exception):
    """The upstream radio directory could not provide a usable station list."""


DEFAULT_GENRES = ("Pop", "Rock", "Dance", "Hip Hop", "Jazz", "Classical", "Electronic", "Chillout", "Russian")
RADIO_GENRES = ("All", *DEFAULT_GENRES)
_CACHE_TTL_SECONDS = 15 * 60
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ShoutcastDirectory:
    """Small, cached boundary around the documented SHOUTcast directory API."""

    def __init__(
        self,
        cache_path: Path,
        api_key: str | None = None,
        fetch: Callable[[str], bytes] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.api_key = (api_key if api_key is not None else os.environ.get("SHOUTCAST_API_KEY", "")).strip()
        self.fetch = fetch or self._fetch
        self.clock = clock
        self._lock = threading.RLock()
        self._memory: dict[str, dict[str, Any]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def list_stations(self, genre: str = "All", search: str = "", limit: int = 18, refresh: bool = False) -> dict[str, Any]:
        normalized_genre = self._clean_text(genre, 48) or "All"
        if normalized_genre.casefold() == "all":
            normalized_genre = "All"
        normalized_search = self._clean_text(search, 100)
        bounded_limit = max(1, min(int(limit), 40))
        if not self.configured:
            return {"configured": False, "genres": list(RADIO_GENRES), "genre": normalized_genre, "stations": []}
        cache_key = f"{normalized_genre.casefold()}|{normalized_search.casefold()}|{bounded_limit}"
        with self._lock:
            if not refresh:
                cached = self._load_cached(cache_key)
                if cached is not None:
                    return cached
            command = "stationsearch" if normalized_search or normalized_genre == "All" else "genresearch"
            params = {"k": self.api_key, "f": "json", "limit": str(bounded_limit)}
            if normalized_search:
                params["search"] = normalized_search
            elif normalized_genre != "All":
                params["genre"] = normalized_genre
            try:
                payload = self._decode(self.fetch(f"https://api.shoutcast.com/legacy/{command}?{urlencode(params)}"))
                stations = self._stations(payload, bounded_limit)
            except (OSError, ValueError, UnicodeError, RadioDirectoryError) as error:
                raise RadioDirectoryError("Не удалось загрузить каталог Shoutcast") from error
            result = {"configured": True, "source": "shoutcast", "genres": list(RADIO_GENRES), "genre": normalized_genre, "stations": stations}
            self._memory[cache_key] = {"saved_at": self.clock(), "value": result}
            self._write_cache()
            return result

    def station(self, station_id: str | int) -> dict[str, Any] | None:
        wanted = str(station_id)
        with self._lock:
            for cached in self._all_cached_values():
                for station in cached.get("stations", []):
                    if station.get("id") == wanted:
                        return station
        return None

    def _load_cached(self, key: str) -> dict[str, Any] | None:
        if not self._memory:
            self._read_cache()
        cached = self._memory.get(key)
        if cached and self.clock() - float(cached.get("saved_at", 0)) < _CACHE_TTL_SECONDS:
            return cached["value"]
        return None

    def _all_cached_values(self):
        if not self._memory:
            self._read_cache()
        for cached in self._memory.values():
            if self.clock() - float(cached.get("saved_at", 0)) < _CACHE_TTL_SECONDS:
                yield cached.get("value", {})

    def _read_cache(self) -> None:
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._memory = {str(key): value for key, value in raw.items() if isinstance(value, dict)}
        except (OSError, ValueError, UnicodeError):
            self._memory = {}

    def _write_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._memory, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.cache_path)

    @staticmethod
    def _fetch(url: str) -> bytes:
        with urlopen(url, timeout=5) as response:  # nosec B310: fixed HTTPS Shoutcast endpoint
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise RadioDirectoryError("Shoutcast response is too large")
        return payload

    @staticmethod
    def _decode(payload: bytes) -> dict[str, Any]:
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RadioDirectoryError("invalid Shoutcast response")
        return decoded

    def _stations(self, payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        station_list = payload.get("stationlist", {})
        if not isinstance(station_list, dict):
            return []
        raw_stations = station_list.get("station", [])
        if isinstance(raw_stations, dict):
            raw_stations = [raw_stations]
        if not isinstance(raw_stations, list):
            return []
        tunein = station_list.get("tunein", {})
        base = tunein.get("base", "/sbin/tunein-station.pls") if isinstance(tunein, dict) else "/sbin/tunein-station.pls"
        stations: list[dict[str, Any]] = []
        for raw in raw_stations:
            if not isinstance(raw, dict):
                continue
            station_id = str(raw.get("id", "")).strip()
            name = self._clean_text(raw.get("name", ""), 120)
            if not station_id.isdigit() or not name:
                continue
            stream_url = self._tunein_url(str(base), station_id)
            if not stream_url:
                continue
            stations.append({
                "id": station_id,
                "name": name,
                "genre": self._clean_text(raw.get("genre", ""), 100) or "Shoutcast",
                "now_playing": self._clean_text(raw.get("ct", ""), 160),
                "listeners": self._as_int(raw.get("lc")),
                "bitrate": self._as_int(raw.get("br")),
                "stream_url": stream_url,
            })
            if len(stations) >= limit:
                break
        return stations

    @staticmethod
    def _tunein_url(base: str, station_id: str) -> str | None:
        target = base.strip()
        if target.startswith("/"):
            target = f"https://yp.shoutcast.com{target}"
        parsed = urlparse(target)
        if parsed.scheme != "https" or parsed.netloc != "yp.shoutcast.com":
            return None
        separator = "&" if "?" in target else "?"
        return f"{target}{separator}id={station_id}"

    @staticmethod
    def _clean_text(value: Any, maximum: int) -> str:
        return " ".join(str(value or "").split())[:maximum]

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
