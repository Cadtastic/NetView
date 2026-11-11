from typing import Annotated

from fastapi import APIRouter, Path, Response

from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import DeviceOut, InspectionReportOut, Ipv4, NicknameIn

router = APIRouter()


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(services: Services) -> list[DeviceOut]:
    return [DeviceOut.model_validate(d) for d in services.state().devices]


@router.get("/devices/{key}", response_model=DeviceOut)
def get_device(key: str, services: Services) -> DeviceOut:
    return DeviceOut.model_validate(services.device(key))


@router.put("/devices/{key}/nickname", response_model=DeviceOut)
def put_nickname(key: str, body: NicknameIn, services: Services) -> DeviceOut:
    services.set_nickname(key, body.nickname)
    return DeviceOut.model_validate(services.device(key))


@router.delete("/devices/{key}", status_code=204)
def forget_device(key: str, services: Services) -> Response:
    """Forget a device and what was learned about it. Its nickname is kept."""
    services.forget_device(key)
    return Response(status_code=204)


@router.post("/devices/{ip}/probe", response_model=InspectionReportOut)
def probe_device(ip: Annotated[Ipv4, Path()], services: Services) -> InspectionReportOut:
    """A quick inspection (the common ports) that is returned but not stored or announced."""
    return InspectionReportOut.model_validate(services.run_inspection(ip, "common", store=False))
