from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.player import get_mpd_client
from app.mpd import MpdCommandError, MpdConfigurationError, MpdConnectionError
from app.radio import HybridRadioDirectory, RadioDirectoryError


router = APIRouter()


class RadioPlayInput(BaseModel):
    station_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")


def get_radio_directory(request: Request) -> HybridRadioDirectory:
    return request.app.state.radio_directory


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


@router.get("/radio", response_model=None)
def radio_catalog(
    genre: str = "Pop", search: str = "", limit: int = 18,
    directory: HybridRadioDirectory = Depends(get_radio_directory),
):
    try:
        return directory.list_stations(genre=genre, search=search, limit=limit)
    except RadioDirectoryError:
        return _error(502, "radio_directory_unavailable", "Каталог радио временно недоступен")


@router.post("/radio/play", response_model=None)
def play_radio(
    body: RadioPlayInput,
    directory: HybridRadioDirectory = Depends(get_radio_directory),
    client=Depends(get_mpd_client),
):
    station = directory.station(body.station_id)
    if station is None:
        return _error(404, "radio_station_not_found", "Станция не найдена: обновите каталог и попробуйте снова")
    try:
        return client.play_stream(station["stream_url"])
    except MpdConfigurationError as error:
        return _error(422, "invalid_mpd_settings", str(error))
    except MpdCommandError as error:
        return _error(422, "invalid_radio_station", str(error))
    except MpdConnectionError:
        return _error(503, "mpd_offline", "MPD is unavailable")
