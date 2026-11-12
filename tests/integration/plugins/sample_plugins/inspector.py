from collections.abc import Iterable, Mapping

from netview.sdk import (
    Capability,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    ReportSection,
)


class FakeInspection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def inspect(self, ip: str, ports_spec: str) -> Iterable[ReportSection]:
        self.calls.append((ip, ports_spec))
        return [
            ReportSection("inspector", "ports", "Open ports", {"text": ["22 ssh", "80 http"]}),
            ReportSection("inspector", "raw", "Raw facts", {"vendor": "Acme"}),
        ]


class InspectorPlugin(Plugin):
    manifest = PluginManifest(
        id="inspector",
        name="Inspector",
        version="1.0.0",
        description="A fake inspection provider",
        guid="aed1722a-0788-493f-8413-2002ac273027",
        display_name="Inspector",
        plugin_type=PluginType.OTHER,
        sdk_version=">=1.1,<2",
        capabilities=frozenset({Capability.INSPECTION}),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.INSPECTION: FakeInspection()}
