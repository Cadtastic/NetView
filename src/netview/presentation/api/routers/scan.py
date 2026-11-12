from fastapi import APIRouter

from netview.presentation.api.deps import Services
from netview.presentation.api.permissions import require_permission
from netview.presentation.api.schemas import SweepSummaryOut

router = APIRouter()


@router.post("/scan", response_model=SweepSummaryOut, dependencies=[require_permission("core.scan")])
def run_scan(services: Services) -> SweepSummaryOut:
    # A plain `def` endpoint: FastAPI runs it in a worker thread, so the sweep never blocks the loop.
    try:
        return SweepSummaryOut.model_validate(services.run_scan())
    finally:
        services.notifier.state_changed()  # a refused or failed scan still changes what clients see
