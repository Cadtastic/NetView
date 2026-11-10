from fastapi import APIRouter

from netview.domain.errors import NotFoundError
from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import WatchIn, WatchOut

router = APIRouter()


@router.get("/watches", response_model=list[WatchOut])
def list_watches(services: Services) -> list[WatchOut]:
    return [WatchOut.model_validate(w) for w in services.state().watches]


@router.post("/watches", response_model=WatchOut)
def add_watch(body: WatchIn, services: Services) -> WatchOut:
    return WatchOut.model_validate(services.add_watch(body.spec))


@router.delete("/watches/{ip}")
def remove_watch(ip: str, services: Services) -> dict[str, bool]:
    if not services.remove_watch(ip):
        raise NotFoundError(f"no watch for {ip}")
    return {"removed": True}
