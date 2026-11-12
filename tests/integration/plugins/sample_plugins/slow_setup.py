import time

from netview.sdk import Plugin, PluginContext, PluginManifest, PluginType


class SlowSetupPlugin(Plugin):
    manifest = PluginManifest(
        name="Slow setup",
        version="1.0.0",
        description="setup() sleeps far too long",
        guid="a2a64599-d79e-49a5-aea9-6720372c53a0",
        display_name="Slow setup",
        plugin_type=PluginType.OTHER,
        sdk_version=">=2.0,<3",
        capabilities=frozenset(),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        time.sleep(30)
