"""Sign in, sign out, who am I, change my password."""

from fastapi import APIRouter, Request, Response

from netview.application.auth.catalog import catalog_ids
from netview.application.auth.principal import Principal
from netview.application.services import AuthServices
from netview.presentation.api.deps import SESSION_COOKIE, Auth, client_ip
from netview.presentation.api.permissions import CurrentUser
from netview.presentation.api.schemas import LoginIn, MeOut, PasswordChangeIn

router = APIRouter()


def me_out(auth: AuthServices, principal: Principal) -> MeOut:
    return MeOut(
        username=principal.username,
        display_name=principal.display_name,
        provider=principal.provider,
        must_change_password=principal.must_change_password,
        permissions=principal.permissions.as_list(catalog_ids(auth.catalog())),
        is_admin=principal.permissions.everything,
        password_min_length=auth.policy.get().password_min_length,
    )


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        path="/",
        secure=request.url.scheme == "https",
    )


@router.get("/auth/me", response_model=MeOut)
def me(auth: Auth, principal: CurrentUser) -> MeOut:
    return me_out(auth, principal)


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, auth: Auth) -> MeOut:
    result = auth.sign_in(
        body.username, body.password, client_ip(request), request.headers.get("user-agent", "")
    )
    set_session_cookie(response, request, result.token)
    return me_out(auth, result.principal)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, auth: Auth) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth.sessions.end(token)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChangeIn, request: Request, auth: Auth, principal: CurrentUser) -> Response:
    token = request.cookies.get(SESSION_COOKIE, "")
    auth.change_password(principal, body.current, body.new, token, client_ip(request))
    return Response(status_code=204)


@router.get("/auth/providers")
def providers() -> list[str]:
    return []
