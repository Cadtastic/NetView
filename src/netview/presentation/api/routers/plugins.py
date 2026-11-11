from fastapi import APIRouter

from netview.application.usecases.plugin_catalog import CatalogView
from netview.presentation.api.deps import Services
from netview.presentation.api.schemas import AvailableOut, CatalogOut, PluginOut, PluginPatch

router = APIRouter()


@router.get("/plugins", response_model=list[PluginOut])
def list_plugins(services: Services) -> list[PluginOut]:
    return [PluginOut.model_validate(p) for p in services.plugins.list()]


def _catalog_out(view: CatalogView) -> CatalogOut:
    plugins = [
        AvailableOut(
            id=a.entry.plugin.id,
            name=a.entry.plugin.name,
            version=a.entry.plugin.version,
            description=a.entry.plugin.description,
            author=a.entry.plugin.author,
            homepage=a.entry.plugin.homepage,
            license=a.entry.plugin.license,
            sdk_version=a.entry.plugin.sdk_version,
            capabilities=list(a.entry.plugin.capabilities),
            permissions=list(a.entry.plugin.permissions),
            requires=list(a.entry.plugin.requires),
            path=a.entry.path,
            installable=a.installable,
            reason=a.reason,
        )
        for a in view.plugins
    ]
    return CatalogOut(
        source=view.source,
        fetched_at_ms=view.fetched_at_ms,
        error=view.error,
        stale=view.stale,
        plugins=plugins,
    )


# the fixed routes come before /plugins/{plugin_id} so a plugin id can never shadow them
@router.get("/plugins/catalog", response_model=CatalogOut)
def get_catalog(services: Services) -> CatalogOut:
    return _catalog_out(services.catalog.view())


@router.post("/plugins/catalog/refresh", response_model=CatalogOut)
def refresh_catalog(services: Services) -> CatalogOut:
    return _catalog_out(services.catalog.refresh())


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
