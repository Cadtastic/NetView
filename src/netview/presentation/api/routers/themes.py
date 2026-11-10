from fastapi import APIRouter

from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import ThemeListOut, ThemeOut

router = APIRouter()


@router.get("/themes", response_model=ThemeListOut)
def list_themes(services: Services) -> ThemeListOut:
    return ThemeListOut(
        themes=[ThemeOut.model_validate(t) for t in services.themes.list()],
        user_dir=services.themes.user_dir(),
    )
