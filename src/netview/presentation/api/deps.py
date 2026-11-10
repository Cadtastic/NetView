"""FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from netview.application.services import AppServices


def get_services(request: Request) -> AppServices:
    services: AppServices = request.app.state.services
    return services


Services = Annotated[AppServices, Depends(get_services)]
