from netview.sdk import Capability, Permission, Plugin, PluginContext, PluginManifest


class Sdk14Plugin(Plugin):
    """Written for SDK 1.3 to 1.4: declares no user permissions."""

    manifest = PluginManifest(
        id="sdk14",
        name="Old Style",
        version="1.0.0",
        description="Predates user permissions",
        sdk_version=">=1.3,<2",
        capabilities=frozenset({Capability.API}),
        permissions=frozenset({Permission.API}),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None
