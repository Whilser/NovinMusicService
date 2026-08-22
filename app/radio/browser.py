from __future__ import annotations

import json
import random
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlencode, urlparse

from .shoutcast import DEFAULT_GENRES, RadioDirectoryError


_CACHE_TTL_SECONDS = 15 * 60
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_UPSTREAM_LIMIT = 8
ALL_GENRE = "All"
RADIO_GENRES = (ALL_GENRE, *DEFAULT_GENRES)


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

    def list_stations(self, genre: str = ALL_GENRE, search: str = "", limit: int = 18, refresh: bool = False) -> dict[str, Any]:
        normalized_genre = self._clean_text(genre, 48) or ALL_GENRE
        if normalized_genre.casefold() == ALL_GENRE.casefold():
            normalized_genre = ALL_GENRE
        normalized_search = self._clean_text(search, 100)
        bounded_limit = max(1, min(int(limit), 40))
        # The suffix prevents older broad genre results in the persistent cache
        # from being reused after switching to exact tag matching.
        cache_key = f"exact-tag-v1|{normalized_genre.casefold()}|{normalized_search.casefold()}|{bounded_limit}"
        with self._lock:
            if not refresh:
                cached = self._load_cached(cache_key)
                if cached is not None:
                    return cached
            try:
                parameters = {"limit": str(min(bounded_limit, _UPSTREAM_LIMIT)), "hidebroken": "true", "order": "votes", "reverse": "true"}
                if normalized_search:
                    parameters["name"] = normalized_search
                    stations = self._stations(self._payload("/json/stations/search", parameters), bounded_limit)
                elif normalized_genre == ALL_GENRE:
                    stations = self._stations(self._payload("/json/stations/topclick/8", {"hidebroken": "true"}), bounded_limit)
                    if len(stations) < bounded_limit:
                        stations = self._merge_stations(stations, self._stations(self._payload("/json/stations/topvote/8", {"hidebroken": "true"}), 8), limit=bounded_limit)
                    if len(stations) < bounded_limit:
                        stations = self._merge_stations(stations, self._stations(self._payload("/json/stations/lastclick/8", {"hidebroken": "true"}), 8), limit=bounded_limit)
                else:
                    # The exact endpoint compares the complete comma-separated
                    # tag string and therefore drops almost every useful
                    # station.  Use the tag endpoint, then do an exact match
                    # against individual tags ourselves.
                    genre_path = f"/json/stations/bytag/{quote(normalized_genre, safe='')}"
                    stations = self._filter_genre(self._stations(self._payload(genre_path, parameters), bounded_limit), normalized_genre)
                    # A small popular-stations supplement avoids an empty
                    # screen when a mirror has a shallow genre index, while
                    # retaining only stations with the selected tag.
                    for popular_path in ("/json/stations/topclick/8", "/json/stations/topvote/8", "/json/stations/lastclick/8"):
                        if len(stations) >= bounded_limit:
                            break
                        popular = self._filter_genre(self._stations(self._payload(popular_path, {"hidebroken": "true"}), 8), normalized_genre)
                        stations = self._merge_stations(stations, popular, limit=bounded_limit)
            except (OSError, ValueError, UnicodeError, subprocess.SubprocessError, RadioDirectoryError) as error:
                raise RadioDirectoryError("Не удалось загрузить открытый каталог радио") from error
            result = {"configured": True, "source": "radio_browser", "genres": list(RADIO_GENRES), "genre": normalized_genre, "stations": stations}
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

    def _payload(self, path: str, parameters: dict[str, str]) -> list[Any]:
        servers = [server.rstrip("/") for server in self.servers() if self._safe_server(server)]
        if not servers:
            raise RadioDirectoryError("no Radio Browser server available")
        random.shuffle(servers)
        last_error: Exception | None = None
        for server in servers:
            try:
                payload = json.loads(self.fetch(f"{server}{path}?{urlencode(parameters)}").decode("utf-8"))
                if isinstance(payload, list):
                    return payload
                raise RadioDirectoryError("invalid Radio Browser response")
            except (OSError, ValueError, UnicodeError, subprocess.SubprocessError, RadioDirectoryError) as error:
                last_error = error
        raise RadioDirectoryError("all Radio Browser servers failed") from last_error

    @staticmethod
    def _filter_genre(stations: list[dict[str, Any]], genre: str) -> list[dict[str, Any]]:
        wanted = genre.casefold()
        return [
            station for station in stations
            if wanted in {tag.strip().casefold() for tag in str(station.get("genre", "")).split(",") if tag.strip()}
        ]

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
        for fallback in ("de2.api.radio-browser.info", "de1.api.radio-browser.info"):
            if fallback not in names:
                names.append(fallback)
        return [f"https://{name}" for name in names]

    @staticmethod
    def _fetch(url: str) -> bytes:
        result = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "5", "--user-agent", "NovinMusicService/1.0", url],
            check=True,
            capture_output=True,
            timeout=6,
        )
        payload = result.stdout
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
    def _merge_stations(*groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for group in groups:
            for station in group:
                station_id = str(station.get("id", ""))
                if not station_id or station_id in seen:
                    continue
                seen.add(station_id)
                merged.append(station)
                if len(merged) >= limit:
                    return merged
        return merged

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
