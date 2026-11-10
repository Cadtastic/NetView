from collections.abc import Iterable, Mapping

from netview.sdk import Capability, Plugin, PluginContext, PluginManifest, TrafficReading


class SilentTraffic:
    def read(self) -> Iterable[TrafficReading]:
        return []


class UndeclaredPlugin(Plugin):
    manifest = PluginManifest(
        id="undeclared",
        name="Undeclared",
        version="1.0.0",
        description="Provides TRAFFIC without declaring it",
        sdk_version=">=1.0,<2",
        capabilities=frozenset(),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.TRAFFIC: SilentTraffic()}
