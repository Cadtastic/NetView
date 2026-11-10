from fastapi import APIRouter

from netview.domain.errors import NotFoundError
from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import InspectionIn, InspectionReportOut

router = APIRouter()


@router.post("/inspections", response_model=InspectionReportOut)
def run_inspection(body: InspectionIn, services: Services) -> InspectionReportOut:
    return InspectionReportOut.model_validate(services.run_inspection(body.ip, body.ports))


@router.get("/inspections/{ip}", response_model=InspectionReportOut)
def latest_inspection(ip: str, services: Services) -> InspectionReportOut:
    report = services.latest_inspection(ip)
    if report is None:
        raise NotFoundError(f"no inspection for {ip}")
    return InspectionReportOut.model_validate(report)
