"""A signed-in user's dashboard layout."""

from typing import Any

from fastapi import APIRouter

from netview.application.usecases.dashboard import LayoutView
from netview.domain.dashboard import layout_to_dict, parse_layout
from netview.presentation.api.deps import Auth
from netview.presentation.api.permissions import CurrentUser, require_permission
from netview.presentation.api.schemas import LayoutOut

router = APIRouter(prefix="/dashboard")


def layout_out(view: LayoutView) -> LayoutOut:
    return LayoutOut(
        layout=None if view.layout is None else layout_to_dict(view.layout),
        source=view.source,
        updated_ms=view.updated_ms,
        default=None if view.default is None else layout_to_dict(view.default),
    )


@router.get("/layout", response_model=LayoutOut, dependencies=[require_permission("core.view")])
def get_layout(auth: Auth, actor: CurrentUser) -> LayoutOut:
    return layout_out(auth.dashboard.mine(actor))


@router.put("/layout", response_model=LayoutOut, dependencies=[require_permission("core.dashboard")])
def put_layout(body: dict[str, Any], auth: Auth, actor: CurrentUser) -> LayoutOut:
    return layout_out(auth.dashboard.save_mine(actor, parse_layout(body)))


@router.delete("/layout", response_model=LayoutOut, dependencies=[require_permission("core.view")])
def delete_layout(auth: Auth, actor: CurrentUser) -> LayoutOut:
    return layout_out(auth.dashboard.reset_mine(actor))
