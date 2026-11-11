"""Starlink API."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_router(status: Callable[[], dict[str, Any]]) -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    def get_status() -> dict[str, Any]:
        return status()

    return router
