"""Where a plugin lives in a running test app: addresses carry its source_id, which the app assigns."""

from netview.application.services import AppServices


def plugin_key(services: AppServices, guid: str) -> str:
    """The runtime key (``str(source_id)``) the app gave the plugin with this guid."""
    for info in services.plugins.list():
        if info.guid == guid and info.owns_data:
            return info.id
    raise LookupError(f"no plugin with guid {guid} was loaded")


def api_base(services: AppServices, guid: str) -> str:
    """``/api/v1/plugins/<source_id>``"""
    return f"/api/v1/plugins/{plugin_key(services, guid)}"


def static_base(services: AppServices, guid: str) -> str:
    """``/plugins/<source_id>/static``"""
    return f"/plugins/{plugin_key(services, guid)}/static"
