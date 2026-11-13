from fastapi import APIRouter

from netview.application.auth.principal import Principal
from netview.application.ports.plugin_admin import PluginInfo
from netview.application.usecases.install_plugin import InstallJob
from netview.application.usecases.plugin_catalog import CatalogView
from netview.domain.errors import PermissionDeniedError
from netview.presentation.api.deps import Services
from netview.presentation.api.permissions import CurrentUser, require_admin, require_permission
from netview.presentation.api.schemas import (
    AvailableOut,
    CatalogOut,
    InstallIn,
    InstallJobOut,
    PluginOut,
    PluginPatch,
    UninstallIn,
    UninstallOut,
)

router = APIRouter()


def _plugin_out(info: PluginInfo, principal: Principal) -> PluginOut:
    """Settings are for people who may change them; everyone else sees ``null``."""
    out = PluginOut.model_validate(info)
    if not principal.can(f"{info.guid or info.id}.configure"):
        out = out.model_copy(update={"settings": None, "settings_schema": None})
    return out


@router.get("/plugins", response_model=list[PluginOut], dependencies=[require_permission("core.view")])
def list_plugins(services: Services, principal: CurrentUser) -> list[PluginOut]:
    return [_plugin_out(p, principal) for p in services.plugins.list()]


def _catalog_out(view: CatalogView) -> CatalogOut:
    plugins = [
        AvailableOut(
            guid=a.entry.plugin.guid,
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
@router.get("/plugins/catalog", response_model=CatalogOut, dependencies=[require_permission("core.view")])
def get_catalog(services: Services) -> CatalogOut:
    return _catalog_out(services.catalog.view())


@router.post("/plugins/catalog/refresh", response_model=CatalogOut, dependencies=[require_admin()])
def refresh_catalog(services: Services) -> CatalogOut:
    return _catalog_out(services.catalog.refresh())


def _job_out(job: InstallJob) -> InstallJobOut:
    return InstallJobOut(job=job.id, guid=job.guid, state=job.state, percent=job.percent, error=job.error)


@router.post(
    "/plugins/install", response_model=InstallJobOut, status_code=202, dependencies=[require_admin()]
)
def start_install(body: InstallIn, services: Services) -> InstallJobOut:
    return _job_out(services.installs.start(body.guid))


@router.post("/plugins/uninstall", response_model=UninstallOut, dependencies=[require_admin()])
def uninstall_plugin(body: UninstallIn, services: Services) -> UninstallOut:
    return UninstallOut.model_validate(services.plugins.uninstall(body.folder, body.delete_data))


@router.get(
    "/plugins/install/{job_id}", response_model=InstallJobOut, dependencies=[require_permission("core.view")]
)
def get_install_job(job_id: str, services: Services) -> InstallJobOut:
    return _job_out(services.installs.get(job_id))


@router.get("/plugins/{plugin_id}", response_model=PluginOut, dependencies=[require_permission("core.view")])
def get_plugin(plugin_id: str, services: Services, principal: CurrentUser) -> PluginOut:
    return _plugin_out(services.plugins.get(plugin_id), principal)


@router.patch(
    "/plugins/{plugin_id}", response_model=PluginOut, dependencies=[require_permission("core.view")]
)
def patch_plugin(plugin_id: str, body: PluginPatch, services: Services, principal: CurrentUser) -> PluginOut:
    info = services.plugins.get(plugin_id)  # 404 before anything changes
    # Both checks come before either change, so a refused request changes nothing.
    if body.enabled is not None and not principal.can("core.plugins"):
        raise PermissionDeniedError("You do not have permission to turn plugins on or off")
    if body.settings is not None and not principal.can(f"{info.guid or info.id}.configure"):
        raise PermissionDeniedError("You do not have permission to change this plugin's settings")
    if body.settings is not None:
        services.plugins.update_settings(plugin_id, body.settings)
    if body.enabled is not None:
        services.plugins.set_enabled(plugin_id, body.enabled)
    return _plugin_out(services.plugins.get(plugin_id), principal)
