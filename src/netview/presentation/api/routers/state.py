from fastapi import APIRouter

from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import NetworkStateOut

router = APIRouter()


@router.get("/state", response_model=NetworkStateOut)
def get_state(services: Services) -> NetworkStateOut:
    return NetworkStateOut.model_validate(services.state())
