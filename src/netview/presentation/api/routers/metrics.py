import time
from typing import Annotated

from fastapi import APIRouter, Query

from netview.presentation.api.deps import Services
from netview.presentation.api.permissions import require_permission
from netview.presentation.api.schemas import MetricsOut

router = APIRouter()


@router.get("/metrics", response_model=MetricsOut, dependencies=[require_permission("core.view")])
def get_metrics(
    services: Services,
    since_ms: Annotated[int, Query(description="Only points newer than this (epoch ms)")] = 0,
    prefix: Annotated[list[str] | None, Query(description="Series name prefix; repeat for several")] = None,
) -> MetricsOut:
    series = services.metrics.snapshot(tuple(prefix or ()), since_ms)
    return MetricsOut(now_ms=int(time.time() * 1000), series=series)
