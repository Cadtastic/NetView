import time

from netview.sdk import Plugin, PluginContext, PluginManifest


class SlowSetupPlugin(Plugin):
    manifest = PluginManifest(
        id="slow_setup",
        name="Slow setup",
        version="1.0.0",
        description="setup() sleeps far too long",
        sdk_version=">=1.0,<2",
        capabilities=frozenset(),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        time.sleep(30)
