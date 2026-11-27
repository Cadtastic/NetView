from __future__ import annotations

from typing import Any

from netview_local_plugins.geotrace.plugin import GeoTracePlugin
from netview_local_plugins.geotrace.settings import GeoTraceSettings


class StubService:
    def __init__(self) -> None:
        self.changed: list[GeoTraceSettings] = []
        self.stopped = 0

    def tick(self) -> None: ...

    def cleanup(self) -> None: ...

    def update_geo(self) -> None: ...

    def settings_changed(self, settings: GeoTraceSettings) -> None:
        self.changed.append(settings)

    def stop(self) -> None:
        self.stopped += 1


def make(settings: GeoTraceSettings) -> tuple[GeoTracePlugin, StubService]:
    plugin = GeoTracePlugin()
    stub = StubService()
    plugin._service = stub  # type: ignore[assignment]
    plugin.settings = settings
    return plugin, stub


def _shape(plugin: GeoTracePlugin) -> list[tuple[Any, ...]]:
    return [(j.name, j.interval_s, j.timeout_s, j.initial_delay_s) for j in plugin.jobs()]


def test_jobs_include_the_geodata_update_when_it_is_automatic() -> None:
    plugin, stub = make(GeoTraceSettings(geo_auto_update=True))
    assert _shape(plugin) == [
        ("tick", 30, 10, 15),
        ("cleanup", 86400, 120, 600),
        ("geodata", 86400, 600, 60),
    ]
    assert [j.run for j in plugin.jobs()] == [stub.tick, stub.cleanup, stub.update_geo]


def test_jobs_leave_out_the_geodata_update_when_it_is_off() -> None:
    plugin, _ = make(GeoTraceSettings(geo_auto_update=False))
    assert [j.name for j in plugin.jobs()] == ["tick", "cleanup"]


def test_a_settings_change_reaches_the_service_and_the_job_list() -> None:
    plugin, stub = make(GeoTraceSettings(geo_auto_update=False))
    changed = GeoTraceSettings(geo_auto_update=True)
    plugin.on_settings_changed(changed)
    assert stub.changed == [changed]
    assert "geodata" in [j.name for j in plugin.jobs()]


def test_there_are_no_jobs_before_setup_and_shutdown_stops_the_service() -> None:
    assert GeoTracePlugin().jobs() == []
    plugin, stub = make(GeoTraceSettings())
    plugin.shutdown()
    assert stub.stopped == 1
