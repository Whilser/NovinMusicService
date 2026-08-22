from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.catalog import router as catalog_router
from app.catalog import Catalog, CatalogError, ConflictError, NotFoundError


def _error(code: str, message: str, details=None) -> dict:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def create_app(data_dir: Optional[Path] = None, music_root: Optional[Path] = None) -> FastAPI:
    resolved_data_dir = Path(data_dir or os.environ.get("NOVIN_DATA_DIR", "data"))
    application = FastAPI(title="Novin Music Service")
    application.state.catalog = Catalog(resolved_data_dir / "catalog.sqlite3")
    application.state.music_root = Path(music_root or os.environ.get("NOVIN_MUSIC_ROOT", "/music"))

    @application.exception_handler(CatalogError)
    async def catalog_error_handler(request: Request, error: CatalogError) -> JSONResponse:
        if isinstance(error, NotFoundError):
            response_status = 404
        elif isinstance(error, ConflictError):
            response_status = 409
        else:
            response_status = 422
        return JSONResponse(
            status_code=response_status,
            content=_error(error.code, error.message, error.details),
        )

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            {"location": list(item.get("loc", ())), "message": item.get("msg", "invalid value")}
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error("validation_error", "request validation failed", {"errors": details}),
        )

    application.include_router(catalog_router, prefix="/api")
    # Wave-one extension seams: later feature routers become active by exporting
    # ``router`` from these agreed modules; missing future modules are harmless.
    for module_name in ("app.api.scan", "app.api.player"):
        try:
            feature_module = import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name != module_name:
                raise
        else:
            application.include_router(feature_module.router, prefix="/api")

    @application.on_event("shutdown")
    def close_catalog() -> None:
        application.state.catalog.close()

    return application


app = create_app()
