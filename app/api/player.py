from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.catalog import Catalog
from app.dependencies import get_catalog
from app.mpd import (
    MpdClient,
    MpdCommandError,
    MpdConfigurationError,
    MpdConnectionError,
    MpdError,
)


router = APIRouter()


class PlayerCommandInput(BaseModel):
    command: str
    params: Dict[str, Any] = Field(default_factory=dict)


class PlayerPlayInput(BaseModel):
    track_ids: List[int] = Field(min_length=1)
    shuffle: bool = False


class _InvalidMpdClient:
    def __init__(self, error: MpdConfigurationError):
        self.error = error

    def status(self):
        raise self.error

    def command(self, name: str, **params: Any):
        raise self.error

    def play_uris(self, paths, shuffle: bool = False):
        raise self.error

    def play_stream(self, stream_url: str):
        raise self.error


def get_mpd_client(catalog: Catalog = Depends(get_catalog)):
    settings = catalog.get_settings()
    try:
        port = int(settings.get("mpd_port", "6600"))
    except (TypeError, ValueError):
        return _InvalidMpdClient(
            MpdConfigurationError("mpd_port must be an integer between 1 and 65535")
        )
    try:
        return MpdClient(
            settings.get("mpd_host", "host.docker.internal"),
            port,
            os.environ.get("MPD_PASSWORD"),
            uri_prefix=settings.get("mpd_uri_prefix", ""),
        )
    except MpdConfigurationError as error:
        return _InvalidMpdClient(error)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _offline() -> dict[str, Any]:
    return {"online": False, "state": "offline", "song": None, "message": "MPD is unavailable"}


def _offline_response() -> JSONResponse:
    return JSONResponse(status_code=503, content=_offline())


def _settings_error(error: MpdConfigurationError) -> JSONResponse:
    return _error(422, "invalid_mpd_settings", str(error))


@router.get("/player/status")
def player_status(catalog: Catalog = Depends(get_catalog), client: MpdClient = Depends(get_mpd_client)) -> dict[str, Any]:
    try:
        return client.status()
    except MpdConfigurationError as error:
        return _settings_error(error)
    except MpdError:
        catalog.blacklist_recent_radio_station()
        return _offline()


@router.post("/settings/test-mpd")
def test_mpd(client: MpdClient = Depends(get_mpd_client)) -> dict[str, Any]:
    try:
        return client.status()
    except MpdConfigurationError as error:
        return _settings_error(error)
    except MpdError:
        return _offline()


@router.post("/player/command")
def player_command(body: PlayerCommandInput, client: MpdClient = Depends(get_mpd_client)):
    if body.command not in {"play", "pause", "previous", "next", "seek", "volume"}:
        return _error(422, "invalid_player_command", "command is not allowed")
    try:
        return client.command(body.command, **body.params)
    except MpdConfigurationError as error:
        return _settings_error(error)
    except MpdCommandError as error:
        return _error(422, "invalid_player_command", str(error))
    except MpdConnectionError:
        return _offline_response()


@router.post("/player/play")
def player_play(
    body: PlayerPlayInput,
    catalog: Catalog = Depends(get_catalog),
    client: MpdClient = Depends(get_mpd_client),
):
    try:
        paths = [catalog.get_track(track_id)["path"] for track_id in body.track_ids]
        return client.play_uris(paths, shuffle=body.shuffle)
    except MpdConfigurationError as error:
        return _settings_error(error)
    except MpdCommandError as error:
        return _error(422, "invalid_player_request", str(error))
    except MpdConnectionError:
        return _offline_response()
