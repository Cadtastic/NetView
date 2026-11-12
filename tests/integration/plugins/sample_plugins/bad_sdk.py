from netview.sdk import Plugin, PluginContext, PluginManifest, PluginType


class BadSdkPlugin(Plugin):
    manifest = PluginManifest(
        id="bad_sdk",
        name="Bad SDK",
        version="1.0.0",
        description="Needs a newer SDK",
        guid="aa909c6f-c03e-4365-ad84-03990201c528",
        display_name="Bad SDK",
        plugin_type=PluginType.OTHER,
        sdk_version=">=2",
        capabilities=frozenset(),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None
