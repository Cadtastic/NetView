from netview.sdk import Plugin, PluginContext, PluginManifest, PluginType


class CrashSetupPlugin(Plugin):
    manifest = PluginManifest(
        id="crash_setup",
        name="Crash setup",
        version="1.0.0",
        description="setup() raises",
        guid="4b623e91-dc56-42a4-89ea-e436fac8f438",
        display_name="Crash setup",
        plugin_type=PluginType.OTHER,
        sdk_version=">=1.0,<2",
        capabilities=frozenset(),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        raise RuntimeError("boom")
