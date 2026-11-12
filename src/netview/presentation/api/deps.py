"""FastAPI dependencies."""

from typing import Annotated, cast

from fastapi import Depends, Request

from netview.application.services import AppServices, AuthServices
from netview.domain.errors import NotFoundError


def get_services(request: Request) -> AppServices:
    services: AppServices = request.app.state.services
    return services


Services = Annotated[AppServices, Depends(get_services)]


SESSION_COOKIE = "netview_session"


def get_auth(request: Request) -> AuthServices:
    auth = request.app.state.services.auth
    if auth is None:
        raise NotFoundError("sign-in is not enabled")
    return cast(AuthServices, auth)


Auth = Annotated[AuthServices, Depends(get_auth)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
