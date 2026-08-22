from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple


SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff"}
IMAGE_NAMES = ("cover", "folder", "front")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_COVER_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class CoverAsset:
    data: bytes
    mime_type: str
    etag: str


@dataclass(frozen=True)
class ScanSnapshot:
    tracks: Tuple[dict, ...]
    counters: dict
    covers: Mapping[str, CoverAsset]


class Scanner:
    def __init__(self, metadata_reader: Optional[Callable[[Path], Mapping]] = None):
        self._metadata_reader = metadata_reader or _read_mutagen

    def scan(self, root: Path, progress: Optional[Callable[[dict], None]] = None) -> ScanSnapshot:
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"music root is unavailable: {root}")
        tracks = []
        covers: Dict[str, CoverAsset] = {}
        counters = {"discovered": 0, "indexed": 0, "unreadable": 0, "unsupported": 0}
        if progress:
            progress(dict(counters))
        for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                counters["unsupported"] += 1
                if progress:
                    progress(dict(counters))
                continue
            counters["discovered"] += 1
            try:
                metadata = dict(self._metadata_reader(path))
                stat = path.stat()
            except Exception:
                counters["unreadable"] += 1
                if progress:
                    progress(dict(counters))
                continue
            embedded = metadata.pop("embedded_cover", None)
            cover = _make_cover(embedded) if embedded else _directory_cover(path.parent)
            row = {
                "path": path.relative_to(root).as_posix(),
                "title": _text(metadata.get("title"), "Без названия"),
                "artist": _text(metadata.get("artist"), "Неизвестный исполнитель"),
                "album": _text(metadata.get("album"), "Неизвестный альбом"),
                "album_artist": _text(metadata.get("album_artist"), ""),
                "track_no": _number(metadata.get("track_no")),
                "disc_no": _number(metadata.get("disc_no")),
                "year": _number(metadata.get("year")),
                "genre": _text(metadata.get("genre"), ""),
                "duration": metadata.get("duration"),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
            if cover:
                covers[cover.etag] = cover
                row["cover_url"] = f"/api/covers/{cover.etag}"
            else:
                row["cover_url"] = "/api/covers/placeholder"
            tracks.append(row)
            counters["indexed"] += 1
            if progress:
                progress(dict(counters))
        return ScanSnapshot(tuple(tracks), counters, covers)


def scan(root: Path) -> ScanSnapshot:
    return Scanner().scan(root)


def _text(value, fallback: str) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    value = str(value).strip() if value is not None else ""
    return value or fallback


def _number(value):
    text = _text(value, "")
    if not text:
        return None
    try:
        return int(text.split("/", 1)[0].split("-", 1)[0])
    except ValueError:
        return None


def _make_cover(raw) -> Optional[CoverAsset]:
    if isinstance(raw, tuple) and len(raw) == 2:
        data, mime_type = raw
    elif isinstance(raw, bytes):
        data, mime_type = raw, "application/octet-stream"
    else:
        return None
    if not data or len(data) > MAX_COVER_BYTES:
        return None
    etag = hashlib.sha256(data).hexdigest()
    return CoverAsset(bytes(data), str(mime_type), etag)


def _directory_cover(directory: Path) -> Optional[CoverAsset]:
    entries = {entry.name.lower(): entry for entry in directory.iterdir() if entry.is_file() and not entry.is_symlink()}
    for stem in IMAGE_NAMES:
        for extension in IMAGE_EXTENSIONS:
            path = entries.get(stem + extension)
            if path and path.stat().st_size <= MAX_COVER_BYTES:
                return _make_cover((path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"))
    return None


def _first(tags, *names):
    for name in names:
        value = tags.get(name) if tags else None
        if value is not None:
            return value
    return None


def _read_mutagen(path: Path) -> Mapping:
    try:
        import mutagen
    except ImportError as error:
        raise RuntimeError("Mutagen is required to scan audio metadata") from error
    audio = mutagen.File(path)
    if audio is None:
        raise ValueError("unsupported or unreadable audio file")
    tags = audio.tags or {}
    result = {
        "title": _first(tags, "title", "TIT2", "\xa9nam"),
        "artist": _first(tags, "artist", "TPE1", "\xa9ART"),
        "album": _first(tags, "album", "TALB", "\xa9alb"),
        "album_artist": _first(tags, "albumartist", "album artist", "TPE2", "aART"),
        "track_no": _first(tags, "tracknumber", "TRCK", "trkn"),
        "disc_no": _first(tags, "discnumber", "TPOS", "disk"),
        "year": _first(tags, "date", "year", "TDRC", "\xa9day"),
        "genre": _first(tags, "genre", "TCON", "\xa9gen"),
        "duration": float(audio.info.length) if getattr(audio, "info", None) else None,
    }
    pictures = getattr(audio, "pictures", None)
    if pictures:
        result["embedded_cover"] = (pictures[0].data, pictures[0].mime)
    else:
        for key, value in tags.items():
            if str(key).startswith("APIC") and hasattr(value, "data"):
                result["embedded_cover"] = (value.data, getattr(value, "mime", "image/jpeg"))
                break
            if str(key) == "covr" and value:
                cover = value[0]
                result["embedded_cover"] = (bytes(cover), "image/png" if getattr(cover, "imageformat", 0) == 14 else "image/jpeg")
                break
    return result
