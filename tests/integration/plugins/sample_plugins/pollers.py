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
        sdk_version=">=1.1,<2",
        capabilities=frozenset({Capability.JOBS}),
        permissions=frozenset(),
    )

    def setup(self, ctx: PluginContext) -> None:
        return None

    def jobs(self) -> list[JobSpec]:
        return [JobSpec(name="poll.x", interval_s=60.0, run=lambda: None)]
