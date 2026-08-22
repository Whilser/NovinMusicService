from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from app.catalog import Catalog
from app.dependencies import get_catalog


router = APIRouter()


class PlaylistInput(BaseModel):
    name: str


class PlaylistTrackInput(BaseModel):
    track_id: int


class PlaylistOrderInput(BaseModel):
    track_ids: List[int]


class PreferenceInput(BaseModel):
    rating: Optional[int] = Field(default=None, ge=0, le=5)
    favorite: Optional[bool] = None


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/tracks")
def tracks(
    search: str = "",
    favorite: Optional[bool] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    page: Optional[int] = Query(default=None, ge=1),
    page_size: Optional[int] = Query(default=None, ge=1, le=200),
    catalog: Catalog = Depends(get_catalog),
) -> dict:
    return catalog.list_tracks(
        search=search, favorite=favorite, limit=limit, offset=offset,
        page=page, page_size=page_size,
    )


@router.get("/albums")
def albums(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
           catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.list_albums(page=page, page_size=page_size)


@router.get("/artists")
def artists(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
            catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.list_artists(page=page, page_size=page_size)


@router.get("/playlists")
def playlists(catalog: Catalog = Depends(get_catalog)) -> list:
    return catalog.list_playlists()


@router.post("/playlists", status_code=status.HTTP_201_CREATED)
def create_playlist(body: PlaylistInput, catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.create_playlist(body.name)


@router.get("/playlists/{playlist_id}")
def playlist(playlist_id: int, catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.get_playlist(playlist_id)


@router.patch("/playlists/{playlist_id}")
def rename_playlist(playlist_id: int, body: PlaylistInput, catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.update_playlist(playlist_id, body.name)


@router.delete("/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_playlist(playlist_id: int, catalog: Catalog = Depends(get_catalog)) -> Response:
    catalog.delete_playlist(playlist_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/playlists/{playlist_id}/tracks", status_code=status.HTTP_201_CREATED)
def add_playlist_track(playlist_id: int, body: PlaylistTrackInput,
                       catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.add_playlist_track(playlist_id, body.track_id)


@router.delete("/playlists/{playlist_id}/tracks/{track_id}")
def remove_playlist_track(playlist_id: int, track_id: int,
                          catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.remove_playlist_track(playlist_id, track_id)


@router.put("/playlists/{playlist_id}/tracks")
def reorder_playlist(playlist_id: int, body: PlaylistOrderInput,
                     catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.set_playlist_tracks(playlist_id, body.track_ids)


@router.put("/tracks/{track_id}/preference")
def preference(track_id: int, body: PreferenceInput, catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.set_preference(track_id, rating=body.rating, favorite=body.favorite)


@router.get("/settings")
def settings(catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.get_settings()


@router.patch("/settings")
def update_settings(body: Dict[str, str], catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.update_settings(body)
