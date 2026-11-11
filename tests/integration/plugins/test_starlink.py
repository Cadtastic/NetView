"""The starlink plugin: wire client, readings, names, stored baselines, failure handling and the fence."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from conftest import HostEnv
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlink_wire import FIXTURE, client, default_response, frame, lfield, response, vfield

from netview.application.queries.read_models import DeviceView
from netview.infrastructure.db.migrate import upgrade_plugin
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.infrastructure.scheduler import AsyncScheduler
from netview.plugins.builtin.starlink.client import UNREADABLE, starlink_clients
from netview.plugins.builtin.starlink.plugin import StarlinkPlugin
from netview.plugins.builtin.starlink.settings import StarlinkSettings
from netview.plugins.builtin.starlink.storage import counters
from netview.sdk import Capability, JobSpec, NameClaim, Plugin, PluginContext, PluginManifest, TrafficReading
from netview.sdk.testing.contract import _FakeContext, check_plugin
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    FakeServiceProbes,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
    RecordingEventBus,
)

Reply = tuple[int, Mapping[str, str], bytes]


def ok(body: bytes | None = None, headers: Mapping[str, str] | None = None) -> Reply:
    return 200, dict(headers or {}), default_response() if body is None else body


class FakePost:
    """The injectable transport: records calls and returns (or raises) what it was given."""

    def __init__(self, reply: Reply | BaseException | None = None) -> None:
        self.reply: Reply | BaseException = reply if reply is not None else ok()
        self.calls: list[tuple[str, int, str, bytes, Mapping[str, str], float]] = []

    def __call__(
        self, host: str, port: int, path: str, body: bytes, headers: Mapping[str, str], timeout_s: float
    ) -> Reply:
        self.calls.append((host, port, path, body, headers, timeout_s))
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def device(key: str, ip: str, is_self: bool = False) -> DeviceView:
    return DeviceView(
        key=key,
        ip=ip,
        mac=None,
        vendor="",
        nickname=None,
        device_name="",
        name_source="",
        type="",
        type_source="",
        hints=[],
        status="online",
        rtt_ms=None,
        ttl=None,
        first_seen_ms=0,
        last_seen_ms=0,
        is_new=False,
        is_self=is_self,
        watched=False,
        display_name="",
    )


# ---- the wire client


def test_contract() -> None:
    check_plugin(StarlinkPlugin)


def test_the_fixture_is_what_the_helper_builds() -> None:
    assert FIXTURE.read_bytes() == default_response()


def test_the_fixture_gives_two_clients_and_skips_the_routers_own_entry() -> None:
    post = FakePost(ok(FIXTURE.read_bytes()))
    clients = starlink_clients("192.0.2.1", 9001, 4.0, post=post)
    assert [c["ip"] for c in clients] == ["192.0.2.20", "192.0.2.21"]
    tv, mesh = clients
    assert (tv["down_bytes"], tv["up_bytes"], tv["signal"], tv["role"]) == (
        5_000_000,
        300_000,
        -52.5,
        "client",
    )
    assert (tv["name"], tv["ap"], tv["assoc_s"], tv["down_link"], tv["up_link"]) == (
        "Living room TV",
        "Kitchen",
        7200,
        866,
        433,
    )
    assert mesh["role"] == "mesh node"
    assert mesh["down_link"] is None


def test_only_the_empty_wifi_get_clients_request_is_sent() -> None:
    post = FakePost()
    starlink_clients("192.0.2.1", 9001, 4.0, post=post)
    [(host, port, path, body, headers, timeout)] = post.calls
    assert (host, port, path, timeout) == ("192.0.2.1", 9001, "/SpaceX.API.Device.Device/Handle", 4.0)
    assert body == b"\x00\x00\x00\x00\x04\xd2\xbb\x01\x00"  # field 3002, empty
    assert headers["Content-Type"] == "application/grpc-web+proto"


def test_a_name_is_cut_to_60_characters_and_a_bad_signal_is_none() -> None:
    long = client("192.0.2.30", name="x" * 100, down=1, up=1, signal=float("nan"))
    [c] = starlink_clients("h", post=FakePost(ok(response([long]))))
    assert len(c["name"]) == 60
    assert c["signal"] is None


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ((404, {}, b"<html>not found</html>"), "router API refused: HTTP 404"),
        ((200, {"grpc-status": "12", "grpc-message": "unimplemented"}, b""), "unimplemented"),
        ((200, {"Grpc-Status": "12"}, b""), "grpc-status 12"),
        ((200, {}, response([], trailer="grpc-status: 12\r\ngrpc-message: nope\r\n")), "nope"),
    ],
)
def test_a_refusal_is_an_os_error_with_the_routers_message(reply: Reply, message: str) -> None:
    with pytest.raises(OSError, match="router API refused: HTTP") as raised:
        starlink_clients("h", post=FakePost(reply))
    assert message in str(raised.value)
    if reply[0] == 404:
        assert str(raised.value) == "router API refused: HTTP 404"


def test_a_connection_failure_propagates_as_an_os_error() -> None:
    with pytest.raises(ConnectionRefusedError):
        starlink_clients("h", post=FakePost(ConnectionRefusedError("refused")))


def test_a_body_that_does_not_list_clients_is_an_os_error() -> None:
    with pytest.raises(OSError, match="router API sent no client list"):
        starlink_clients("h", post=FakePost(ok(b"")))


def test_a_body_cut_in_half_is_an_unreadable_answer() -> None:
    body = default_response()
    with pytest.raises(ValueError) as raised:
        starlink_clients("h", post=FakePost(ok(body[: len(body) // 2])))
    assert str(raised.value) == "router API sent an unreadable answer" == UNREADABLE


@pytest.mark.parametrize(
    "junk", [b"\xff" * 40, b"<html>not grpc at all</html>", b"\x00\x00\x00\x00", bytes(range(256))]
)
def test_garbage_is_an_unreadable_answer_or_a_missing_list_never_another_exception(junk: bytes) -> None:
    with pytest.raises((OSError, ValueError)):
        starlink_clients("h", post=FakePost(ok(junk)))


def test_a_truncated_client_message_inside_a_good_frame_is_unreadable() -> None:
    bad = frame(lfield(3002, lfield(1, b"\x1a\x09192.0.2")))  # field 3, length 9, only 7 bytes
    with pytest.raises(ValueError, match="unreadable"):
        starlink_clients("h", post=FakePost(ok(bad)))


# ---- the plugin


def make_plugin(
    post: FakePost | None = None,
    settings: StarlinkSettings | None = None,
    gateway: str | None = "192.0.2.1",
    devices: dict[str, DeviceView] | None = None,
) -> tuple[StarlinkPlugin, _FakeContext, FakePost]:
    plugin = StarlinkPlugin()
    plugin.settings = settings or StarlinkSettings()
    fake = post or FakePost()
    plugin.post = fake
    ctx = _FakeContext("starlink", plugin.settings)
    ctx.core.host.return_value.gateway = gateway
    known = devices or {}
    ctx.core.device_by_ip.side_effect = lambda ip: known.get(ip)
    plugin.setup(ctx)  # type: ignore[arg-type]
    return plugin, ctx, fake


def test_manifest() -> None:
    m = StarlinkPlugin.manifest
    assert (m.id, m.name, m.version) == ("starlink", "Starlink router", "0.1.0")
    assert (
        m.description == "Per-device traffic, signal and names from a Starlink router's local API (read-only)"
    )
    assert m.sdk_version == ">=1.1,<2"
    assert m.capabilities == {Capability.TRAFFIC, Capability.STORAGE, Capability.API, Capability.WEB_UI}
    assert {p.value for p in m.permissions} == {
        "devices:read",
        "names:write",
        "traffic:write",
        "storage:own",
        "network:probe",
        "api",
        "ui",
    }


def test_settings_defaults_and_limits() -> None:
    s = StarlinkSettings()
    assert (s.router, s.port, s.timeout_s) == (None, 9001, 4.0)
    assert StarlinkSettings(router=" 192.168.1.1 ").router == "192.168.1.1"
    assert StarlinkSettings(router="").router is None
    for bad in ({"router": "starlink.local"}, {"router": "999.1.1.1"}, {"timeout_s": 0.5}, {"timeout_s": 31}):
        with pytest.raises(ValueError):
            StarlinkSettings(**bad)


def test_the_plugin_provides_traffic_and_no_poll_job_of_its_own() -> None:
    plugin, _, _ = make_plugin()
    assert plugin.providers() == {Capability.TRAFFIC: plugin}
    assert plugin.jobs() == []


def test_read_returns_a_reading_per_client_with_counters() -> None:
    plugin, ctx, post = make_plugin()
    readings = list(plugin.read())
    assert [r.ip for r in readings] == ["192.0.2.20", "192.0.2.21"]
    tv = readings[0]
    assert isinstance(tv, TrafficReading)
    assert (tv.down_bytes, tv.up_bytes, tv.t_ms) == (5_000_000, 300_000, ctx.clock.now_ms())
    assert tv.extra == {
        "name": "Living room TV",
        "signal_dbm": -52.5,
        "down_link": 866,
        "up_link": 433,
        "assoc_s": 7200,
        "role": "client",
        "ap": "Kitchen",
    }
    assert post.calls[0][0] == "192.0.2.1"  # the gateway


def test_the_configured_router_and_port_win_over_the_gateway() -> None:
    plugin, _, post = make_plugin(settings=StarlinkSettings(router="192.0.2.9", port=9002, timeout_s=2.5))
    plugin.read()
    assert post.calls[0][:3] == ("192.0.2.9", 9002, "/SpaceX.API.Device.Device/Handle")
    assert post.calls[0][5] == 2.5


def test_without_a_router_or_gateway_the_read_fails_without_asking_anyone() -> None:
    plugin, _, post = make_plugin(gateway=None)
    with pytest.raises(OSError, match="no router address and no gateway"):
        plugin.read()  # a failed job, so the UI does not say devices are not router clients
    assert post.calls == []
    assert plugin.status()["target"] is None


def test_a_stats_message_without_a_byte_count_means_zero_bytes() -> None:
    """proto3 leaves out a zero, so a present rx_stats / tx_stats with no field 1 is a count of 0."""
    fresh = client("192.0.2.50", name="Phone") + lfield(5, b"") + lfield(6, b"")
    no_upload = client("192.0.2.51", name="Laptop", down=900) + lfield(6, vfield(8, 433))
    [a, b] = starlink_clients("h", post=FakePost(ok(response([fresh, no_upload]))))
    assert (a["down_bytes"], a["up_bytes"]) == (0, 0)
    assert (b["down_bytes"], b["up_bytes"], b["up_link"]) == (900, 0, 433)


def test_a_client_with_no_stats_at_all_has_no_byte_counts() -> None:
    [c] = starlink_clients("h", post=FakePost(ok(response([client("192.0.2.40", name="Printer")]))))
    assert (c["down_bytes"], c["up_bytes"]) == (None, None)


def test_every_listed_client_gets_a_reading_and_one_without_counters_has_none() -> None:
    body = response(
        [
            client("192.0.2.40", name="Printer"),
            client("192.0.2.41", down=10, up=20),
            client("192.0.2.42", name="Phone") + lfield(5, b"") + lfield(6, b""),
        ]
    )
    plugin, ctx, _ = make_plugin(FakePost(ok(body)))
    readings = {r.ip: r for r in plugin.read() if r.t_ms == ctx.clock.now_ms()}
    assert list(readings) == ["192.0.2.40", "192.0.2.41", "192.0.2.42"]
    assert (readings["192.0.2.40"].down_bytes, readings["192.0.2.40"].up_bytes) == (None, None)
    assert readings["192.0.2.40"].extra["name"] == "Printer"
    assert (readings["192.0.2.41"].down_bytes, readings["192.0.2.41"].up_bytes) == (10, 20)
    assert (readings["192.0.2.42"].down_bytes, readings["192.0.2.42"].up_bytes) == (0, 0)


def test_a_dhcp_name_is_claimed_for_a_known_device_and_not_for_an_unknown_one_or_this_device() -> None:
    known = {
        "192.0.2.20": device("aa:01", "192.0.2.20"),
        "192.0.2.22": device("self", "192.0.2.22", is_self=True),
    }
    body = response(
        [
            client("192.0.2.20", name="Living room TV", down=1, up=1),
            client("192.0.2.21", name="Stranger", down=1, up=1),
            client("192.0.2.22", name="Me", down=1, up=1),
            client("192.0.2.23", name="", down=1, up=1),
        ]
    )
    plugin, ctx, _ = make_plugin(FakePost(ok(body)), devices=known)
    plugin.read()
    [call] = ctx.core.claim.call_args_list
    [items] = call.args
    assert items == [NameClaim("aa:01", "Living room TV", "DHCP", 3.5, ctx.clock.now_ms())]


def test_a_claim_that_fails_does_not_fail_the_read() -> None:
    plugin, ctx, _ = make_plugin(devices={"192.0.2.20": device("aa:01", "192.0.2.20")})
    ctx.core.claim.side_effect = RuntimeError("db is busy")
    assert len(list(plugin.read())) == 2


def test_status_reports_the_target_the_last_success_and_the_last_error() -> None:
    plugin, ctx, post = make_plugin()
    assert plugin.status() == {"target": None, "last_ok_ms": None, "error": ""}
    plugin.read()
    assert plugin.status() == {"target": "192.0.2.1", "last_ok_ms": ctx.clock.now_ms(), "error": ""}
    ctx.clock.advance(5_000)  # type: ignore[attr-defined]
    post.reply = (404, {}, b"")
    with pytest.raises(OSError):
        plugin.read()
    status = plugin.status()
    assert status["error"] == "router API refused: HTTP 404"
    assert status["last_ok_ms"] == ctx.clock.now_ms() - 5_000
    assert status["target"] == "192.0.2.1"


def test_the_status_route() -> None:
    plugin, _, _ = make_plugin()
    plugin.read()
    app = FastAPI()
    app.include_router(plugin.router())
    body = TestClient(app).get("/status").json()
    assert set(body) == {"target", "last_ok_ms", "error"}
    assert body["target"] == "192.0.2.1"


# ---- Review focus 1: a gateway that is not a Starlink router, or answers garbage


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ((404, {}, b"not found"), OSError),
        (ConnectionRefusedError("refused"), OSError),
        ((200, {"grpc-status": "12"}, b""), OSError),
        ((200, {}, default_response()[:30]), ValueError),
    ],
)
def test_a_router_that_is_not_one_makes_read_raise_a_readable_error(
    reply: Reply | BaseException, error: type[Exception]
) -> None:
    plugin, _, _ = make_plugin(FakePost(reply))
    with pytest.raises(error):
        plugin.read()


class Flaky(Plugin):
    """Another plugin's job, to show one plugin's failures stop nothing else."""

    manifest = PluginManifest(
        id="flaky",
        name="Flaky",
        version="1.0.0",
        description="Counts its runs",
        sdk_version=">=1.0,<2",
        capabilities=frozenset({Capability.JOBS}),
        permissions=frozenset(),
    )
    runs = 0

    def setup(self, ctx: PluginContext) -> None:
        return None

    def jobs(self) -> list[JobSpec]:
        def tick() -> None:
            type(self).runs += 1

        return [JobSpec("tick", 0.05, tick)]


def test_a_failing_router_backs_off_through_the_real_scheduler_and_other_jobs_keep_running(
    env: HostEnv,
) -> None:
    class StarlinkWith404(StarlinkPlugin):
        def __init__(self) -> None:
            super().__init__()
            self.post = FakePost((404, {}, b""))

    Flaky.runs = 0
    clock = FakeClock()

    def now_ms() -> int:
        return int(time.time() * 1000)

    clock.now_ms = now_ms  # type: ignore[method-assign]
    scheduler = AsyncScheduler(clock)

    def poller(plugin_id: str, capability: Capability, provider: Any) -> JobSpec | None:
        if capability is Capability.TRAFFIC:
            return JobSpec("poll.traffic", 0.05, lambda: list(provider.read()), timeout_s=5)
        return None

    env.scheduler = scheduler  # type: ignore[assignment]
    host = env.host([StarlinkWith404, Flaky], seeds={"starlink": {"router": "192.0.2.1"}}, poller=poller)

    async def scenario() -> tuple[Any, int]:
        host.load_all()
        assert host.get("starlink").state == "active"
        host.start_jobs()
        await scheduler.start()
        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            status = next(s for s in scheduler.status() if (s.owner, s.name) == ("starlink", "poll.traffic"))
            if status.consecutive_failures >= 3 and status.next_run_ms is not None:
                break
        await scheduler.stop()
        return status, Flaky.runs

    status, flaky_runs = asyncio.run(scenario())
    assert status is not None
    assert status.consecutive_failures >= 3
    assert status.last_ok is False
    assert status.last_error == "OSError: router API refused: HTTP 404"
    # from the third failure the gap to the next run grows beyond the 0.05 s interval
    assert status.next_run_ms is not None and status.last_finished_ms is not None
    assert status.next_run_ms - status.last_finished_ms >= 90
    assert flaky_runs >= 3


# ---- storage: baselines after a restart, and the fence


@pytest.fixture
def real(env: HostEnv) -> tuple[StarlinkPlugin, DefaultPluginContext, FakePost, FakeClock]:
    """The plugin on a real plugin context: its own migrated table behind the write fence."""
    plugin = StarlinkPlugin()
    upgrade_plugin(env.engine, "starlink", plugin.storage().versions_dir)  # type: ignore[union-attr]
    clock = FakeClock()
    from unittest.mock import MagicMock

    core = MagicMock()
    core.host.return_value.gateway = "192.0.2.1"
    core.device_by_ip.return_value = None
    ctx = DefaultPluginContext(
        "starlink",
        StarlinkSettings(),
        env.engine,
        clock,
        FakeNetworkTools(),
        FakeVendors(),
        InMemoryMetrics(),
        core,
        RecordingEventBus(),
        FakeServiceProbes(),
        FakeSystemInfo(),
    )
    plugin.settings = ctx.settings
    post = FakePost(ok(response([client("192.0.2.20", name="TV", down=1000, up=500)])))
    plugin.post = post
    plugin.setup(ctx)
    return plugin, ctx, post, clock


def stored(ctx: DefaultPluginContext) -> list[Any]:
    with ctx.unit_of_work() as uow:
        return list(uow.session.execute(sa.select(counters).order_by(counters.c.ip)).all())


def seed_row(ctx: DefaultPluginContext, ip: str, down: int, up: int, t_ms: int) -> None:
    with ctx.unit_of_work() as uow:
        uow.session.execute(
            sa.insert(counters).values(ip=ip, name="TV", down_bytes=down, up_bytes=up, t_ms=t_ms)
        )
        uow.commit()


def test_each_successful_read_upserts_every_client(real: Any) -> None:
    plugin, ctx, post, clock = real
    plugin.read()
    rows = stored(ctx)
    assert [(r.ip, r.name, r.down_bytes, r.up_bytes, r.t_ms) for r in rows] == [
        ("192.0.2.20", "TV", 1000, 500, clock.now_ms())
    ]
    clock.advance(5000)
    post.reply = ok(response([client("192.0.2.20", name="TV", down=2000, up=900)]))
    plugin.read()
    [row] = stored(ctx)
    assert (row.down_bytes, row.up_bytes, row.t_ms) == (2000, 900, clock.now_ms())


def test_a_client_without_counters_is_listed_but_not_stored_and_gives_no_baseline(real: Any) -> None:
    plugin, ctx, post, clock = real
    post.reply = ok(
        response([client("192.0.2.40", name="Printer"), client("192.0.2.20", name="TV", down=1000, up=500)])
    )
    seed_row(ctx, "192.0.2.20", 400, 200, clock.now_ms() - 20_000)
    readings = list(plugin.read())
    assert [(r.ip, r.down_bytes) for r in readings] == [
        ("192.0.2.20", 400),
        ("192.0.2.40", None),
        ("192.0.2.20", 1000),
    ]
    assert [r.ip for r in stored(ctx)] == ["192.0.2.20"]


def test_a_young_row_with_lower_counters_gives_a_baseline_first(real: Any) -> None:
    plugin, ctx, _post, clock = real
    seed_row(ctx, "192.0.2.20", 400, 200, clock.now_ms() - 20_000)
    readings = list(plugin.read())
    assert [(r.ip, r.down_bytes, r.up_bytes, r.t_ms) for r in readings] == [
        ("192.0.2.20", 400, 200, clock.now_ms() - 20_000),
        ("192.0.2.20", 1000, 500, clock.now_ms()),
    ]


def test_an_old_row_gives_no_baseline(real: Any) -> None:
    plugin, ctx, _post, clock = real
    seed_row(ctx, "192.0.2.20", 400, 200, clock.now_ms() - 120_000)
    assert len(list(plugin.read())) == 1


def test_a_row_with_higher_counters_gives_no_baseline(real: Any) -> None:
    plugin, ctx, _post, clock = real
    seed_row(ctx, "192.0.2.20", 5000, 200, clock.now_ms() - 20_000)  # the router was reset
    assert len(list(plugin.read())) == 1


def test_a_baseline_is_given_only_on_the_first_successful_read(real: Any) -> None:
    plugin, ctx, _post, clock = real
    seed_row(ctx, "192.0.2.20", 400, 200, clock.now_ms() - 20_000)
    assert len(list(plugin.read())) == 2
    clock.advance(5000)
    assert len(list(plugin.read())) == 1


def test_a_failed_read_does_not_use_up_the_baseline(real: Any) -> None:
    plugin, ctx, post, clock = real
    seed_row(ctx, "192.0.2.20", 400, 200, clock.now_ms() - 20_000)
    good = post.reply
    post.reply = (404, {}, b"")
    with pytest.raises(OSError):
        plugin.read()
    post.reply = good
    clock.advance(1000)
    assert len(list(plugin.read())) == 2


def test_the_baseline_goes_through_the_real_ledger_to_a_rate_at_once(real: Any) -> None:
    from netview.application.usecases.traffic import TrafficLedger

    plugin, ctx, _post, clock = real
    seed_row(ctx, "192.0.2.20", 400, 200, clock.now_ms() - 20_000)
    ledger = TrafficLedger(InMemoryMetrics(), clock)
    ledger.record("starlink", plugin.read())
    [view] = ledger.views()
    assert view.down_bps == (1000 - 400) * 8 / 20
    assert view.up_bps == (500 - 200) * 8 / 20
    assert ledger.totals()[0].clients == 1  # baseline plus current reading is one client, not two


def test_rows_older_than_a_day_are_dropped(real: Any) -> None:
    plugin, ctx, _post, clock = real
    seed_row(ctx, "192.0.2.99", 1, 1, clock.now_ms() - 2 * 86_400_000)
    plugin.read()
    assert [r.ip for r in stored(ctx)] == ["192.0.2.20"]


def test_a_storage_failure_does_not_fail_the_read(real: Any) -> None:
    plugin, ctx, _post, _clock = real
    with ctx.unit_of_work() as uow:
        uow.session.execute(sa.text("DROP TABLE starlink_counters"))
        uow.commit()
    assert len(list(plugin.read())) == 1


def test_writes_go_only_to_the_plugins_own_table(real: Any) -> None:
    plugin, ctx, _post, _clock = real
    plugin.read()
    with ctx.unit_of_work() as uow, pytest.raises(Exception, match="not authorized"):
        uow.session.execute(
            sa.text(
                "INSERT INTO devices (key, ip, first_seen_ms, last_seen_ms, status) "
                "VALUES ('x', '1', 0, 0, 'up')"
            )
        )
    with ctx.unit_of_work() as uow, pytest.raises(Exception, match="not authorized"):
        uow.session.execute(sa.text("DELETE FROM devices"))
    with ctx.unit_of_work() as uow:  # its own table is open
        uow.session.execute(sa.text("DELETE FROM starlink_counters"))
        uow.commit()


def test_the_migration_creates_the_table_with_its_columns(env: HostEnv) -> None:
    plugin = StarlinkPlugin()
    spec = plugin.storage()
    assert spec is not None
    upgrade_plugin(env.engine, "starlink", spec.versions_dir)
    columns = {c["name"]: c for c in sa.inspect(env.engine).get_columns("starlink_counters")}
    assert list(columns) == ["ip", "name", "down_bytes", "up_bytes", "t_ms"]
    assert sa.inspect(env.engine).get_pk_constraint("starlink_counters")["constrained_columns"] == ["ip"]
    assert set(spec.metadata.tables) == {"starlink_counters"}


def test_it_loads_through_the_plugin_host_and_serves_its_status(env: HostEnv, tmp_path: Path) -> None:
    host = env.host([StarlinkPlugin])
    host.load_all()
    info = host.get("starlink")
    assert info.state == "active", info.error
    assert env.registry.providers(Capability.TRAFFIC)[0][0] == "starlink"


def test_end_to_end_through_the_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import netview.plugins.builtin.starlink.plugin as module
    from netview.bootstrap import build_container
    from netview.infrastructure.settings import AppSettings
    from netview.presentation.api.app import create_app

    monkeypatch.setattr(module, "_http_post", FakePost())
    container = build_container(
        AppSettings(data_dir=tmp_path, subnet="192.0.2.0/24", plugins={"starlink": {"router": "192.0.2.1"}})
    )
    try:
        owners = [owner for owner, _ in container.registry.providers(Capability.TRAFFIC)]
        assert "starlink" in owners
        provider = dict(container.registry.providers(Capability.TRAFFIC))["starlink"]
        assert [r.ip for r in provider.read()] == ["192.0.2.20", "192.0.2.21"]
        app = create_app(
            container.services, container.host.routers(), container.host.ui_contributions(), {"localhost"}
        )
        http = TestClient(app, base_url="http://localhost", headers={"X-Netview": "1"})
        body = http.get("/api/v1/plugins/starlink/status").json()
        assert body["target"] == "192.0.2.1"
        assert body["error"] == ""
        assert http.get("/plugins/starlink/static/ui.js").status_code == 200
    finally:
        container.host.shutdown()
        container.engine.dispose()
