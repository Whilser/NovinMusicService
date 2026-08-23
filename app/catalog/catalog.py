from __future__ import annotations

import sqlite3
import threading
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .errors import ConflictError, NotFoundError, ValidationError


TRACK_FIELDS = (
    "id", "path", "title", "artist", "album", "album_artist", "track_no",
    "disc_no", "year", "genre", "duration", "cover_url", "rating", "favorite",
)
ALLOWED_SETTINGS = frozenset(
    {
        "smb_host", "smb_share", "smb_username", "smb_mount_path", "smb_domain", "smb_options",
        "mpd_host", "mpd_port", "mpd_uri_prefix", "catalog_page_size", "album_sort",
    }
)
SECRET_MARKERS = ("password", "secret", "token", "credential", "api_key", "apikey")


class Catalog:
    """Persistent boundary for the local media catalog and user-owned metadata."""

    def __init__(self, database_path: Any):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.database_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def initialize(self) -> "Catalog":
        """Idempotently initialize or migrate the catalog database."""
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        return self

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL DEFAULT '',
                    album TEXT NOT NULL DEFAULT '',
                    album_artist TEXT NOT NULL DEFAULT '',
                    track_no INTEGER,
                    disc_no INTEGER,
                    year INTEGER,
                    genre TEXT NOT NULL DEFAULT '',
                    duration REAL,
                    size INTEGER NOT NULL DEFAULT 0,
                    mtime REAL NOT NULL DEFAULT 0,
                    cover_url TEXT,
                    artist_cover_url TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (playlist_id, track_id),
                    UNIQUE (playlist_id, position)
                );
                CREATE TABLE IF NOT EXISTS track_preferences (
                    track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    rating INTEGER CHECK (rating BETWEEN 0 AND 5),
                    favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS scan_runs (
                    id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL,
                    discovered INTEGER NOT NULL DEFAULT 0,
                    indexed INTEGER NOT NULL DEFAULT 0,
                    removed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_scan
                    ON scan_runs(status) WHERE status = 'running';
                CREATE TABLE IF NOT EXISTS artist_images (
                    artist TEXT PRIMARY KEY COLLATE NOCASE,
                    cover_id TEXT,
                    status TEXT NOT NULL CHECK (status IN ('ready','missing')),
                    source TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS radio_stations (
                    station_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    genre TEXT NOT NULL DEFAULT '',
                    now_playing TEXT NOT NULL DEFAULT '',
                    listeners INTEGER,
                    bitrate INTEGER,
                    stream_url TEXT NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
                    blacklisted INTEGER NOT NULL DEFAULT 0 CHECK (blacklisted IN (0, 1)),
                    last_played_at TEXT,
                    blacklisted_at TEXT,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS radio_stations_favorite
                    ON radio_stations(favorite, updated_at DESC);
                CREATE TABLE IF NOT EXISTS radio_catalog_snapshots (
                    cache_key TEXT PRIMARY KEY,
                    genre TEXT NOT NULL,
                    search TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
                """
            )
            columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(radio_stations)")}
            if "blacklisted" not in columns:
                self._connection.execute("ALTER TABLE radio_stations ADD COLUMN blacklisted INTEGER NOT NULL DEFAULT 0")
            if "last_played_at" not in columns:
                self._connection.execute("ALTER TABLE radio_stations ADD COLUMN last_played_at TEXT")
            if "blacklisted_at" not in columns:
                self._connection.execute("ALTER TABLE radio_stations ADD COLUMN blacklisted_at TEXT")
            track_columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(tracks)")}
            if "artist_cover_url" not in track_columns:
                self._connection.execute("ALTER TABLE tracks ADD COLUMN artist_cover_url TEXT")

    @staticmethod
    def _page(page: int, page_size: int) -> tuple[int, int]:
        if not isinstance(page, int) or page < 1:
            raise ValidationError("page must be a positive integer", {"field": "page"})
        if not isinstance(page_size, int) or not 1 <= page_size <= 200:
            raise ValidationError("page_size must be between 1 and 200", {"field": "page_size"})
        return page_size, (page - 1) * page_size

    @staticmethod
    def _track(row: sqlite3.Row) -> dict[str, Any]:
        item = {field: row[field] for field in TRACK_FIELDS}
        item["favorite"] = bool(item["favorite"])
        return item

    def reconcile_tracks(self, tracks: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Atomically make the indexed track set match a complete scan snapshot."""
        snapshot = list(tracks)
        paths = [str(item.get("path", "")).strip() for item in snapshot]
        if any(not path for path in paths):
            raise ValidationError("every track requires a non-empty path", {"field": "path"})
        if len(paths) != len(set(paths)):
            raise ValidationError("track paths must be unique", {"field": "path"})
        existing = {}
        with self._lock, self._connection:
            for item, path in zip(snapshot, paths):
                title = str(item.get("title") or Path(path).stem)
                values = (
                    path, title, str(item.get("artist") or ""), str(item.get("album") or ""),
                    str(item.get("album_artist") or ""), item.get("track_no"), item.get("disc_no"),
                    item.get("year"), str(item.get("genre") or ""), item.get("duration"),
                    int(item.get("size") or 0), float(item.get("mtime") or 0), item.get("cover_url"), item.get("artist_cover_url"),
                )
                self._connection.execute(
                    """INSERT INTO tracks(
                           path,title,artist,album,album_artist,track_no,disc_no,year,genre,
                           duration,size,mtime,cover_url,artist_cover_url
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(path) DO UPDATE SET
                           title=excluded.title,artist=excluded.artist,album=excluded.album,
                           album_artist=excluded.album_artist,track_no=excluded.track_no,
                           disc_no=excluded.disc_no,year=excluded.year,genre=excluded.genre,
                           duration=excluded.duration,size=excluded.size,mtime=excluded.mtime,
                           cover_url=excluded.cover_url,artist_cover_url=excluded.artist_cover_url,
                           updated_at=CURRENT_TIMESTAMP""",
                    values,
                )
            if paths:
                placeholders = ",".join("?" for _ in paths)
                removed = self._connection.execute(
                    f"DELETE FROM tracks WHERE path NOT IN ({placeholders})", paths
                ).rowcount
            else:
                removed = self._connection.execute("DELETE FROM tracks").rowcount
            rows = self._connection.execute(
                "SELECT id,path FROM tracks WHERE path IN ({})".format(
                    ",".join("?" for _ in paths)
                ), paths
            ).fetchall() if paths else []
            existing = {row["path"]: row["id"] for row in rows}
            # Local Artist.* files are authoritative for the current scan. Remove
            # only previous local mappings; externally resolved images stay cached.
            self._connection.execute("DELETE FROM artist_images WHERE source='local'")
            local_artist_images = self._connection.execute(
                """SELECT artist, MAX(artist_cover_url) AS url FROM tracks
                   WHERE artist_cover_url IS NOT NULL AND artist_cover_url<>''
                   GROUP BY artist"""
            ).fetchall()
            for image in local_artist_images:
                cover_id = str(image["url"]).rsplit("/", 1)[-1]
                if len(cover_id) == 64 and cover_id.isalnum():
                    self._connection.execute(
                        """INSERT INTO artist_images(artist,cover_id,status,source) VALUES (?,?,?,?)
                           ON CONFLICT(artist) DO UPDATE SET cover_id=excluded.cover_id,status=excluded.status,
                           source=excluded.source,updated_at=CURRENT_TIMESTAMP""",
                        (image["artist"], cover_id, "ready", "local"),
                    )
        return {"indexed": len(snapshot), "removed": removed, "track_ids": [existing[p] for p in paths]}

    def scan_cache(self) -> dict[str, dict[str, Any]]:
        """Return the immutable fields needed to skip unchanged audio files.

        The scanner still walks the whole tree, so removals remain visible to
        reconciliation.  Only expensive tag and embedded-artwork extraction is
        avoided for files whose size and modification time have not changed.
        """
        fields = "path,title,artist,album,album_artist,track_no,disc_no,year,genre,duration,size,mtime,cover_url,artist_cover_url"
        with self._lock:
            rows = self._connection.execute(f"SELECT {fields} FROM tracks").fetchall()
        return {str(row["path"]): dict(row) for row in rows}

    def get_track(self, track_id: int) -> dict[str, Any]:
        row = self._connection.execute(
            """SELECT t.*, p.rating, COALESCE(p.favorite,0) AS favorite
               FROM tracks t LEFT JOIN track_preferences p ON p.track_id=t.id WHERE t.id=?""",
            (track_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("track not found", {"track_id": track_id})
        return self._track(row)

    def list_tracks(self, search: Optional[str] = None, favorite: Optional[bool] = None,
                    limit: int = 50, offset: int = 0, *, page: Optional[int] = None,
                    page_size: Optional[int] = None) -> dict[str, Any]:
        if page is not None or page_size is not None:
            resolved_page = page if page is not None else 1
            resolved_page_size = page_size if page_size is not None else limit
            limit, offset = self._page(resolved_page, resolved_page_size)
        else:
            if not isinstance(limit, int) or not 1 <= limit <= 200:
                raise ValidationError("limit must be between 1 and 200", {"field": "limit"})
            if not isinstance(offset, int) or offset < 0:
                raise ValidationError("offset must be a non-negative integer", {"field": "offset"})
            resolved_page = offset // limit + 1
            resolved_page_size = limit
        clauses, params = [], []
        if search:
            clauses.append("(t.title LIKE ? OR t.artist LIKE ? OR t.album LIKE ?)")
            term = "%{}%".format(search)
            params.extend((term, term, term))
        if favorite is not None:
            clauses.append("COALESCE(p.favorite,0)=?")
            params.append(1 if favorite else 0)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        base = " FROM tracks t LEFT JOIN track_preferences p ON p.track_id=t.id" + where
        total = self._connection.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
        rows = self._connection.execute(
            "SELECT t.*,p.rating,COALESCE(p.favorite,0) AS favorite" + base
            + " ORDER BY t.artist COLLATE NOCASE,t.album COLLATE NOCASE,t.disc_no,t.track_no,t.title COLLATE NOCASE LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return {
            "items": [self._track(row) for row in rows],
            "page": resolved_page,
            "page_size": resolved_page_size,
            "limit": limit,
            "offset": offset,
            "total": total,
        }

    def _list_groups(self, column: str, page: int, page_size: int) -> dict[str, Any]:
        limit, offset = self._page(page, page_size)
        total = self._connection.execute(
            f"SELECT COUNT(DISTINCT {column}) FROM tracks WHERE {column}<>''"
        ).fetchone()[0]
        rows = self._connection.execute(
            f"""SELECT {column} AS name,COUNT(*) AS track_count,COALESCE(SUM(duration),0) AS duration
                FROM tracks WHERE {column}<>'' GROUP BY {column}
                ORDER BY {column} COLLATE NOCASE LIMIT ? OFFSET ?""", (limit, offset)
        ).fetchall()
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def list_albums(
        self, page: int = 1, page_size: int = 50, search: str = "", sort: str = "alphabet"
    ) -> dict[str, Any]:
        if sort not in {"alphabet", "recent"}:
            raise ValidationError("album sort must be alphabet or recent", {"field": "sort"})
        limit, offset = self._page(page, page_size)
        clause, params = self._group_search_clause("album", search)
        order = "album COLLATE NOCASE" if sort == "alphabet" else "MAX(id) DESC,album COLLATE NOCASE"
        total = self._connection.execute(
            f"SELECT COUNT(DISTINCT album) FROM tracks WHERE album<>''{clause}", params
        ).fetchone()[0]
        rows = self._connection.execute(
            """SELECT album AS name,
                       CASE WHEN COUNT(DISTINCT COALESCE(NULLIF(album_artist,''),artist)) = 1
                            THEN MAX(COALESCE(NULLIF(album_artist,''),artist))
                            ELSE 'Разные исполнители' END AS album_artist,
                       COUNT(*) AS track_count,
                       COALESCE(SUM(duration),0) AS duration,MAX(cover_url) AS cover_url
                FROM tracks WHERE album<>''""" + clause + """ GROUP BY album
                ORDER BY """ + order + """ LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total, "sort": sort}

    def list_recent_albums(self, limit: int = 7) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValidationError("limit must be between 1 and 50", {"field": "limit"})
        rows = self._connection.execute(
            """SELECT album AS name,
                       CASE WHEN COUNT(DISTINCT COALESCE(NULLIF(album_artist,''),artist)) = 1
                            THEN MAX(COALESCE(NULLIF(album_artist,''),artist))
                            ELSE 'Разные исполнители' END AS album_artist,
                       COUNT(*) AS track_count, COALESCE(SUM(duration),0) AS duration,
                       MAX(cover_url) AS cover_url
                FROM tracks WHERE album<>'' GROUP BY album
                ORDER BY MAX(id) DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_artists(self, page: int = 1, page_size: int = 50, search: str = "") -> dict[str, Any]:
        limit, offset = self._page(page, page_size)
        clause, params = self._group_search_clause("artist", search)
        row_clause, row_params = self._group_search_clause("t.artist", search)
        total = self._connection.execute(
            f"SELECT COUNT(DISTINCT artist) FROM tracks WHERE artist<>''{clause}", params
        ).fetchone()[0]
        rows = self._connection.execute(
                """SELECT t.artist AS name,COUNT(*) AS track_count,COALESCE(SUM(t.duration),0) AS duration,
                       image.cover_id AS artist_cover_id,image.status AS artist_image_status
                FROM tracks t LEFT JOIN artist_images image ON image.artist=t.artist
                WHERE t.artist<>''""" + row_clause + """ GROUP BY t.artist
                ORDER BY t.artist COLLATE NOCASE LIMIT ? OFFSET ?""", (*row_params, limit, offset)
        ).fetchall()
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    @staticmethod
    def _group_search_clause(column: str, search: str) -> tuple[str, tuple[str, ...]]:
        if not search.strip():
            return "", ()
        return f" AND {column} LIKE ?", (f"%{search.strip()}%",)

    def list_catalog_values(self, kind: str, search: str = "", favorite: Optional[bool] = None) -> list[str]:
        columns = {"albums": "t.album", "artists": "t.artist", "songs": "t.artist"}
        column = columns.get(kind)
        if column is None:
            raise ValidationError("unknown catalog kind", {"kind": kind})
        clauses = [f"{column}<>''"]
        params: list[Any] = []
        if search:
            clauses.append("(t.title LIKE ? OR t.artist LIKE ? OR t.album LIKE ?)")
            term = f"%{search}%"
            params.extend((term, term, term))
        if kind == "songs" and favorite is not None:
            clauses.append("COALESCE(p.favorite,0)=?")
            params.append(int(favorite))
        preferences = " LEFT JOIN track_preferences p ON p.track_id=t.id" if kind == "songs" else ""
        statement = f"SELECT DISTINCT {column} AS value FROM tracks t{preferences} WHERE " + " AND ".join(clauses)
        rows = self._connection.execute(statement + f" ORDER BY {column} COLLATE NOCASE", params).fetchall()
        return [str(row["value"]) for row in rows if str(row["value"]).strip()]

    def list_catalog_initials(self, kind: str, search: str = "", favorite: Optional[bool] = None) -> list[str]:
        return sorted({value.strip()[:1].upper() for value in self.list_catalog_values(kind, search, favorite)})

    def artist_album_cover_urls(self, artist: str) -> list[str]:
        rows = self._connection.execute(
            """SELECT cover_url FROM tracks WHERE artist=? COLLATE NOCASE AND cover_url<>''
               GROUP BY album,cover_url ORDER BY album COLLATE NOCASE LIMIT 4""", (artist,)
        ).fetchall()
        return [str(row["cover_url"]) for row in rows]

    def artist_image(self, artist: str) -> Optional[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT artist,cover_id,status,source FROM artist_images WHERE artist=? COLLATE NOCASE", (artist,)
        ).fetchone()
        return dict(row) if row else None

    def save_artist_image(self, artist: str, cover_id: Optional[str], status: str, source: str = "") -> None:
        if status not in {"ready", "missing"}:
            raise ValidationError("invalid artist image status", {"status": status})
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO artist_images(artist,cover_id,status,source) VALUES (?,?,?,?)
                   ON CONFLICT(artist) DO UPDATE SET cover_id=excluded.cover_id,status=excluded.status,
                   source=excluded.source,updated_at=CURRENT_TIMESTAMP""",
                (artist, cover_id, status, source),
            )

    def set_preference(self, track_id: int, rating: Optional[int] = None,
                       favorite: Optional[bool] = None) -> dict[str, Any]:
        if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int) or not 0 <= rating <= 5):
            raise ValidationError("rating must be an integer from 0 to 5", {"field": "rating"})
        if favorite is not None and not isinstance(favorite, bool):
            raise ValidationError("favorite must be a boolean", {"field": "favorite"})
        with self._lock, self._connection:
            if self._connection.execute("SELECT 1 FROM tracks WHERE id=?", (track_id,)).fetchone() is None:
                raise NotFoundError("track not found", {"track_id": track_id})
            current = self._connection.execute(
                "SELECT rating,favorite FROM track_preferences WHERE track_id=?", (track_id,)
            ).fetchone()
            next_rating = rating if rating is not None else (current["rating"] if current else None)
            next_favorite = favorite if favorite is not None else bool(current["favorite"] if current else 0)
            self._connection.execute(
                """INSERT INTO track_preferences(track_id,rating,favorite) VALUES (?,?,?)
                   ON CONFLICT(track_id) DO UPDATE SET rating=excluded.rating,favorite=excluded.favorite""",
                (track_id, next_rating, int(next_favorite)),
            )
        return self.get_track(track_id)

    @staticmethod
    def _radio_station(item: Mapping[str, Any]) -> dict[str, Any]:
        station_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        stream_url = str(item.get("stream_url", "")).strip()
        if not station_id or not name or not stream_url:
            raise ValidationError("radio station requires id, name and stream_url")
        def text(key: str, limit: int) -> str:
            return str(item.get(key, "") or "").strip()[:limit]
        def number(key: str) -> Optional[int]:
            value = item.get(key)
            return int(value) if isinstance(value, int) and not isinstance(value, bool) else None
        return {"id": station_id[:64], "name": name[:120], "genre": text("genre", 100), "now_playing": text("now_playing", 160), "listeners": number("listeners"), "bitrate": number("bitrate"), "stream_url": stream_url[:2048]}

    def save_radio_stations(self, stations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        saved = [self._radio_station(item) for item in stations]
        with self._lock, self._connection:
            for station in saved:
                self._connection.execute(
                    """INSERT INTO radio_stations(station_id,name,genre,now_playing,listeners,bitrate,stream_url)
                       VALUES (:id,:name,:genre,:now_playing,:listeners,:bitrate,:stream_url)
                       ON CONFLICT(station_id) DO UPDATE SET name=excluded.name,genre=excluded.genre,
                       now_playing=excluded.now_playing,listeners=excluded.listeners,bitrate=excluded.bitrate,
                       stream_url=excluded.stream_url,updated_at=CURRENT_TIMESTAMP""",
                    station,
                )
        return saved

    @staticmethod
    def _radio_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["favorite"] = bool(item["favorite"])
        item["blacklisted"] = bool(item["blacklisted"])
        return item

    def list_radio_stations(self, favorite: Optional[bool] = None, limit: int = 100,
                            include_blacklisted: bool = False, genre: str = "", search: str = "") -> list[dict[str, Any]]:
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValidationError("limit must be between 1 and 200", {"field": "limit"})
        clauses, params = [], []
        if favorite is not None:
            clauses.append("favorite=?")
            params.append(int(favorite))
        if not include_blacklisted:
            clauses.append("blacklisted=0")
        if genre and genre.casefold() != "all":
            clauses.append("genre LIKE ?")
            params.append(f"%{genre}%")
        if search:
            clauses.append("(name LIKE ? OR genre LIKE ? OR now_playing LIKE ?)")
            term = f"%{search}%"
            params.extend((term, term, term))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self._connection.execute(
            "SELECT station_id AS id,name,genre,now_playing,listeners,bitrate,stream_url,favorite,blacklisted FROM radio_stations"
            + where + " ORDER BY favorite DESC,updated_at DESC LIMIT ?", (*params, limit)
        ).fetchall()
        return [self._radio_row(row) for row in rows]

    @staticmethod
    def _radio_snapshot_key(genre: str, search: str) -> str:
        return f"{genre.strip().casefold()}|{search.strip().casefold()}"

    def save_radio_snapshot(self, result: Mapping[str, Any]) -> None:
        genre = str(result.get("genre", "All") or "All").strip()[:48]
        search = str(result.get("search", "") or "").strip()[:100]
        payload = {
            "configured": bool(result.get("configured", True)), "source": str(result.get("source", "local")),
            "genres": list(result.get("genres", [])), "genre": genre, "search": search,
            "stations": [self._radio_station(station) for station in result.get("stations", [])],
        }
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO radio_catalog_snapshots(cache_key,genre,search,payload)
                   VALUES (?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP""",
                (self._radio_snapshot_key(genre, search), genre, search, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            )

    def get_radio_snapshot(self, genre: str, search: str, limit: int) -> Optional[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT payload FROM radio_catalog_snapshots WHERE cache_key=?", (self._radio_snapshot_key(genre, search),)
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"])
            stations = [self._radio_station(item) for item in payload.get("stations", [])]
        except (TypeError, ValueError, ValidationError):
            return None
        current = {item["id"]: item for item in self.list_radio_stations(limit=200, include_blacklisted=True)}
        visible = []
        for station in stations:
            saved = current.get(station["id"])
            if saved is None or saved["blacklisted"]:
                continue
            visible.append({**station, "favorite": saved["favorite"]})
            if len(visible) >= limit:
                break
        return {**payload, "stations": visible}

    def get_radio_station(self, station_id: str, include_blacklisted: bool = False) -> Optional[dict[str, Any]]:
        visible = "" if include_blacklisted else " AND blacklisted=0"
        row = self._connection.execute(
            "SELECT station_id AS id,name,genre,now_playing,listeners,bitrate,stream_url,favorite,blacklisted FROM radio_stations WHERE station_id=?" + visible,
            (station_id,),
        ).fetchone()
        return self._radio_row(row) if row else None

    def set_radio_favorite(self, station: Mapping[str, Any], favorite: bool) -> dict[str, Any]:
        if not isinstance(favorite, bool):
            raise ValidationError("favorite must be a boolean", {"field": "favorite"})
        saved = self.save_radio_stations([station])[0]
        with self._lock, self._connection:
            self._connection.execute("UPDATE radio_stations SET favorite=?,updated_at=CURRENT_TIMESTAMP WHERE station_id=?", (int(favorite), saved["id"]))
        result = self.get_radio_station(saved["id"])
        assert result is not None
        return result

    def mark_radio_playing(self, station_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE radio_stations SET last_played_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE station_id=? AND blacklisted=0",
                (station_id,),
            )

    def blacklist_recent_radio_station(self, grace_seconds: int = 90) -> Optional[dict[str, Any]]:
        if not isinstance(grace_seconds, int) or not 1 <= grace_seconds <= 600:
            raise ValidationError("radio blacklist grace must be between 1 and 600 seconds")
        with self._lock, self._connection:
            row = self._connection.execute(
                """SELECT station_id AS id,name,genre,now_playing,listeners,bitrate,stream_url,favorite,blacklisted
                   FROM radio_stations WHERE blacklisted=0 AND last_played_at IS NOT NULL
                   AND last_played_at >= datetime('now', ?) ORDER BY last_played_at DESC LIMIT 1""",
                (f"-{grace_seconds} seconds",),
            ).fetchone()
            if row is None:
                return None
            self._connection.execute(
                "UPDATE radio_stations SET blacklisted=1,blacklisted_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE station_id=?",
                (row["id"],),
            )
        item = self._radio_row(row)
        item["blacklisted"] = True
        return item

    def create_playlist(self, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValidationError("playlist name is required", {"field": "name"})
        try:
            with self._lock, self._connection:
                cursor = self._connection.execute("INSERT INTO playlists(name) VALUES (?)", (name,))
        except sqlite3.IntegrityError as error:
            raise ConflictError("playlist name already exists", {"field": "name"}) from error
        return self.get_playlist(cursor.lastrowid)

    def list_playlists(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """SELECT p.id,p.name,p.created_at,p.updated_at,COUNT(pt.track_id) AS track_count
               FROM playlists p LEFT JOIN playlist_tracks pt ON pt.playlist_id=p.id
               GROUP BY p.id ORDER BY p.name COLLATE NOCASE"""
        ).fetchall()
        return [dict(row) for row in rows]

    def get_playlist(self, playlist_id: int) -> dict[str, Any]:
        row = self._connection.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        if row is None:
            raise NotFoundError("playlist not found", {"playlist_id": playlist_id})
        tracks = self._connection.execute(
            """SELECT t.*,p.rating,COALESCE(p.favorite,0) AS favorite
               FROM playlist_tracks pt JOIN tracks t ON t.id=pt.track_id
               LEFT JOIN track_preferences p ON p.track_id=t.id
               WHERE pt.playlist_id=? ORDER BY pt.position""", (playlist_id,)
        ).fetchall()
        result = dict(row)
        result["tracks"] = [self._track(track) for track in tracks]
        return result

    def rename_playlist(self, playlist_id: int, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValidationError("playlist name is required", {"field": "name"})
        try:
            with self._lock, self._connection:
                cursor = self._connection.execute(
                    "UPDATE playlists SET name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (name, playlist_id)
                )
                if cursor.rowcount == 0:
                    raise NotFoundError("playlist not found", {"playlist_id": playlist_id})
        except sqlite3.IntegrityError as error:
            raise ConflictError("playlist name already exists", {"field": "name"}) from error
        return self.get_playlist(playlist_id)

    def update_playlist(self, playlist_id: int, name: str) -> dict[str, Any]:
        return self.rename_playlist(playlist_id, name)

    def delete_playlist(self, playlist_id: int) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
            if cursor.rowcount == 0:
                raise NotFoundError("playlist not found", {"playlist_id": playlist_id})

    def add_playlist_track(self, playlist_id: int, track_id: int) -> dict[str, Any]:
        try:
            with self._lock, self._connection:
                if self._connection.execute("SELECT 1 FROM playlists WHERE id=?", (playlist_id,)).fetchone() is None:
                    raise NotFoundError("playlist not found", {"playlist_id": playlist_id})
                if self._connection.execute("SELECT 1 FROM tracks WHERE id=?", (track_id,)).fetchone() is None:
                    raise NotFoundError("track not found", {"track_id": track_id})
                position = self._connection.execute(
                    "SELECT COALESCE(MAX(position),-1)+1 FROM playlist_tracks WHERE playlist_id=?", (playlist_id,)
                ).fetchone()[0]
                self._connection.execute(
                    "INSERT INTO playlist_tracks(playlist_id,track_id,position) VALUES (?,?,?)",
                    (playlist_id, track_id, position),
                )
                self._connection.execute("UPDATE playlists SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (playlist_id,))
        except sqlite3.IntegrityError as error:
            raise ConflictError("track is already in playlist", {"track_id": track_id}) from error
        return self.get_playlist(playlist_id)

    def remove_playlist_track(self, playlist_id: int, track_id: int) -> dict[str, Any]:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM playlist_tracks WHERE playlist_id=? AND track_id=?", (playlist_id, track_id)
            )
            if cursor.rowcount == 0:
                raise NotFoundError("playlist track not found", {"playlist_id": playlist_id, "track_id": track_id})
            rows = self._connection.execute(
                "SELECT track_id FROM playlist_tracks WHERE playlist_id=? ORDER BY position", (playlist_id,)
            ).fetchall()
            for position, row in enumerate(rows):
                self._connection.execute(
                    "UPDATE playlist_tracks SET position=? WHERE playlist_id=? AND track_id=?",
                    (position, playlist_id, row["track_id"]),
                )
        return self.get_playlist(playlist_id)

    def reorder_playlist(self, playlist_id: int, track_ids: Iterable[int]) -> dict[str, Any]:
        requested = list(track_ids)
        with self._lock, self._connection:
            current = [row["track_id"] for row in self._connection.execute(
                "SELECT track_id FROM playlist_tracks WHERE playlist_id=? ORDER BY position", (playlist_id,)
            ).fetchall()]
            if self._connection.execute("SELECT 1 FROM playlists WHERE id=?", (playlist_id,)).fetchone() is None:
                raise NotFoundError("playlist not found", {"playlist_id": playlist_id})
            if len(requested) != len(set(requested)) or set(requested) != set(current):
                raise ValidationError("track_ids must contain every playlist track exactly once", {"field": "track_ids"})
            self._connection.execute(
                "UPDATE playlist_tracks SET position=position+? WHERE playlist_id=?", (len(current) + 1, playlist_id)
            )
            for position, track_id in enumerate(requested):
                self._connection.execute(
                    "UPDATE playlist_tracks SET position=? WHERE playlist_id=? AND track_id=?",
                    (position, playlist_id, track_id),
                )
        return self.get_playlist(playlist_id)

    def set_playlist_tracks(self, playlist_id: int, track_ids: Iterable[int]) -> dict[str, Any]:
        requested = list(track_ids)
        if len(requested) != len(set(requested)):
            raise ValidationError("track_ids must not contain duplicates", {"field": "track_ids"})
        with self._lock, self._connection:
            if self._connection.execute("SELECT 1 FROM playlists WHERE id=?", (playlist_id,)).fetchone() is None:
                raise NotFoundError("playlist not found", {"playlist_id": playlist_id})
            if requested:
                placeholders = ",".join("?" for _ in requested)
                found = {
                    row["id"] for row in self._connection.execute(
                        f"SELECT id FROM tracks WHERE id IN ({placeholders})", requested
                    ).fetchall()
                }
                missing = [track_id for track_id in requested if track_id not in found]
                if missing:
                    raise ValidationError("track_ids contain unknown tracks", {"track_ids": missing})
            self._connection.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (playlist_id,))
            self._connection.executemany(
                "INSERT INTO playlist_tracks(playlist_id,track_id,position) VALUES (?,?,?)",
                [(playlist_id, track_id, position) for position, track_id in enumerate(requested)],
            )
            self._connection.execute(
                "UPDATE playlists SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (playlist_id,)
            )
        return self.get_playlist(playlist_id)

    def get_settings(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self._connection.execute(
            "SELECT key,value FROM settings ORDER BY key"
        ).fetchall()}

    def update_settings(self, mapping: Mapping[str, Any]) -> dict[str, str]:
        invalid = [key for key in mapping if key not in ALLOWED_SETTINGS or any(marker in key.lower() for marker in SECRET_MARKERS)]
        if invalid:
            raise ValidationError("unknown or secret setting keys are not allowed", {"keys": sorted(invalid)})
        if any(not isinstance(value, str) for value in mapping.values()):
            raise ValidationError("setting values must be strings", {"field": "settings"})
        if "catalog_page_size" in mapping and mapping["catalog_page_size"] not in {"7", "14", "21", "28", "35", "42", "49"}:
            raise ValidationError("catalog_page_size must be a multiple of 7 between 7 and 49", {"field": "catalog_page_size"})
        if "album_sort" in mapping and mapping["album_sort"] not in {"alphabet", "recent"}:
            raise ValidationError("album_sort must be alphabet or recent", {"field": "album_sort"})
        with self._lock, self._connection:
            for key, value in mapping.items():
                self._connection.execute(
                    """INSERT INTO settings(key,value) VALUES (?,?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
                    (key, value),
                )
        return self.get_settings()
