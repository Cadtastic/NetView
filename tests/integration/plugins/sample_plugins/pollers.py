from collections.abc import Iterable, Mapping

from pydantic import BaseModel

from netview.sdk import (
    Capability,
    HealthTargets,
    JobSpec,
    LatencySample,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    WatchProbe,
)


class SilentHealth:
    def probe(self, targets: HealthTargets) -> Iterable[LatencySample | WatchProbe]:
        return []


class PollerSettings(BaseModel):
    x: int = 1


class PollerPlugin(Plugin):
    """Provides HEALTH, so the host schedules ``poll.health`` for it."""

    manifest = PluginManifest(
        id="poller",
        name="Poller",
        version="1.0.0",
        description="A health provider",
        guid="e4acddcb-8e52-42b4-8cc6-acbc365fcfc9",
        display_name="Poller",
        plugin_type=PluginType.OTHER,
        sdk_version=">=1.1,<2",
        capabilities=frozenset({Capability.HEALTH, Capability.JOBS}),
        permissions=frozenset(),
    )
    settings_model = PollerSettings

    def setup(self, ctx: PluginContext) -> None:
        return None

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.HEALTH: SilentHealth()}

    def jobs(self) -> list[JobSpec]:
        return [JobSpec(name="own", interval_s=60.0, run=lambda: None)]


class ReservedJobPlugin(Plugin):
    """Declares a job in the namespace the core reserves for capability polling."""

    manifest = PluginManifest(
        id="reserved_job",
        name="Reserved job",
        version="1.0.0",
        description="Uses a poll.* job name",
        guid="10d09c44-5e98-44f3-bd97-073e40135f9f",
        display_name="Reserved job",
        plugin_type=PluginType.OTHER,
        sdk_version=">=1.1,<2",
        capabilities=frozenset({Capability.JOBS}),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None

    def jobs(self) -> list[JobSpec]:
        return [JobSpec(name="poll.x", interval_s=60.0, run=lambda: None)]
