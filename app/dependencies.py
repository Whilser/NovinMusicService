from fastapi import Request

from app.catalog import Catalog


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog
