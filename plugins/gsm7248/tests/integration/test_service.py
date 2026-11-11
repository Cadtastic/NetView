from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from netview_local_plugins.gsm7248 import mibs
from netview_local_plugins.gsm7248.analysis import REACHABLE_TEXT, UNREACHABLE_TEXT
from netview_local_plugins.gsm7248.collector import Collector
from netview_local_plugins.gsm7248.plugin import Gsm7248Plugin
from netview_local_plugins.gsm7248.service import Gsm7248Service
from netview_local_plugins.gsm7248.settings import Gsm7248Settings
from netview_local_plugins.gsm7248.storage import SwitchStore, storage_spec
from sqlalchemy import Engine

from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core, upgrade_plugin
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk import DeviceView, EventKind, Hint, NameClaim, SnmpAuthError, SnmpTimeout, TypeClaim
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

WALK = Path(__file__).resolve().parents[1] / "fixtures" / "walk_basic.txt"
PROXMOX_MAC = "b8:ca:3a:67:7d:ef"
SWITCH_MAC = "00:1b:2f:c2:dc:75"
HC_IN_5 = (*mibs.IF_X_TABLE, 6, 5)
HC_OUT_5 = (*mibs.IF_X_TABLE, 10, 5)
OUI = {"bc:24:11:00:00:01": "Proxmox Server Solutions"}


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


PROXMOX = device("dev-proxmox", "192.168.1.10", PROXMOX_MAC, "proxmox")
SWITCH = device("dev-switch", "192.168.1.4", SWITCH_MAC, "switch")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(eng)
    upgrade_plugin(eng, "gsm7248", storage_spec().versions_dir)
    yield eng
    eng.dispose()


@dataclass
class World:
    service: Gsm7248Service
    snmp: FakeSnmpClient
    core: FakeCore
    clock: FakeClock
    ctx: FakePluginContext
    store: SwitchStore

    def events(self, text: str | None = None) -> list[str]:
        return [t for _, t, _ in self.core.events if text is None or t == text]


def settings_2c(**extra: Any) -> Gsm7248Settings:
    return Gsm7248Settings(snmp_version="2c", community="s3cr3t", **extra)


def build(
    engine: Engine,
    *,
    settings: Gsm7248Settings | None = None,
    devices: list[DeviceView] | None = None,
    snmp: FakeSnmpClient | None = None,
    core: FakeCore | None = None,
    clock: FakeClock | None = None,
) -> World:
    real = DefaultPluginContext(
        "gsm7248",
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
    snmp = snmp or FakeSnmpClient.from_walk_file(WALK)
    core = core or FakeCore([PROXMOX, SWITCH] if devices is None else devices)
    clock = clock or FakeClock()
    ctx = FakePluginContext(
        settings or settings_2c(),
        snmp=snmp,
        core=core,
        uow_factory=real.unit_of_work,
        clock=clock,
        plugin_id="gsm7248",
    )
    ctx.vendors = FakeVendors(OUI)
    store = SwitchStore(real.unit_of_work, "gsm7248")
    service = Gsm7248Service(
        ctx, lambda switch_id: SwitchStore(real.unit_of_work, switch_id), Collector(snmp)
    )
    return World(service, snmp, core, clock, ctx, store)


@pytest.fixture
def world(engine: Engine) -> World:
    return build(engine)


def poll_everything(w: World) -> None:
    assert w.service.poll_all() is True


def test_status_poll_claims_switch_name_type_hint(world: World) -> None:
    world.service.poll_status()
    claims = world.core.claims
    names = [c for c in claims if isinstance(c, NameClaim)]
    types = [c for c in claims if isinstance(c, TypeClaim)]
    assert names == [NameClaim("dev-switch", "GSM7248", "GSM7248", 8, world.clock.now_ms())]
    assert [(t.key, t.type, t.source) for t in types] == [("dev-switch", "switch", "GSM7248")]
    assert "1.3.6.1.4.1.4526" in types[0].reason
    assert not [c for c in claims if isinstance(c, Hint)]  # inventory arrives with the topology poll


def test_inventory_hint_follows_topology_poll(world: World) -> None:
    world.service.poll_status()
    world.service.poll_topology()
    world.service.poll_status()
    hints = [c for c in world.core.claims if isinstance(c, Hint) and c.key == "dev-switch"]
    assert len(hints) == 1
    assert hints[0].source == "GSM7248"
    assert hints[0].text.startswith("NETGEAR ")
    assert "firmware" in hints[0].text


def test_concurrent_polls_are_serialised(world: World) -> None:
    errors: list[BaseException] = []

    def run(fn: Any) -> None:
        try:
            fn()
        except BaseException as exc:  # reported by the assertion below
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(world.service.poll_status,)),
        threading.Thread(target=run, args=(world.service.poll_bridge,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert errors == []
    saved = world.store.load_snapshot()
    assert saved is not None
    assert {"status", "bridge"} <= saved.groups
    assert saved.ports
    assert saved.macs


def test_poll_all_returns_false_while_running(world: World) -> None:
    entered = threading.Event()
    release = threading.Event()
    real_walk = world.snmp.walk

    def slow_walk(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        release.wait(5)
        return real_walk(*args, **kwargs)

    world.snmp.walk = slow_walk  # type: ignore[method-assign]
    result: list[bool] = []
    t = threading.Thread(target=lambda: result.append(world.service.poll_all()))
    t.start()
    assert entered.wait(5)
    assert world.service.summary()["polling"] is True
    assert world.service.poll_all() is False
    assert world.service.start_poll_all() is False
    release.set()
    t.join(10)
    assert result == [True]
    assert world.service.summary()["polling"] is False
    assert world.service.poll_all() is True


def test_bridge_poll_hints_device_port(world: World) -> None:
    world.service.poll_status()
    world.service.poll_bridge()
    hints = [c for c in world.core.claims if isinstance(c, Hint) and c.key == "dev-proxmox"]
    assert hints == [Hint("dev-proxmox", "on GSM7248 port 0/5 (VLAN 1)", "GSM7248")]


def test_device_behind_uplink_gets_uplink_hint(engine: Engine) -> None:
    w = build(engine, settings=settings_2c(uplink_ports=["0/5"]))
    w.service.poll_status()
    w.service.poll_bridge()
    hints = [c for c in w.core.claims if isinstance(c, Hint) and c.key == "dev-proxmox"]
    assert hints == [Hint("dev-proxmox", "via GSM7248 uplink 0/5", "GSM7248")]


def test_counters_then_rates(world: World) -> None:
    world.service.poll_status()
    world.service.poll_counters()
    entry = next(p for p in world.service.ports() if p["name"] == "0/5")
    assert entry["rates"] is None
    world.snmp.rows[HC_IN_5] = 5_000_000_005 + 1_500_000
    world.snmp.rows[HC_OUT_5] = int(world.snmp.rows[HC_OUT_5]) + 3_000_000  # type: ignore[arg-type]
    world.clock.advance(15_000)
    world.service.poll_counters()
    entry = next(p for p in world.service.ports() if p["name"] == "0/5")
    assert entry["rates"] is not None
    assert entry["rates"]["in_bps"] == pytest.approx(800_000)
    assert entry["rates"]["out_bps"] == pytest.approx(1_600_000)
    assert world.store.samples(5, 0, world.clock.now_ms() + 1, "raw")


def test_reboot_drops_the_next_rates(world: World) -> None:
    world.service.poll_status()
    world.service.poll_counters()
    world.snmp.rows[mibs.SYS_UPTIME] = 100  # uptime went backwards
    world.clock.advance(15_000)
    world.service.poll_status()
    world.snmp.rows[HC_IN_5] = 5_000_000_005 + 1_500_000
    world.service.poll_counters()
    entry = next(p for p in world.service.ports() if p["name"] == "0/5")
    assert entry["rates"] is None
    assert any("restarted" in t for t in world.events())


def test_unreachable_emits_one_event_and_backs_off(world: World) -> None:
    world.snmp.fail_with = SnmpTimeout("no answer")
    world.service.poll_status()
    assert world.events(UNREACHABLE_TEXT) == [UNREACHABLE_TEXT]
    assert world.core.events[0][0] is EventKind.PLUGIN

    world.clock.advance(10 * 60_000)
    world.service.poll_status()  # backoff over: tries again, still down, no second event
    assert len(world.events(UNREACHABLE_TEXT)) == 1

    calls = len(world.snmp.calls)
    world.service.poll_status()  # inside the (doubled) backoff: no SNMP call at all
    assert len(world.snmp.calls) == calls
    summary = world.service.summary()
    assert summary["reachable"] is False
    assert summary["last_error"].startswith("SnmpTimeout")

    world.snmp.fail_with = None
    world.clock.advance(10 * 60_000)
    world.service.poll_status()
    assert world.events(REACHABLE_TEXT) == [REACHABLE_TEXT]
    assert world.service.summary()["reachable"] is True
    assert world.service.summary()["last_error"] is None


def test_one_failing_group_does_not_flap_reachability(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A walk that keeps timing out (say a slow ENTITY walk) while the status GET answers
    must not emit UNREACHABLE/REACHABLE pairs, and must build up its own backoff."""
    topology_calls: list[int] = []

    def slow_topology(target: Any, t_ms: int) -> Any:
        topology_calls.append(t_ms)
        raise SnmpTimeout("walk timed out")

    monkeypatch.setattr(world.service._collector, "topology", slow_topology)
    for _ in range(12):
        world.service.poll_status()
        world.service.poll_topology()
        world.clock.advance(30_000)

    assert world.events(UNREACHABLE_TEXT) == []
    assert world.events(REACHABLE_TEXT) == []
    summary = world.service.summary()
    assert summary["reachable"] is True
    assert summary["last_error"].startswith("SnmpTimeout")
    # backoff doubles from 600 s capped at 300 s: 1 try at t=0, then one every 300 s -> 2 in 6 minutes
    assert len(topology_calls) == 2


def test_non_timeout_error_reaches_summary(world: World) -> None:
    from netview.sdk import SnmpError

    world.snmp.fail_with = SnmpError("SNMP request failed: PySnmpError")
    world.service.poll_status()
    summary = world.service.summary()
    assert summary["reachable"] is None
    assert summary["last_error"] == "SnmpError: SNMP request failed: PySnmpError"


def test_unreachable_still_serves_last_snapshot(world: World) -> None:
    world.service.poll_status()
    world.snmp.fail_with = SnmpTimeout("no answer")
    world.clock.advance(60_000)
    world.service.poll_status()
    assert world.service.summary()["reachable"] is False
    assert any(p["name"] == "0/5" for p in world.service.ports())


def test_auth_error_message_has_no_secret(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    # even an adapter that echoed the secret must not get it through
    world.snmp.fail_with = SnmpAuthError("rejected key s3cr3t")
    world.service.poll_status()
    world.service.poll_counters()
    result = world.service.test_connection(world.ctx.settings.target())
    blob = " ".join(world.events()) + str(world.service.summary()) + caplog.text + str(result)
    assert "s3cr3t" not in blob
    assert world.service.summary()["last_error"].startswith("SnmpAuthError")
    assert result["ok"] == "false"
    assert result["error"].startswith("SnmpAuthError")


def test_restart_does_not_repeat_events(engine: Engine) -> None:
    first = build(engine)
    poll_everything(first)
    first.snmp.rows[HC_IN_5] = 6_000_000_000
    first.clock.advance(60_000)
    poll_everything(first)
    before = len(first.core.events)

    second = build(engine, core=first.core, snmp=first.snmp, clock=first.clock)
    first.clock.advance(60_000)
    poll_everything(second)
    assert len(second.core.events) == before


def test_first_bridge_poll_after_status_emits_nothing(world: World) -> None:
    world.service.poll_status()
    world.service.poll_bridge()
    assert world.core.events == []


def test_link_change_emits_event(world: World) -> None:
    world.service.poll_status()
    world.snmp.rows[(*mibs.IF_TABLE, 8, 5)] = 2
    world.clock.advance(30_000)
    world.service.poll_status()
    assert "GSM7248 port 0/5 link down" in world.events()


def test_mac_gone_event_carries_device_ip(world: World) -> None:
    world.service.poll_status()
    world.service.poll_bridge()
    mac_bytes = bytes.fromhex(PROXMOX_MAC.replace(":", ""))
    world.snmp.rows = {
        oid: v for oid, v in world.snmp.rows.items() if not (len(oid) > 6 and bytes(oid[-6:]) == mac_bytes)
    }
    world.clock.advance(60_000)
    world.service.poll_bridge()
    gone = [(t, ip) for _, t, ip in world.core.events if "left GSM7248 port" in t]
    assert gone == [(f"{PROXMOX_MAC} left GSM7248 port 0/5", "192.168.1.10")]


def test_not_configured_has_only_prune_job(engine: Engine) -> None:
    plugin = Gsm7248Plugin()
    w = build(engine, settings=Gsm7248Settings())
    plugin.settings = w.ctx.settings
    plugin.setup(w.ctx)  # type: ignore[arg-type]
    assert [j.name for j in plugin.jobs()] == ["prune"]
    assert w.service.summary()["configured"] is False
    w.service.poll_status()
    assert w.snmp.calls == []


def test_configured_plugin_jobs(engine: Engine) -> None:
    plugin = Gsm7248Plugin()
    w = build(engine)
    plugin.settings = w.ctx.settings
    plugin.setup(w.ctx)  # type: ignore[arg-type]
    jobs = {j.name: j for j in plugin.jobs()}
    assert set(jobs) == {"counters", "status", "bridge", "topology", "prune"}
    assert [jobs[n].interval_s for n in ("counters", "status", "bridge", "topology", "prune")] == [
        15,
        30,
        60,
        300,
        3600,
    ]
    assert [jobs[n].initial_delay_s for n in ("counters", "status", "bridge", "topology")] == [2, 5, 8, 11]
    assert jobs["counters"].timeout_s == 30
    assert jobs["topology"].timeout_s == 120  # 2 x 300 capped at 120


def test_claims_not_resent_when_unchanged(world: World) -> None:
    for _ in range(2):  # the second status poll adds the inventory hint
        world.service.poll_status()
        world.service.poll_topology()
        world.service.poll_bridge()
    first = list(world.core.claims)
    assert first
    for _ in range(2):
        world.clock.advance(60_000)
        world.service.poll_status()
        world.service.poll_topology()
        world.service.poll_bridge()
    assert world.core.claims == first


def test_changed_value_is_claimed_again(world: World) -> None:
    world.service.poll_status()
    n = len(world.core.claims)
    world.snmp.rows[mibs.SYS_NAME] = b"core-switch"
    world.service.poll_status()
    new = world.core.claims[n:]
    assert [c.name for c in new if isinstance(c, NameClaim)] == ["core-switch"]


def test_read_models(world: World) -> None:
    poll_everything(world)
    world.snmp.rows[HC_IN_5] = 5_000_000_005 + 1_500_000
    world.clock.advance(15_000)
    world.service.poll_counters()

    summary = world.service.summary()
    assert summary["configured"] is True
    assert summary["host"] == world.service.settings.host
    assert summary["reachable"] is True
    assert summary["switch"]["mac"] == SWITCH_MAC
    assert summary["ports"]["total"] >= 48
    assert summary["ports"]["up"] >= 1
    assert summary["throughput_bps"]["in"] > 0

    ports = world.service.ports()
    entry = next(p for p in ports if p["name"] == "0/5")
    assert set(entry) >= {
        "if_index",
        "name",
        "alias",
        "kind",
        "admin_up",
        "oper_up",
        "speed_mbps",
        "duplex",
        "pvid",
        "vlans",
        "stp_state",
        "lag",
        "uplink",
        "rates",
        "devices",
    }
    assert entry["pvid"] == 1
    assert 1 in entry["vlans"]["untagged"]
    assert entry["uplink"] is False
    devices = {d["mac"]: d for d in entry["devices"]}
    assert devices[PROXMOX_MAC]["device_key"] == "dev-proxmox"
    assert devices[PROXMOX_MAC]["ip"] == "192.168.1.10"
    assert devices[PROXMOX_MAC]["display_name"] == "proxmox"
    assert any(d["device_key"] is None for d in entry["devices"])

    one = world.service.port("0/5")
    assert one is not None
    assert "mac_history" in one
    assert world.service.port("9/9") is None

    macs = world.service.macs()
    unknown = [m for m in macs if m["device_key"] is None and m["status"] == "learned"]
    assert unknown
    assert all("vendor" in m for m in unknown)
    assert next(m for m in macs if m["mac"] == PROXMOX_MAC)["port"] == "0/5"

    vlans = world.service.vlans()
    assert vlans[0]["vid"] == 1
    assert "0/5" in vlans[0]["untagged"]

    series = world.service.samples("0/5", 0, world.clock.now_ms() + 1, "raw")
    assert series
    assert set(series[0]) >= {"t_ms", "in_bps", "out_bps"}
    assert world.service.samples("9/9", 0, 1, "raw") == []


def test_unknown_mac_vendor_comes_from_oui(engine: Engine) -> None:
    snmp = FakeSnmpClient.from_walk_file(WALK)
    snmp.rows[(*mibs.DOT1Q_TP_FDB_PORT, 1, 188, 36, 17, 0, 0, 1)] = 5
    snmp.rows[(*mibs.DOT1Q_TP_FDB_STATUS, 1, 188, 36, 17, 0, 0, 1)] = 3
    w = build(engine, snmp=snmp)
    w.service.poll_status()
    w.service.poll_bridge()
    guest = next(m for m in w.service.macs() if m["mac"] == "bc:24:11:00:00:01")
    assert guest["vendor"] == "Proxmox Server Solutions"
    assert guest["device_key"] is None


def test_test_connection_ok_and_error(world: World) -> None:
    target = world.ctx.settings.target()
    ok = world.service.test_connection(target)
    assert ok == {"ok": "true", "sys_descr": "GSM7248 L2 Managed Gigabit Switch"}
    world.snmp.fail_with = SnmpTimeout("no answer")
    bad = world.service.test_connection(target)
    assert bad == {"ok": "false", "error": "SnmpTimeout: no answer"}


def test_empty_view_is_reported_not_shown_as_blank_data(world: World) -> None:
    world.snmp.rows = {}  # the agent answers, but this community can read nothing
    world.service.poll_status()
    summary = world.service.summary()
    assert summary["reachable"] is not False  # it did answer
    assert summary["last_error"].startswith("SnmpEmptyView: ")
    assert "can read nothing" in summary["last_error"]
    assert world.events(UNREACHABLE_TEXT) == []


def test_test_connection_fails_on_an_empty_view(world: World) -> None:
    world.snmp.rows = {}
    result = world.service.test_connection(world.ctx.settings.target())
    assert result["ok"] == "false"
    assert result["error"].startswith("SnmpEmptyView: ")


def test_prune_removes_old_samples(world: World) -> None:
    world.service.poll_status()
    world.service.poll_counters()
    world.snmp.rows[HC_IN_5] = 5_000_000_005 + 1_500_000
    world.clock.advance(15_000)
    world.service.poll_counters()
    assert world.store.samples(5, 0, world.clock.now_ms() + 1, "raw")
    world.clock.advance(3 * 24 * 3_600_000)
    world.service.prune()
    assert world.store.samples(5, 0, world.clock.now_ms() + 1, "raw") == []
