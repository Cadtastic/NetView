from netview.sdk import Plugin, PluginContext, PluginManifest


class BadSdkPlugin(Plugin):
    manifest = PluginManifest(
        id="bad_sdk",
        name="Bad SDK",
        version="1.0.0",
        description="Needs a newer SDK",
        sdk_version=">=2",
        capabilities=frozenset(),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None
