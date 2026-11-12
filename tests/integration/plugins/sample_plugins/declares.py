import uuid

from netview.sdk import (
    Capability,
    Permission,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    UserPermission,
)


def _manifest(plugin_id: str) -> PluginManifest:
    return PluginManifest(
        name=plugin_id.title(),
        version="1.0.0",
        description="Declares user permissions",
        guid=str(uuid.uuid5(uuid.NAMESPACE_DNS, plugin_id)),
        display_name=plugin_id.title(),
        plugin_type=PluginType.OTHER,
        sdk_version=">=2.0,<3",
        capabilities=frozenset({Capability.API}),
        permissions=frozenset({Permission.API}),
    )


class DeclaresPlugin(Plugin):
    manifest = _manifest("declares")
    user_permissions = (
        UserPermission("console", "Open the console", "Run commands", dangerous=True),
        UserPermission("use", "Send commands"),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None


class BadIdPlugin(Plugin):
    manifest = _manifest("bad_id")
    user_permissions = (UserPermission("Not An Id", "Broken"),)

    def setup(self, ctx: PluginContext) -> None:
        return None


class TwicePlugin(Plugin):
    manifest = _manifest("twice")
    user_permissions = (UserPermission("a", "A"), UserPermission("a", "A again"))

    def setup(self, ctx: PluginContext) -> None:
        return None


class NoSettingsConfigurePlugin(Plugin):
    """Declares ``configure`` although it has no settings, so there is no automatic one to relabel."""

    manifest = _manifest("no_configure")
    user_permissions = (UserPermission("configure", "Configure"),)

    def setup(self, ctx: PluginContext) -> None:
        return None
