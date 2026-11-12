"""First-run setup."""

from fastapi import APIRouter, Request, Response

from netview.presentation.api.deps import Auth, client_ip
from netview.presentation.api.routers.auth import me_out, set_session_cookie
from netview.presentation.api.schemas import MeOut, SetupIn, SetupStatusOut

router = APIRouter()


@router.get("/setup", response_model=SetupStatusOut)
def setup_status(auth: Auth) -> SetupStatusOut:
    status = auth.setup.status()
    return SetupStatusOut(
        open=status.open,
        code_required=status.code_required,
        password_min_length=auth.policy.get().password_min_length,
    )


@router.post("/setup", response_model=MeOut)
def complete_setup(body: SetupIn, request: Request, response: Response, auth: Auth) -> MeOut:
    result = auth.setup.complete(
        body.code, body.username, body.password, client_ip(request), request.headers.get("user-agent", "")
    )
    set_session_cookie(response, request, result.token)
    return me_out(auth, result.principal)
