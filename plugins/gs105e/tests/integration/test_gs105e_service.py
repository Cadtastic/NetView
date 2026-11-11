"""Service tests: the polling rules against a fake switch, a real plugin database and a fake core."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import netview_local_plugins.gs105e.service as service_module
import pytest
from netview_local_plugins.gs105e.analysis import (
    COUNTERS_RESET_TEXT,
    LOGIN_FAILED_TEXT,
    PAUSED_ANOTHER_LOGIN_TEXT,
    REACHABLE_TEXT,
    UNREACHABLE_TEXT,
)
from netview_local_plugins.gs105e.client import MalformedReply
from netview_local_plugins.gs105e.model import MirrorConfig
from netview_local_plugins.gs105e.plugin import Gs105ePlugin
from netview_local_plugins.gs105e.service import MASK, RELOGIN_WINDOW_MS, Gs105eService
from netview_local_plugins.gs105e.settings import Gs105eSettings
from netview_local_plugins.gs105e.storage import SwitchStore, storage_spec
from netview_local_plugins.gs105e.tools.fake_switch import FakeSwitch
from sqlalchemy import Engine

from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core, upgrade_plugin
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk import DeviceView, EventKind, Hint, NameClaim, TypeClaim
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeCore,
    FakeNetworkTools,
    FakePluginContext,
    FakeServiceProbes,
    FakeSnmpClient,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
    RecordingEventBus,
)

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fw-1.6.0.11"
HOST = "192.168.1.3"
STATS = "/portStatistics.cgi"


def device(key: str, ip: str, mac: str, name: str) -> DeviceView:
    return DeviceView(
        key=key,
        ip=ip,
        mac=mac,
        vendor="",
        nickname=None,
        device_name=name,
        name_source="",
        type="",
        hints=[],
        status="online",
        rtt_ms=1.0,
        ttl=64,
        first_seen_ms=0,
        last_seen_ms=0,
        is_new=False,
        is_self=False,
        watched=False,
        display_name=name,
    )


OTHER = device("dev-other", "192.168.1.10", "aa:bb:cc:00:00:01", "other")
SWITCH = device("dev-switch", HOST, "00:11:22:33:44:55", "switch")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(eng)
    upgrade_plugin(eng, "gs105e", storage_spec().versions_dir)
    yield eng
    eng.dispose()


def make_settings(password: str | None = "secret", **extra: Any) -> Gs105eSettings:
    return Gs105eSettings.model_validate({"password": password, "page_gap_ms": 0, **extra})


@dataclass
class World:
    service: Gs105eService
    switch: FakeSwitch
    core: FakeCore
    clock: FakeClock
    ctx: FakePluginContext
    store: SwitchStore
    calls: list[tuple[str, str]] = field(default_factory=list)

    def events(self, text: str | None = None) -> list[str]:
        return [t for _, t, _ in self.core.events if text is None or t == text]

    def logins(self) -> int:
        return self.switch.requests.count(("POST", "/login.cgi"))

    def set_settings(self, settings: Gs105eSettings) -> None:
        self.ctx.settings = settings
        self.service.settings_changed()


def build(
    engine: Engine,
    *,
    settings: Gs105eSettings | None = None,
    core: FakeCore | None = None,
    hook: Callable[[str, str], None] | None = None,
) -> World:
    real = DefaultPluginContext(
        "gs105e",
        None,
        engine,
        FakeClock(),
        FakeNetworkTools(),
        FakeVendors(),
        InMemoryMetrics(),
        None,  # type: ignore[arg-type]
        RecordingEventBus(),
        FakeServiceProbes(),
        FakeSystemInfo(),
        FakeSnmpClient([]),
    )
    switch = FakeSwitch(FIX)
    core = core or FakeCore([OTHER, SWITCH])
    clock = FakeClock()
    ctx = FakePluginContext(
        settings or make_settings(),
        snmp=FakeSnmpClient([]),
        core=core,
        uow_factory=real.unit_of_work,
        clock=clock,
        plugin_id="gs105e",
    )
    calls: list[tuple[str, str]] = []

    def counting(
        host: str,
        port: int,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        calls.append((method, path))  # every attempt, also while the fake is down
        if hook is not None:
            hook(method, path)
        return switch(host, port, method, path, body, headers, timeout_s)

    service = Gs105eService(ctx, lambda sid: SwitchStore(real.unit_of_work, sid), counting)
    return World(service, switch, core, clock, ctx, SwitchStore(real.unit_of_work, "gs105e"), calls)


@pytest.fixture
def world(engine: Engine) -> World:
    return build(engine)


def page(name: str) -> str:
    return (FIX / name).read_bytes().decode("utf-8", errors="replace")


def link_down_status() -> str:
    html = page("status.cgi").replace('value="Up" trans', 'value="Down" trans', 1)
    return html.replace('value="1000M"', 'value="No Speed"', 1)


def reset_stats() -> str:
    return re.sub(
        r'<input type="hidden" value="\d+">', '<input type="hidden" value="0">', page("portStatistics.cgi")
    )


def wait_idle(w: World) -> None:
    deadline = time.monotonic() + 10
    while w.service.summary()["polling"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not w.service.summary()["polling"]


# ---- polling basics --------------------------------------------------------------------------


def test_first_polls_are_a_baseline(world: World) -> None:
    world.service.poll_status()
    world.service.poll_config()
    assert world.events() == []
    info = world.service.summary()["switch"]
    assert info["name"] == "GS105E Switch"
    assert (info["dhcp"], info["ip"], info["mask"], info["gateway"]) == (
        False,
        "192.0.2.1",
        "255.255.255.0",
        "192.0.2.2",
    )
    names = [c for c in world.core.claims if isinstance(c, NameClaim)]
    types = [c for c in world.core.claims if isinstance(c, TypeClaim)]
    hints = [c for c in world.core.claims if isinstance(c, Hint)]
    assert names == [NameClaim("dev-switch", "GS105E Switch", "GS105E", 8, world.clock.now_ms())]
    assert [(t.key, t.type, t.reason, t.source) for t in types] == [
        ("dev-switch", "switch", "NETGEAR GS105E web interface", "GS105E")
    ]
    text = f"NETGEAR {info['product']} firmware {info['firmware']} serial {info['serial']}"
    assert hints == [Hint("dev-switch", text, "GS105E")]
    world.service.poll_status()
    world.service.poll_config()
    assert len(world.core.claims) == 3  # unchanged claims are not sent again


def test_claims_fall_back_to_the_switch_mac(engine: Engine) -> None:
    moved = replace(SWITCH, ip="192.168.1.99", mac="00:1B:2F:00:00:01")
    w = build(engine, core=FakeCore([OTHER, moved]))
    w.service.poll_config()
    assert w.core.claims == []  # neither the ip nor the mac matches
    mac = w.service.summary()["switch"]["mac"]
    w.core.devices_list = [OTHER, replace(moved, mac=mac.upper())]
    w.service.poll_status()
    assert {c.key for c in w.core.claims} == {"dev-switch"}


def test_link_down_event(world: World) -> None:
    world.service.poll_status()
    world.switch.override["/status.cgi"] = link_down_status()
    world.service.poll_status()
    assert world.core.events == [(EventKind.PLUGIN, "GS105E: port 1 link down", HOST)]


def test_rates_after_two_counter_polls(world: World) -> None:
    def bump() -> None:
        world.switch.override[STATS] = page("portStatistics.cgi").replace("1274934942", "1275934942")

    world.service.poll_status()
    world.service.poll_counters()
    assert world.service.ports()[0]["in_bps"] is None
    world.clock.advance(15_000)
    world.switch.tick = bump
    world.service.poll_counters()
    first = world.service.ports()[0]
    assert first["in_bps"] == pytest.approx(1_000_000 * 8 / 15)
    assert first["util_percent"] is not None
    assert world.store.samples(1, 0, world.clock.now_ms() + 1, "raw")
    assert world.service.samples(1, None, None, "raw")[0]["in_bps"] == pytest.approx(1_000_000 * 8 / 15)


def test_reboot_relogs_once_and_reports_reset(world: World) -> None:
    world.service.poll_status()
    world.service.poll_counters()
    assert world.logins() == 1
    world.switch.drop_sessions()
    world.switch.override[STATS] = reset_stats()
    world.clock.advance(15_000)
    world.service.poll_counters()
    assert world.logins() == 2
    assert world.events(COUNTERS_RESET_TEXT) == [COUNTERS_RESET_TEXT]
    assert world.store.samples(1, 0, world.clock.now_ms() + 1, "raw") == []
    assert world.service.ports()[0]["in_bps"] is None
    world.clock.advance(15_000)
    world.service.poll_counters()
    assert world.events(COUNTERS_RESET_TEXT) == [COUNTERS_RESET_TEXT]  # reported once, not again
    assert world.logins() == 2


def test_second_loss_within_window_pauses(world: World) -> None:
    world.service.poll_counters()
    world.switch.drop_sessions()
    world.clock.advance(15_000)
    world.service.poll_counters()
    assert world.logins() == 2
    world.switch.drop_sessions()
    world.clock.advance(15_000)
    world.service.poll_counters()
    summary = world.service.summary()
    assert summary["login"] == "paused"
    assert summary["pause_reason"] == "another_login"
    assert summary["paused_until_ms"] == world.clock.now_ms() + 15 * 60_000
    assert world.events(PAUSED_ANOTHER_LOGIN_TEXT) == [PAUSED_ANOTHER_LOGIN_TEXT]
    assert world.logins() == 2
    before = len(world.calls)
    for _ in range(3):
        world.clock.advance(60_000)
        world.service.poll_status()
        world.service.poll_counters()
        world.service.poll_config()
    assert len(world.calls) == before
    assert world.events(PAUSED_ANOTHER_LOGIN_TEXT) == [PAUSED_ANOTHER_LOGIN_TEXT]
    world.clock.advance(15 * 60_000)
    world.service.poll_counters()
    assert len(world.calls) > before
    assert world.service.summary()["login"] == "ok"


def test_loss_after_the_window_relogs_again(world: World) -> None:
    world.service.poll_counters()
    world.switch.drop_sessions()
    world.service.poll_counters()
    world.switch.drop_sessions()
    world.clock.advance(RELOGIN_WINDOW_MS + 1)
    world.service.poll_counters()
    assert world.logins() == 3
    assert world.service.summary()["login"] == "ok"
    assert world.events() == []


def test_wrong_password_logs_in_once(engine: Engine) -> None:
    w = build(engine, settings=make_settings("wrong"))
    for _ in range(4):
        w.service.poll_status()
        w.service.poll_config()
        w.clock.advance(15_000)
        w.service.poll_counters()
    w.service.poll_status()
    w.service.poll_config()
    assert w.logins() == 1
    assert w.events(LOGIN_FAILED_TEXT) == [LOGIN_FAILED_TEXT]
    assert w.service.summary()["login"] == "failed"
    assert w.service.start_poll_all() is False
    w.set_settings(make_settings("secret"))
    w.service.poll_status()
    assert w.logins() == 2
    assert w.service.summary()["login"] == "ok"
    assert w.service.ports()
    assert w.events(LOGIN_FAILED_TEXT) == [LOGIN_FAILED_TEXT]


def test_successful_test_connection_clears_the_stop(engine: Engine) -> None:
    w = build(engine, settings=make_settings("wrong"))
    w.service.poll_status()
    assert w.service.summary()["login"] == "failed"
    assert w.service.test_connection() == {"ok": "false", "error": "login refused"}
    w.switch.password = "wrong"  # the user fixed the password on the switch
    result = w.service.test_connection()
    assert result["ok"] == "true"
    assert result["product"]
    assert w.service.summary()["login"] == "ok"
    before = w.logins()
    w.service.poll_status()
    assert w.service.ports()
    assert w.logins() == before  # the tested session is reused


def test_test_connection_unconfigured_and_unreachable(engine: Engine) -> None:
    w = build(engine, settings=make_settings(None))
    assert w.service.test_connection() == {"ok": "false", "error": "not configured"}
    w.set_settings(make_settings("secret"))
    w.switch.down = True
    result = w.service.test_connection()
    assert result["ok"] == "false"
    assert "secret" not in json.dumps(result)


def test_unreachable_from_start(world: World) -> None:
    summary = world.service.summary()
    assert summary["reachable"] is None
    assert summary["switch"] is None
    assert summary["login"] == "unknown"
    world.switch.down = True
    world.service.poll_counters()
    world.service.poll_status()
    world.service.poll_config()
    summary = world.service.summary()
    assert summary["reachable"] is False
    assert world.events(UNREACHABLE_TEXT) == [UNREACHABLE_TEXT]
    assert set(summary["errors"]) == {"counters", "status", "config"}
    before = len(world.calls)
    world.service.poll_counters()
    world.service.poll_status()
    assert len(world.calls) == before  # inside the backoff window
    world.switch.down = False
    world.clock.advance(301_000)
    world.service.poll_counters()
    assert world.events(REACHABLE_TEXT) == [REACHABLE_TEXT]
    assert world.events(UNREACHABLE_TEXT) == [UNREACHABLE_TEXT]
    assert world.service.summary()["reachable"] is True
    assert "counters" not in world.service.summary()["errors"]


def test_backoff_grows_and_is_capped(world: World) -> None:
    world.switch.down = True
    world.service.poll_counters()
    gaps = []
    for _ in range(8):
        waited = 0
        before = len(world.calls)
        while len(world.calls) == before:
            world.clock.advance(5_000)
            waited += 5_000
            world.service.poll_counters()
        gaps.append(waited)
    assert gaps[:4] == [30_000, 60_000, 120_000, 240_000]  # interval 15 s * 2**failures
    assert gaps == sorted(gaps)
    assert max(gaps) == 300_000


def test_one_page_changed_others_continue(world: World) -> None:
    world.switch.override["/igmp.cgi"] = "<html></html>"
    world.service.poll_config()
    errors = world.service.summary()["errors"]
    assert "/igmp.cgi" in errors["config"]
    world.service.poll_status()
    world.service.poll_counters()
    assert set(world.service.summary()["errors"]) == {"config"}
    assert world.service.ports()
    assert "secret" not in json.dumps(world.service.summary())
    assert all("secret" not in text for text in world.events())
    world.calls.clear()
    world.service.poll_config()  # no backoff for a changed page
    assert world.calls
    del world.switch.override["/igmp.cgi"]
    world.service.poll_config()
    assert world.service.summary()["errors"] == {}


def test_errors_never_carry_the_password(engine: Engine) -> None:
    blown: list[bool] = []

    def explode(method: str, path: str) -> None:
        if not blown and path == "/status.cgi":
            blown.append(True)
            raise RuntimeError("the password secret leaked")

    w = build(engine, hook=explode)
    w.service.poll_status()
    assert w.service.summary()["errors"] == {"status": f"RuntimeError: the password {MASK} leaked"}
    assert "secret" not in json.dumps(w.service.summary())
    w.switch.down = True
    w.clock.advance(400_000)
    w.service.poll_counters()
    assert "secret" not in json.dumps(w.service.summary())
    assert all("secret" not in text for text in w.events())
    assert w.service._scrub("x secret y") == f"x {MASK} y"


def test_pause_logs_out_and_resume(world: World) -> None:
    world.service.poll_status()
    world.service.pause()
    assert world.calls[-1] == ("GET", "/logout.cgi")
    summary = world.service.summary()
    assert summary["login"] == "paused"
    assert summary["pause_reason"] == "user"
    assert summary["paused_until_ms"] == world.clock.now_ms() + 15 * 60_000
    before = len(world.calls)
    world.clock.advance(60_000)
    world.service.poll_status()
    world.service.poll_counters()
    world.service.poll_config()
    assert len(world.calls) == before
    world.service.resume()
    assert world.service.summary()["pause_reason"] is None
    world.service.poll_status()
    assert len(world.calls) > before
    assert world.service.summary()["login"] == "ok"


def test_snapshot_survives_restart(engine: Engine) -> None:
    first = build(engine)
    first.service.poll_status()
    first.service.poll_config()
    second = build(engine)
    assert second.service.summary()["switch"] is not None
    second.service.poll_status()
    assert second.events() == []
    third = build(engine)
    third.switch.override["/status.cgi"] = link_down_status()
    third.service.poll_status()
    assert third.events() == ["GS105E: port 1 link down"]


# ---- poll_block_reason and start_poll_all ----------------------------------------------------


def test_block_reason_not_configured(engine: Engine) -> None:
    w = build(engine, settings=make_settings(None))
    assert w.service.poll_block_reason() == "not configured"
    assert w.service.start_poll_all() is False
    w.service.poll_status()
    assert w.calls == []
    assert w.service.summary()["login"] == "not_configured"
    assert w.service.summary()["configured"] is False


def test_block_reason_login_failed(engine: Engine) -> None:
    w = build(engine, settings=make_settings("wrong"))
    assert w.service.poll_block_reason() is None
    w.service.poll_status()
    assert w.service.poll_block_reason() == "login failed; press Test connection"
    w.service.pause()
    assert w.service.poll_block_reason() == "login failed; press Test connection"  # checked before paused
    assert w.service.start_poll_all() is False


def test_block_reason_paused(world: World) -> None:
    assert world.service.poll_block_reason() is None
    world.service.pause()
    assert world.service.poll_block_reason() == "polling is paused"
    assert world.service.start_poll_all() is False
    world.service.resume()
    assert world.service.poll_block_reason() is None


def test_block_reason_clears_when_the_pause_runs_out(world: World) -> None:
    world.service.pause()
    world.clock.advance(15 * 60_000)
    assert world.service.poll_block_reason() is None


def test_start_poll_all_runs_every_group_in_the_background(world: World) -> None:
    assert world.service.start_poll_all() is True
    wait_idle(world)
    assert world.service.ports()
    assert world.service.config()["vlans"] is not None
    assert world.service.ports()[0]["crc_errors"] is not None
    assert world.service.summary()["last_poll_ms"] == world.clock.now_ms()


def test_start_poll_all_is_false_while_running(world: World) -> None:
    with world.service._lock:
        assert world.service.poll_block_reason() is None  # busy is not a block reason
        assert world.service.start_poll_all() is False
        assert world.service.summary()["polling"] is True


def test_start_poll_all_ignores_backoff(world: World) -> None:
    world.switch.down = True
    world.service.poll_status()
    world.switch.down = False
    assert world.service.start_poll_all() is True
    wait_idle(world)
    assert world.service.summary()["reachable"] is True
    assert world.events(REACHABLE_TEXT) == [REACHABLE_TEXT]


# ---- concurrency, settings, shutdown ---------------------------------------------------------


def test_requests_never_overlap(engine: Engine) -> None:
    active = [0]
    peak = [0]
    guard = threading.Lock()

    def slow(method: str, path: str) -> None:
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.002)
        with guard:
            active[0] -= 1

    w = build(engine, hook=slow)
    threads = [
        threading.Thread(target=fn)
        for fn in (w.service.poll_status, w.service.poll_counters, w.service.poll_config)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert peak[0] == 1
    assert w.logins() == 1
    assert w.service.ports()
    assert w.service.config()["igmp"] is not None


def test_settings_changed_logs_out_only_when_the_connection_changed(world: World) -> None:
    world.service.poll_status()
    before = len(world.calls)
    world.set_settings(make_settings("secret", counters_interval_s=30))
    assert len(world.calls) == before
    world.set_settings(make_settings("other"))
    assert world.calls[-1] == ("GET", "/logout.cgi")
    assert world.service.summary()["login"] == "unknown"


def test_shutdown_logs_out(world: World) -> None:
    world.service.poll_status()
    world.service.shutdown()
    assert world.calls[-1] == ("GET", "/logout.cgi")
    n = len(world.calls)
    world.service.shutdown()
    assert len(world.calls) == n


def test_prune_touches_only_storage(world: World) -> None:
    world.service.prune()
    assert world.calls == []


# ---- read models -----------------------------------------------------------------------------


def test_summary_shape(world: World) -> None:
    world.service.poll_status()
    world.service.poll_config()
    world.service.poll_counters()
    s = world.service.summary()
    assert set(s) == {
        "configured",
        "host",
        "reachable",
        "polling",
        "login",
        "paused_until_ms",
        "pause_reason",
        "last_poll_ms",
        "errors",
        "switch",
        "ports",
        "throughput_bps",
    }
    assert s["configured"] is True
    assert s["host"] == HOST
    assert s["reachable"] is True
    assert s["polling"] is False
    assert s["login"] == "ok"
    assert s["paused_until_ms"] is None
    assert set(s["switch"]) == {
        "name",
        "product",
        "firmware",
        "firmware_tested",
        "serial",
        "mac",
        "bootloader",
        "dhcp",
        "ip",
        "mask",
        "gateway",
    }
    assert s["switch"]["firmware_tested"] is True
    assert s["ports"]["total"] == 5
    assert s["ports"]["up"] == sum(1 for p in world.service.ports() if p["up"])
    assert set(s["throughput_bps"]) == {"in", "out"}
    json.dumps(s)


def test_ports_shape(world: World) -> None:
    assert world.service.ports() == []
    assert world.service.port(1) is None
    world.service.poll_status()
    world.service.poll_config()
    world.service.poll_counters()
    ports = world.service.ports()
    assert [p["port"] for p in ports] == [1, 2, 3, 4, 5]
    one = ports[0]
    for key in (
        "port",
        "description",
        "up",
        "speed_setting",
        "link_mbps",
        "flow_control",
        "max_mtu",
        "in_bps",
        "out_bps",
        "util_percent",
        "crc_errors",
        "crc_delta",
        "pvid",
        "vlan_member",
        "ingress_kbps",
        "egress_kbps",
        "mirror",
    ):
        assert key in one
    assert one["pvid"] == 1
    assert one["vlan_member"] == "U"
    assert one["mirror"] is None
    assert one["ingress_kbps"] is None
    assert one["crc_errors"] == 0
    assert world.service.port(3) == ports[2]
    assert world.service.port(9) is None
    json.dumps(ports)


def test_ports_mirror_roles(world: World) -> None:
    world.service.poll_status()
    world.service.poll_config()
    current = world.service._current
    assert current is not None
    world.service._current = replace(current, mirror=MirrorConfig(True, 5, (1, 2)))
    assert [p["mirror"] for p in world.service.ports()] == ["source", "source", None, None, "destination"]
    world.service._current = replace(current, mirror=MirrorConfig(False, 5, (1, 2)))
    assert [p["mirror"] for p in world.service.ports()] == [None] * 5


def test_samples_default_windows(world: World) -> None:
    world.service.poll_status()
    world.service.poll_counters()
    world.clock.advance(15_000)
    world.service.poll_counters()
    now = world.clock.now_ms()
    assert world.service.samples(1, None, None, "5m") == []
    assert len(world.service.samples(1, now - 1, now, "raw")) == 1
    assert world.service.samples(1, None, None, "raw") != []
    world.clock.advance(2 * 3_600_000)
    assert world.service.samples(1, None, None, "raw") == []  # the default raw window is the last hour


def test_config_dict(world: World) -> None:
    assert world.service.config() == {
        "vlans": None,
        "qos": None,
        "igmp": None,
        "mirror": None,
        "management": None,
    }
    world.service.poll_config()
    config = world.service.config()
    assert list(config) == ["vlans", "qos", "igmp", "mirror", "management"]
    assert config["vlans"]["mode"] == "off"
    assert all(isinstance(v, dict) for v in config.values())
    json.dumps(config)


def test_own_ip_is_validated(world: World) -> None:
    class Core(FakeCore):
        def __init__(self, ip: object) -> None:
            super().__init__([SWITCH])
            self.ip = ip

        def host(self) -> Any:
            if isinstance(self.ip, Exception):
                raise self.ip
            return SimpleNamespace(ip=self.ip)

    assert world.service._own_ip() is None  # FakeCore has no host()
    for value, expected in (
        ("192.168.1.9", "192.168.1.9"),
        ("not an address", None),
        ("fe80::1", None),
        ("", None),
        (None, None),
        (RuntimeError("no host"), None),
    ):
        world.ctx.core = Core(value)
        assert world.service._own_ip() == expected


# ---- the plugin wiring -----------------------------------------------------------------------


def plugin_with(
    engine: Engine, settings: Gs105eSettings
) -> tuple[Gs105ePlugin, FakePluginContext, FakeSwitch]:
    w = build(engine, settings=settings)
    plugin = Gs105ePlugin()
    plugin.fetch = w.switch
    plugin.setup(w.ctx)
    return plugin, w.ctx, w.switch


def test_jobs_when_configured(engine: Engine) -> None:
    plugin, _, _ = plugin_with(engine, make_settings(counters_interval_s=20, status_interval_s=40))
    jobs = {j.name: j for j in plugin.jobs()}
    assert list(jobs) == ["counters", "status", "config", "prune"]
    assert [(j.interval_s, j.initial_delay_s, j.timeout_s) for j in list(jobs.values())[:3]] == [
        (20, 2, 40),
        (40, 5, 80),
        (300, 8, 120),
    ]
    assert jobs["prune"].interval_s == 300  # rolls up each closed 5-minute bucket, so the charts are current


def test_jobs_without_a_password_are_prune_only(engine: Engine) -> None:
    plugin, _, switch = plugin_with(engine, make_settings(None))
    assert [j.name for j in plugin.jobs()] == ["prune"]
    plugin.shutdown()
    assert switch.requests == []


def test_plugin_settings_changed_and_shutdown(engine: Engine) -> None:
    plugin, ctx, switch = plugin_with(engine, make_settings())
    jobs = {j.name: j for j in plugin.jobs()}
    jobs["status"].run()
    assert ("POST", "/login.cgi") in switch.requests
    new = make_settings("other")
    ctx.settings = new
    plugin.on_settings_changed(new)
    assert plugin.settings is new
    assert switch.requests[-1] == ("GET", "/logout.cgi")
    jobs["status"].run()  # the old job object still runs against the live settings
    plugin.shutdown()


# ---- pause and settings changes while a poll is running --------------------------------------


class Held:
    """A fetch hook that blocks the first request for ``path`` until the test lets it go."""

    def __init__(self, path: str, before: Callable[[], None] | None = None) -> None:
        self.path = path
        self.before = before
        self.entered = threading.Event()
        self.release = threading.Event()
        self._done = False

    def __call__(self, method: str, path: str) -> None:
        if path != self.path or self._done:
            return
        self._done = True
        if self.before is not None:
            self.before()
        self.entered.set()
        assert self.release.wait(10)


def start_held_config_poll(w: World, held: Held) -> threading.Thread:
    thread = threading.Thread(target=w.service.poll_config)
    thread.start()
    assert held.entered.wait(10)
    return thread


def finish(held: Held, thread: threading.Thread) -> None:
    held.release.set()
    thread.join(10)
    assert not thread.is_alive()


@pytest.fixture
def short_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "_LOCK_WAIT_S", 0.05)


def test_pause_stops_a_running_poll_and_logs_out(engine: Engine, short_wait: None) -> None:
    held = Held("/igmp.cgi")
    w = build(engine, hook=held)
    thread = start_held_config_poll(w, held)
    started = time.monotonic()
    w.service.pause()
    assert time.monotonic() - started < 2
    finish(held, thread)
    assert w.logins() == 1
    assert w.calls[-2:] == [("GET", "/igmp.cgi"), ("GET", "/logout.cgi")]  # no page after the pause
    assert w.service.summary()["login"] == "paused"
    assert w.service.summary()["errors"] == {}


def test_no_relogin_after_a_loss_while_paused(engine: Engine, short_wait: None) -> None:
    holder: list[World] = []
    held = Held("/igmp.cgi", before=lambda: holder[0].switch.drop_sessions())
    w = build(engine, hook=held)
    holder.append(w)
    thread = start_held_config_poll(w, held)
    w.service.pause()
    finish(held, thread)
    assert w.logins() == 1
    assert w.calls[-1] == ("GET", "/igmp.cgi")  # the lost session is not logged into again
    assert w.service.summary()["login"] == "paused"
    assert w.events() == []


def test_settings_changed_does_not_wait_for_a_running_poll(engine: Engine, short_wait: None) -> None:
    held = Held("/igmp.cgi")
    w = build(engine, hook=held)
    thread = start_held_config_poll(w, held)
    w.switch.password = "other"
    started = time.monotonic()
    w.set_settings(make_settings("other"))
    assert time.monotonic() - started < 2
    finish(held, thread)
    assert w.calls[-1] == ("GET", "/logout.cgi")  # the old session was dropped by the poll's end
    assert w.service.summary()["errors"] == {}
    w.service.poll_status()
    assert w.logins() == 2
    assert w.service.summary()["login"] == "ok"
    assert w.service.ports()


def test_a_pause_set_after_the_gate_is_kept(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "_LOCK_WAIT_S", 0.05)
    real = world.service.poll_block_reason
    fired: list[bool] = []

    def late_pause() -> str | None:
        reason = real()
        if not fired:
            fired.append(True)
            world.service.pause()  # lands between the gate check and the expiry check
        return reason

    monkeypatch.setattr(world.service, "poll_block_reason", late_pause)
    world.service.poll_status()
    assert world.service.summary()["login"] == "paused"
    assert world.calls == []


def test_test_connection_scrubs_unexpected_errors(engine: Engine) -> None:
    def explode(method: str, path: str) -> None:
        raise RuntimeError("the password secret leaked")

    w = build(engine, hook=explode)
    result = w.service.test_connection()
    assert result["ok"] == "false"
    assert "secret" not in result["error"]
    assert MASK in result["error"]
    assert w.service.test_connection()["ok"] == "false"  # the bypass flag was reset


# ---- final review fixes ----------------------------------------------------------------------


def posts(w: World) -> int:
    return w.calls.count(("POST", "/login.cgi"))


def _breaking_login(error: Exception) -> Callable[[str, str], None]:
    def hook(method: str, path: str) -> None:
        if method == "POST" and path == "/login.cgi":
            raise error

    return hook


@pytest.mark.parametrize("error", [MalformedReply("bad gzip body"), RuntimeError("boom")])
def test_a_login_that_fails_after_the_post_backs_off(engine: Engine, error: Exception) -> None:
    w = build(engine, hook=_breaking_login(error))

    def tick() -> None:
        w.service.poll_counters()
        w.service.poll_status()
        w.service.poll_config()

    for _ in range(6):  # 25 s in 5 s steps: inside the first backoff window (30 s)
        tick()
        w.clock.advance(5_000)
    assert posts(w) == 1
    assert w.service.summary()["login"] != "failed"  # not a refused password
    w.clock.advance(10_000)
    tick()
    assert posts(w) == 2
    for _ in range(4):
        w.clock.advance(5_000)
        tick()
    assert posts(w) == 2  # the second failure doubles the wait


def test_a_page_that_fails_to_read_while_logged_in_does_not_back_off(world: World) -> None:
    world.switch.override["/igmp.cgi"] = "<html></html>"
    world.service.poll_config()
    world.calls.clear()
    world.service.poll_config()
    assert world.calls
    assert world.logins() == 1  # the one login of the first poll; the retry reused the session


def test_counters_in_a_closed_bucket_reach_the_5m_series_at_the_next_prune(world: World) -> None:
    world.service.poll_status()
    world.service.poll_counters()
    world.clock.advance(15_000)
    world.service.poll_counters()
    assert world.service.samples(1, None, None, "5m") == []
    world.clock.advance(300_000)  # the bucket is complete
    world.service.prune()
    assert len(world.service.samples(1, None, None, "5m")) == 1


def _rates_live(world: World) -> None:
    world.service.poll_status()
    world.service.poll_counters()
    world.clock.advance(15_000)
    world.service.poll_counters()
    assert world.service.ports()[0]["in_bps"] is not None


def test_rates_go_blank_when_the_switch_stops_answering(world: World) -> None:
    _rates_live(world)
    world.switch.down = True
    world.clock.advance(15_000)
    world.service.poll_counters()
    assert world.service.ports()[0]["in_bps"] is None
    assert world.service.summary()["throughput_bps"] == {"in": 0, "out": 0}


def test_rates_go_blank_on_pause(world: World) -> None:
    _rates_live(world)
    world.service.pause()
    assert world.service.ports()[0]["in_bps"] is None
    assert world.service.summary()["throughput_bps"] == {"in": 0, "out": 0}


def test_rates_go_blank_when_the_login_is_stopped(engine: Engine) -> None:
    w = build(engine)
    _rates_live(w)
    w.switch.password = "changed"  # the next login is refused
    w.switch.drop_sessions()
    w.clock.advance(15_000)
    w.service.poll_counters()
    w.clock.advance(15_000)
    w.service.poll_counters()
    assert w.service.summary()["login"] == "failed"
    assert w.service.ports()[0]["in_bps"] is None


def test_a_port_outside_the_shown_vlan_is_not_a_member(world: World) -> None:
    world.service.poll_status()
    world.service.poll_config()
    current = world.service._current
    assert current is not None and current.vlans is not None and current.vlans.shown is not None
    shown = replace(current.vlans.shown, members=("U", "", "T", "", ""))
    world.service._current = replace(current, vlans=replace(current.vlans, shown=shown))
    assert [p["vlan_member"] for p in world.service.ports()] == ["U", "", "T", "", ""]
    world.service._current = replace(current, vlans=replace(current.vlans, shown=None))
    assert [p["vlan_member"] for p in world.service.ports()] == [None] * 5
