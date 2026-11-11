"""health API."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_router(summary: Callable[[], dict[str, Any]]) -> APIRouter:
    router = APIRouter()

    @router.get("/summary")
    def get_summary() -> dict[str, Any]:
        return summary()

    return router
