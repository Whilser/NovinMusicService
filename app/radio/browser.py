from __future__ import annotations

import json
import random
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .shoutcast import DEFAULT_GENRES, RadioDirectoryError


_CACHE_TTL_SECONDS = 15 * 60
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class RadioBrowserDirectory:
    """Keyless Radio Browser directory client with a persistent short-lived cache."""

    def __init__(
        self,
        cache_path: Path,
        fetch: Callable[[str], bytes] | None = None,
        servers: Callable[[], Iterable[str]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.fetch = fetch or self._fetch
        self.servers = servers or self._servers
        self.clock = clock
        self._lock = threading.RLock()
        self._memory: dict[str, dict[str, Any]] = {}

    def list_stations(self, genre: str = "Pop", search: str = "", limit: int = 18) -> dict[str, Any]:
        normalized_genre = self._clean_text(genre, 48) or DEFAULT_GENRES[0]
        normalized_search = self._clean_text(search, 100)
        bounded_limit = max(1, min(int(limit), 40))
        cache_key = f"{normalized_genre.casefold()}|{normalized_search.casefold()}|{bounded_limit}"
        with self._lock:
            cached = self._load_cached(cache_key)
            if cached is not None:
                return cached
            parameters = {"limit": str(bounded_limit), "hidebroken": "true", "order": "votes", "reverse": "true"}
            if normalized_search:
                parameters["name"] = normalized_search
            else:
                parameters["tag"] = normalized_genre
            try:
                station_url = self._station_url(parameters)
                payload = json.loads(self.fetch(station_url).decode("utf-8"))
                if not isinstance(payload, list):
                    raise RadioDirectoryError("invalid Radio Browser response")
                stations = self._stations(payload, bounded_limit)
            except (OSError, ValueError, UnicodeError, RadioDirectoryError) as error:
                raise RadioDirectoryError("Не удалось загрузить открытый каталог радио") from error
            result = {"configured": True, "source": "radio_browser", "genres": list(DEFAULT_GENRES), "genre": normalized_genre, "stations": stations}
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

    def _station_url(self, parameters: dict[str, str]) -> str:
        servers = [server.rstrip("/") for server in self.servers() if self._safe_server(server)]
        if not servers:
            raise RadioDirectoryError("no Radio Browser server available")
        return f"{random.choice(servers)}/json/stations/search?{urlencode(parameters)}"

    @staticmethod
    def _safe_server(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and parsed.hostname.endswith(".api.radio-browser.info")

    @staticmethod
    def _servers() -> list[str]:
        names: list[str] = []
        try:
            addresses = socket.getaddrinfo("all.api.radio-browser.info", 443, type=socket.SOCK_STREAM)
            for address in addresses:
                host = address[4][0]
                try:
                    name = socket.gethostbyaddr(host)[0].rstrip(".").lower()
                except OSError:
                    continue
                if name.endswith(".api.radio-browser.info") and name not in names:
                    names.append(name)
        except OSError:
            pass
        return [f"https://{name}" for name in names] or ["https://de1.api.radio-browser.info"]

    @staticmethod
    def _fetch(url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "NovinMusicService/1.0"})
        with urlopen(request, timeout=5) as response:  # nosec B310: server is validated above
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise RadioDirectoryError("Radio Browser response is too large")
        return payload

    def _stations(self, payload: list[Any], limit: int) -> list[dict[str, Any]]:
        stations: list[dict[str, Any]] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            station_id = self._clean_text(raw.get("stationuuid", ""), 64)
            name = self._clean_text(raw.get("name", ""), 120)
            stream_url = self._stream_url(raw.get("url_resolved") or raw.get("url"))
            if not station_id or not name or not stream_url:
                continue
            stations.append({
                "id": station_id,
                "name": name,
                "genre": self._clean_text(raw.get("tags", ""), 100) or "Интернет-радио",
                "now_playing": self._clean_text(raw.get("codec", ""), 80),
                "listeners": self._as_int(raw.get("votes")),
                "bitrate": self._as_int(raw.get("bitrate")),
                "stream_url": stream_url,
            })
            if len(stations) >= limit:
                break
        return stations

    @staticmethod
    def _stream_url(value: Any) -> str | None:
        target = str(value or "").strip()
        if len(target) > 2048 or any(ord(character) < 32 for character in target):
            return None
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        hostname = parsed.hostname.lower()
        if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
            return None
        return target

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
    def _clean_text(value: Any, maximum: int) -> str:
        return " ".join(str(value or "").split())[:maximum]

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
