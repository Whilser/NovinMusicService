from __future__ import annotations

from typing import Any, Optional
import threading

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.player import get_mpd_client
from app.catalog import Catalog
from app.dependencies import get_catalog
from app.mpd import MpdCommandError, MpdConfigurationError, MpdConnectionError
from app.radio import HybridRadioDirectory, RadioDirectoryError


router = APIRouter()


class RadioPlayInput(BaseModel):
    station_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")


class RadioStationInput(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")
    name: str = Field(min_length=1, max_length=120)
    genre: str = Field(default="", max_length=100)
    now_playing: str = Field(default="", max_length=160)
    listeners: Optional[int] = Field(default=None, ge=0)
    bitrate: Optional[int] = Field(default=None, ge=0)
    stream_url: str = Field(min_length=1, max_length=2048)


class RadioFavoriteInput(BaseModel):
    station: RadioStationInput
    favorite: bool


def get_radio_directory(request: Request) -> HybridRadioDirectory:
    return request.app.state.radio_directory


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _refresh_catalog(directory: HybridRadioDirectory, catalog: Catalog, genre: str, search: str, key: str, request: Request) -> None:
    try:
        result = directory.list_stations(genre=genre, search=search, limit=40, refresh=True)
        result["search"] = search
        catalog.save_radio_stations(result["stations"])
        catalog.save_radio_snapshot(result)
    except RadioDirectoryError:
        pass
    finally:
        with request.app.state.radio_refresh_lock:
            request.app.state.radio_refreshing.discard(key)


def _refresh_in_background(request: Request, directory: HybridRadioDirectory, catalog: Catalog, genre: str, search: str) -> bool:
    if not hasattr(request.app.state, "radio_refresh_lock"):
        request.app.state.radio_refresh_lock = threading.Lock()
        request.app.state.radio_refreshing = set()
    key = f"{genre.casefold()}|{search.casefold()}"
    with request.app.state.radio_refresh_lock:
        if key in request.app.state.radio_refreshing:
            return True
        request.app.state.radio_refreshing.add(key)
    threading.Thread(target=_refresh_catalog, args=(directory, catalog, genre, search, key, request), daemon=True).start()
    return True


@router.get("/radio", response_model=None)
def radio_catalog(
    request: Request,
    genre: str = "All", search: str = "", limit: int = 18, refresh: bool = False,
    directory: HybridRadioDirectory = Depends(get_radio_directory),
    catalog: Catalog = Depends(get_catalog),
):
    requested_limit = max(1, min(int(limit), 40))
    normalized_genre, normalized_search = genre.strip() or "All", search.strip()
    snapshot = catalog.get_radio_snapshot(normalized_genre, normalized_search, requested_limit)
    if snapshot is not None:
        snapshot["refreshing"] = _refresh_in_background(request, directory, catalog, normalized_genre, normalized_search)
        return snapshot
    cached = catalog.list_radio_stations(limit=requested_limit, genre=normalized_genre, search=normalized_search)
    if not cached and normalized_genre.casefold() != "all":
        cached = catalog.list_radio_stations(limit=requested_limit, search=normalized_search)
    if cached:
        return {"configured": True, "source": "local", "genres": ["All", "Pop", "Rock", "Dance", "Hip Hop", "Jazz", "Classical", "Electronic", "Chillout", "Russian"], "genre": normalized_genre, "search": normalized_search, "stations": cached, "refreshing": _refresh_in_background(request, directory, catalog, normalized_genre, normalized_search)}
    try:
        result = directory.list_stations(genre=normalized_genre, search=normalized_search, limit=40, refresh=refresh)
        result["search"] = normalized_search
        catalog.save_radio_stations(result["stations"])
        catalog.save_radio_snapshot(result)
        result["stations"] = result["stations"][:requested_limit]
        result["refreshing"] = False
        return result
    except RadioDirectoryError:
        return _error(502, "radio_directory_unavailable", "Каталог радио временно недоступен")


@router.get("/radio/favorites")
def radio_favorites(catalog: Catalog = Depends(get_catalog)) -> list[dict]:
    return catalog.list_radio_stations(favorite=True)


@router.put("/radio/stations/{station_id}/favorite")
def set_radio_favorite(station_id: str, body: RadioFavoriteInput, catalog: Catalog = Depends(get_catalog)) -> dict:
    if station_id != body.station.id:
        return _error(422, "invalid_radio_station", "Идентификатор станции не совпадает")
    return catalog.set_radio_favorite(body.station.model_dump(), body.favorite)


@router.post("/radio/play", response_model=None)
def play_radio(
    body: RadioPlayInput,
    directory: HybridRadioDirectory = Depends(get_radio_directory),
    catalog: Catalog = Depends(get_catalog),
    client=Depends(get_mpd_client),
):
    stored = catalog.get_radio_station(body.station_id, include_blacklisted=True)
    if stored is not None and stored["blacklisted"]:
        return _error(410, "radio_station_blacklisted", "Станция исключена из-за проблем с воспроизведением")
    station = stored or directory.station(body.station_id)
    if station is None:
        return _error(404, "radio_station_not_found", "Станция не найдена: обновите каталог и попробуйте снова")
    try:
        result = client.play_stream(station["stream_url"])
        catalog.mark_radio_playing(body.station_id)
        return result
    except MpdConfigurationError as error:
        return _error(422, "invalid_mpd_settings", str(error))
    except MpdCommandError as error:
        return _error(422, "invalid_radio_station", str(error))
    except MpdConnectionError:
        return _error(503, "mpd_offline", "MPD is unavailable")
