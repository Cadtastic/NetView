from fastapi import APIRouter

from netview.presentation.api.deps import Services
from netview.presentation.api.permissions import require_permission
from netview.presentation.api.schemas import ThemeListOut, ThemeOut

router = APIRouter()


@router.get("/themes", response_model=ThemeListOut, dependencies=[require_permission("core.view")])
def list_themes(services: Services) -> ThemeListOut:
    return ThemeListOut(
        themes=[ThemeOut.model_validate(t) for t in services.themes.list()],
        user_dir=services.themes.user_dir(),
    )
