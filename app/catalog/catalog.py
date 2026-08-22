from __future__ import annotations

import sqlite3
import threading
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
        "mpd_host", "mpd_port", "mpd_uri_prefix",
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
                INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
                """
            )

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
                    int(item.get("size") or 0), float(item.get("mtime") or 0), item.get("cover_url"),
                )
                self._connection.execute(
                    """INSERT INTO tracks(
                           path,title,artist,album,album_artist,track_no,disc_no,year,genre,
                           duration,size,mtime,cover_url
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(path) DO UPDATE SET
                           title=excluded.title,artist=excluded.artist,album=excluded.album,
                           album_artist=excluded.album_artist,track_no=excluded.track_no,
                           disc_no=excluded.disc_no,year=excluded.year,genre=excluded.genre,
                           duration=excluded.duration,size=excluded.size,mtime=excluded.mtime,
                           cover_url=excluded.cover_url,updated_at=CURRENT_TIMESTAMP""",
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
        return {"indexed": len(snapshot), "removed": removed, "track_ids": [existing[p] for p in paths]}

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

    def list_albums(self, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        limit, offset = self._page(page, page_size)
        total = self._connection.execute(
            "SELECT COUNT(DISTINCT album) FROM tracks WHERE album<>''"
        ).fetchone()[0]
        rows = self._connection.execute(
            """SELECT album AS name,
                       CASE WHEN COUNT(DISTINCT COALESCE(NULLIF(album_artist,''),artist)) = 1
                            THEN MAX(COALESCE(NULLIF(album_artist,''),artist))
                            ELSE 'Разные исполнители' END AS album_artist,
                       COUNT(*) AS track_count,
                       COALESCE(SUM(duration),0) AS duration,MAX(cover_url) AS cover_url
                FROM tracks WHERE album<>'' GROUP BY album
                ORDER BY album COLLATE NOCASE LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def list_artists(self, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        limit, offset = self._page(page, page_size)
        total = self._connection.execute(
            "SELECT COUNT(DISTINCT artist) FROM tracks WHERE artist<>''"
        ).fetchone()[0]
        rows = self._connection.execute(
            """SELECT t.artist AS name,COUNT(*) AS track_count,COALESCE(SUM(t.duration),0) AS duration,
                       image.cover_id AS artist_cover_id,image.status AS artist_image_status,
                       (SELECT GROUP_CONCAT(cover_url, char(31)) FROM (
                            SELECT cover_url FROM tracks album_tracks
                            WHERE album_tracks.artist=t.artist AND album_tracks.cover_url<>''
                            GROUP BY album_tracks.album, album_tracks.cover_url
                            ORDER BY album_tracks.album COLLATE NOCASE LIMIT 4
                        )) AS album_cover_urls
                FROM tracks t LEFT JOIN artist_images image ON image.artist=t.artist
                WHERE t.artist<>'' GROUP BY t.artist
                ORDER BY t.artist COLLATE NOCASE LIMIT ? OFFSET ?""", (limit, offset)
        ).fetchall()
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": total}

    def list_catalog_initials(self, kind: str, search: str = "", favorite: Optional[bool] = None) -> list[str]:
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
        rows = self._connection.execute(
            f"SELECT DISTINCT {column} AS value FROM tracks t{preferences} WHERE " + " AND ".join(clauses), params
        ).fetchall()
        return sorted({str(row["value"]).strip()[:1].upper() for row in rows if str(row["value"]).strip()})

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
        with self._lock, self._connection:
            for key, value in mapping.items():
                self._connection.execute(
                    """INSERT INTO settings(key,value) VALUES (?,?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
                    (key, value),
                )
        return self.get_settings()
