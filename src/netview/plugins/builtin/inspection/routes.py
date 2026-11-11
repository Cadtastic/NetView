"""Inspection API."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_router(open_ports: Callable[[], dict[str, list[dict[str, Any]]]]) -> APIRouter:
    router = APIRouter()

    @router.get("/open-ports")
    def get_open_ports() -> dict[str, list[dict[str, Any]]]:
        return open_ports()

    return router
