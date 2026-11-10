from fastapi import APIRouter, Query

from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import EventOut

router = APIRouter()


@router.get("/events", response_model=list[EventOut])
def list_events(services: Services, limit: int = Query(300, ge=1, le=1000)) -> list[EventOut]:
    return [EventOut.model_validate(e) for e in services.events(limit)]
