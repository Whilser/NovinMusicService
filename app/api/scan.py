from __future__ import annotations

import threading
from functools import lru_cache
from typing import Dict

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.catalog import Catalog
from app.dependencies import get_catalog
from app.scanner import CoverAsset, Scanner
from app.scanner.scanner import MAX_COVER_BYTES
from app.share import ShareError, ShareManager


router = APIRouter()


class ShareInput(BaseModel):
    host: str
    share: str
    domain: str = ""
    options: str = ""


class ScanJobs:
    def __init__(self):
        self._lock = threading.Lock()
        self._status = {"state": "idle", "counters": self._empty_counters()}
        self._covers: Dict[str, CoverAsset] = {}

    @staticmethod
    def _empty_counters() -> dict:
        return {"discovered": 0, "indexed": 0, "unreadable": 0, "unsupported": 0}

    def start(self, scanner: Scanner, root, catalog: Catalog, manager: ShareManager, settings: dict) -> bool:
        with self._lock:
            if self._status["state"] == "running":
                return False
            self._status = {"state": "running", "counters": self._empty_counters()}
        threading.Thread(
            target=self._run,
            args=(scanner, root, catalog, manager, settings),
            name="novin-library-scan",
            daemon=True,
        ).start()
        return True

    def _run(self, scanner: Scanner, root, catalog: Catalog, manager: ShareManager, settings: dict) -> None:
        try:
            if settings.get("host") and settings.get("share"):
                share_status = manager.apply(settings)
                if share_status.get("state") != "connected":
                    raise ShareError("SMB mount failed")
            snapshot = scanner.scan(root, progress=self._progress)
            reconciliation = catalog.reconcile_tracks(snapshot.tracks)
        except Exception as error:
            with self._lock:
                self._status = {
                    "state": "error",
                    "counters": {},
                    "error": {"code": "scan_failed", "message": str(error) or "scan failed"},
                }
            return
        with self._lock:
            self._covers = dict(snapshot.covers)
            counters = dict(snapshot.counters)
            counters.update({"removed": reconciliation["removed"]})
            self._status = {"state": "completed", "counters": counters}

    def _progress(self, counters: dict) -> None:
        with self._lock:
            if self._status["state"] == "running":
                self._status = {"state": "running", "counters": dict(counters)}

    def status(self) -> dict:
        with self._lock:
            return {**self._status, "counters": dict(self._status.get("counters", {}))}

    def cover(self, cover_id: str):
        with self._lock:
            return self._covers.get(cover_id)


@lru_cache(maxsize=1)
def get_scanner() -> Scanner:
    return Scanner()


def get_scan_jobs(request: Request) -> ScanJobs:
    if not hasattr(request.app.state, "scan_jobs"):
        request.app.state.scan_jobs = ScanJobs()
    return request.app.state.scan_jobs


@lru_cache(maxsize=1)
def get_share_manager() -> ShareManager:
    return ShareManager()


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def start_scan(
    request: Request,
    scanner: Scanner = Depends(get_scanner),
    jobs: ScanJobs = Depends(get_scan_jobs),
    manager: ShareManager = Depends(get_share_manager),
    catalog: Catalog = Depends(get_catalog),
):
    saved = catalog.get_settings()
    share_settings = {
        "host": saved.get("smb_host", ""),
        "share": saved.get("smb_share", ""),
        "domain": saved.get("smb_domain", ""),
        "options": saved.get("smb_options", ""),
    }
    if not jobs.start(scanner, request.app.state.music_root, catalog, manager, share_settings):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": {"code": "scan_in_progress", "message": "a scan is already running"}},
        )
    return jobs.status()


@router.get("/scan/status")
def scan_status(jobs: ScanJobs = Depends(get_scan_jobs)) -> dict:
    return jobs.status()


@router.post("/share")
def apply_share(
    body: ShareInput,
    manager: ShareManager = Depends(get_share_manager),
    catalog: Catalog = Depends(get_catalog),
):
    settings = {"host": body.host, "share": body.share, "domain": body.domain, "options": body.options}
    try:
        result = manager.apply(settings)
    except ShareError as error:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": {"code": "invalid_share", "message": str(error)}},
        )
    if result.get("state") != "connected":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {"code": "share_mount_failed", "message": "SMB mount failed"},
                "status": result,
            },
        )
    catalog.update_settings(
        {
            "smb_host": body.host,
            "smb_share": body.share,
            "smb_domain": body.domain,
            "smb_options": body.options,
        }
    )
    return result


@router.get("/share/status")
def share_status(manager: ShareManager = Depends(get_share_manager)) -> dict:
    return manager.status()


_PLACEHOLDER = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1" fill="#eee"/></svg>'


@router.get("/covers/{cover_id}")
def cover(cover_id: str, request: Request, jobs: ScanJobs = Depends(get_scan_jobs)) -> Response:
    asset = jobs.cover(cover_id) if len(cover_id) == 64 and cover_id.isalnum() else None
    if asset is None or len(asset.data) > MAX_COVER_BYTES:
        return Response(content=_PLACEHOLDER, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=300"})
    etag = f'"{asset.etag}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return Response(
        content=asset.data,
        media_type=asset.mime_type,
        headers={"ETag": etag, "Cache-Control": "public, max-age=86400"},
    )
