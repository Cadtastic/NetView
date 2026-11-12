from netview.sdk import Capability, Permission, Plugin, PluginContext, PluginManifest, PluginType


class Sdk14Plugin(Plugin):
    """Written for SDK 1.3 to 1.4: declares no user permissions."""

    manifest = PluginManifest(
        id="sdk14",
        name="Old Style",
        version="1.0.0",
        description="Predates user permissions",
        guid="24e7e0b5-6021-4b5e-b529-e77abb165f14",
        display_name="Old Style",
        plugin_type=PluginType.OTHER,
        sdk_version=">=1.3,<2",
        capabilities=frozenset({Capability.API}),
        permissions=frozenset({Permission.API}),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None
