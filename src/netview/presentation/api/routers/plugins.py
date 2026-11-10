from fastapi import APIRouter

from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import PluginOut, PluginPatch

router = APIRouter()


@router.get("/plugins", response_model=list[PluginOut])
def list_plugins(services: Services) -> list[PluginOut]:
    return [PluginOut.model_validate(p) for p in services.plugins.list()]


@router.get("/plugins/{plugin_id}", response_model=PluginOut)
def get_plugin(plugin_id: str, services: Services) -> PluginOut:
    return PluginOut.model_validate(services.plugins.get(plugin_id))


@router.patch("/plugins/{plugin_id}", response_model=PluginOut)
def patch_plugin(plugin_id: str, body: PluginPatch, services: Services) -> PluginOut:
    services.plugins.get(plugin_id)  # 404 before anything changes
    if body.settings is not None:
        services.plugins.update_settings(plugin_id, body.settings)
    if body.enabled is not None:
        services.plugins.set_enabled(plugin_id, body.enabled)
    return PluginOut.model_validate(services.plugins.get(plugin_id))
