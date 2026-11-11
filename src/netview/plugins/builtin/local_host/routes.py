"""local_host API."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_router(snapshot: Callable[[], dict[str, Any]]) -> APIRouter:
    router = APIRouter()

    @router.get("/snapshot")
    def get_snapshot() -> dict[str, Any]:
        return snapshot()

    return router
