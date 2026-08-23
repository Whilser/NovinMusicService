from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.artist_images import ArtistCollageResolver, ArtistImageResolver
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
def albums(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200), search: str = "",
           catalog: Catalog = Depends(get_catalog)) -> dict:
    return catalog.list_albums(page=page, page_size=page_size, search=search)


@router.get("/albums/recent")
def recent_albums(limit: int = Query(default=7, ge=1, le=50), catalog: Catalog = Depends(get_catalog)) -> list:
    return catalog.list_recent_albums(limit=limit)


@router.get("/artists")
def artists(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200), search: str = "",
           catalog: Catalog = Depends(get_catalog)) -> dict:
    result = catalog.list_artists(page=page, page_size=page_size, search=search)
    for item in result["items"]:
        cover_id = item.pop("artist_cover_id", None)
        image_status = item.get("artist_image_status")
        if cover_id and image_status == "ready":
            item["cover_url"] = f"/api/covers/{cover_id}"
    return result


@router.get("/catalog/initials")
def catalog_initials(
    kind: str = Query(pattern="^(albums|artists|songs)$"), search: str = "", favorite: Optional[bool] = None,
    page_size: int = Query(default=24, ge=1, le=200),
    catalog: Catalog = Depends(get_catalog),
) -> dict:
    values = catalog.list_catalog_values(kind, search=search, favorite=favorite)
    pages: dict[str, int] = {}
    for index, value in enumerate(values):
        letter = value.strip()[:1].upper()
        pages.setdefault(letter, index // page_size + 1)
    return {"items": sorted(pages), "pages": pages}


def get_artist_image_resolver(request: Request, catalog: Catalog = Depends(get_catalog)) -> ArtistImageResolver:
    resolver = getattr(request.app.state, "artist_image_resolver", None)
    if resolver is None or resolver.catalog is not catalog:
        resolver = ArtistImageResolver(catalog, request.app.state.cover_dir)
        request.app.state.artist_image_resolver = resolver
    return resolver


@router.get("/artists/image")
def artist_image(
    name: str = Query(min_length=1, max_length=160),
    resolver: ArtistImageResolver = Depends(get_artist_image_resolver),
) -> Response:
    image = resolver.resolve(name)
    if image is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "public, max-age=86400"})
    payload, mime_type, cover_id = image
    return Response(
        content=payload, media_type=mime_type,
        headers={"ETag": f'"{cover_id}"', "Cache-Control": "public, max-age=2592000"},
    )


def get_artist_collage_resolver(request: Request, catalog: Catalog = Depends(get_catalog)) -> ArtistCollageResolver:
    resolver = getattr(request.app.state, "artist_collage_resolver", None)
    if resolver is None or resolver.catalog is not catalog:
        resolver = ArtistCollageResolver(catalog, request.app.state.cover_dir)
        request.app.state.artist_collage_resolver = resolver
    return resolver


@router.get("/artists/collage")
def artist_collage(
    name: str = Query(min_length=1, max_length=160),
    resolver: ArtistCollageResolver = Depends(get_artist_collage_resolver),
) -> Response:
    collage = resolver.resolve(name)
    if collage is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    payload, key = collage
    return Response(content=payload, media_type="image/jpeg", headers={"ETag": f'"{key}"', "Cache-Control": "public, max-age=2592000, immutable"})


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
