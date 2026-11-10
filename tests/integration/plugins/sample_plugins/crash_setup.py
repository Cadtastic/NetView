from netview.sdk import Plugin, PluginContext, PluginManifest


class CrashSetupPlugin(Plugin):
    manifest = PluginManifest(
        id="crash_setup",
        name="Crash setup",
        version="1.0.0",
        description="setup() raises",
        sdk_version=">=1.0,<2",
        capabilities=frozenset(),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        raise RuntimeError("boom")
