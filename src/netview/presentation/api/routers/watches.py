from fastapi import APIRouter

from netview.domain.errors import NotFoundError
from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import WatchIn, WatchListItemOut, WatchOut, WatchStatusOut

router = APIRouter()


@router.get("/watches", response_model=list[WatchListItemOut])
def list_watches(services: Services) -> list[WatchListItemOut]:
    state = services.state()
    status = {s.ip: WatchStatusOut.model_validate(s).model_dump() for s in state.watch_status}
    return [
        WatchListItemOut.model_validate(
            {**status.get(w.ip, {}), "ip": w.ip, "ports": w.ports, "label": w.label}
        )
        for w in state.watches
    ]


@router.post("/watches", response_model=WatchOut)
def add_watch(body: WatchIn, services: Services) -> WatchOut:
    return WatchOut.model_validate(services.add_watch(body.spec))


@router.delete("/watches/{ip}")
def remove_watch(ip: str, services: Services) -> dict[str, bool]:
    if not services.remove_watch(ip):
        raise NotFoundError(f"no watch for {ip}")
    return {"removed": True}
