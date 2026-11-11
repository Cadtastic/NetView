from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from netview_local_plugins.roku.discovery import ScanResult
from netview_local_plugins.roku.ecp import EcpClient, EcpResponse, parse_device_info
from netview_local_plugins.roku.model import SavedTv, ScanHit
from netview_local_plugins.roku.service import CommandError, DocumentError, RokuService, UnknownTv
from netview_local_plugins.roku.settings import RokuSettings

from netview.sdk.testing.fakes import FakeClock

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ON = (FIXTURES / "device-info-on.xml").read_text()
STANDBY = (FIXTURES / "device-info-standby.xml").read_text()
APPS = (FIXTURES / "apps.xml").read_bytes()
ACTIVE = (FIXTURES / "active-app-youtube.xml").read_bytes()


def _info(serial: str, name: str, power: str = "PowerOn") -> bytes:
    body = re.sub(r"<serial-number>.*?</serial-number>", f"<serial-number>{serial}</serial-number>", ON)
    body = re.sub(
        r"<user-device-name>.*?</user-device-name>", f"<user-device-name>{name}</user-device-name>", body
    )
    return re.sub(r"<power-mode>.*?</power-mode>", f"<power-mode>{power}</power-mode>", body).encode()


class FakeTv:
    def __init__(self, serial: str = "S1", name: str = "Living Room TV", power: str = "PowerOn") -> None:
        self.serial = serial
        self.name = name
        self.power = power
        self.answering = True
        self.limited_apps = False


class FakeTransport:
    def __init__(self) -> None:
        self.tvs: dict[str, FakeTv] = {}
        self.posts: list[str] = []
        self.gets: list[str] = []
        self.timeouts: list[float] = []
        self._lock = threading.Lock()

    def __call__(self, method: str, url: str, timeout_s: float) -> EcpResponse:
        match = re.match(r"http://([\d.]+):8060(/.*)$", url)
        assert match, url
        ip, path = match.groups()
        with self._lock:
            self.timeouts.append(timeout_s)
            (self.posts if method == "POST" else self.gets).append(f"{ip}{path}")
        tv = self.tvs.get(ip)
        if tv is None or not tv.answering:
            raise TimeoutError("timed out")
        if path == "/query/device-info":
            return EcpResponse(200, {}, _info(tv.serial, tv.name, tv.power))
        if path == "/query/active-app":
            return EcpResponse(200, {}, ACTIVE)
        if path == "/query/apps":
            return EcpResponse(403, {}, b"") if tv.limited_apps else EcpResponse(200, {}, APPS)
        if path.startswith("/query/icon/"):
            return EcpResponse(200, {"Content-Type": "image/png"}, b"PNG")
        return EcpResponse(200, {}, b"")


class MemStore:
    def __init__(self, tvs: list[SavedTv]) -> None:
        self.tvs = list(tvs)
        self._lock = threading.Lock()

    def load(self) -> list[SavedTv]:
        with self._lock:
            return list(self.tvs)

    def replace(self, tvs: list[SavedTv]) -> None:
        with self._lock:
            self.tvs = list(tvs)


def _saved(id: str = "a", ip: str = "192.168.1.60", serial: str = "S1", **kw: Any) -> SavedTv:
    base: dict[str, Any] = {
        "id": id, "serial": serial, "ip": ip, "name": "Living Room TV", "label": "", "model": "M",
        "location": "", "tv": True, "found_by": "ssdp", "first_seen": "t0", "last_seen": "t1",
    }  # fmt: skip
    base.update(kw)
    return SavedTv(**base)


class Rig:
    def __init__(self, tvs: list[SavedTv], scanner: Callable[..., ScanResult] | None = None) -> None:
        self.transport = FakeTransport()
        self.clock = FakeClock()
        self.store = MemStore(tvs)
        self.timers: list[tuple[float, Callable[[], None]]] = []
        self.probes = object()
        ctx = SimpleNamespace(
            settings=RokuSettings(),
            clock=self.clock,
            log=logging.getLogger("roku-test"),
            probes=self.probes,
            core=SimpleNamespace(host=lambda: SimpleNamespace(subnet="192.168.1.0/24")),
        )
        self.ecp = EcpClient(self.transport)
        kwargs: dict[str, Any] = {"timer": lambda d, f: self.timers.append((d, f))}
        args: list[Any] = [scanner] if scanner else []
        self.service = RokuService(ctx, self.store, self.ecp, *args, **kwargs)

    def status(self, tv_id: str = "a") -> dict[str, Any]:
        status: dict[str, Any] = next(t for t in self.service.list_tvs()["tvs"] if t["id"] == tv_id)["status"]
        return status


@pytest.fixture
def rig() -> Rig:
    r = Rig([_saved()])
    r.transport.tvs["192.168.1.60"] = FakeTv()
    return r


def test_never_polled_tv_has_default_status(rig: Rig) -> None:
    view = rig.service.list_tvs()["tvs"][0]
    assert view["title"] == "Living Room TV"
    assert view["status"]["reachable"] is False
    assert view["status"]["error"] == ""
    assert view["status"]["checked_at_ms"] is None
    assert rig.service.list_tvs()["scan"]["running"] is False


def test_poll_marks_on_tv_with_app_and_apps(rig: Rig) -> None:
    rig.service.poll_status()
    st = rig.status()
    assert st["reachable"] is True
    assert st["power"] == "on"
    assert st["active_app"]["id"] == "837"
    assert st["apps"] and set(st["apps"][0]) == {"id", "name", "type"}
    assert st["apps_refused"] is False
    assert st["checked_at_ms"] == rig.clock.now_ms()


def test_poll_standby_skips_active_app(rig: Rig) -> None:
    rig.transport.tvs["192.168.1.60"].power = "Ready"
    rig.service.poll_status()
    st = rig.status()
    assert st["power"] == "standby"
    assert st["active_app"] is None
    assert "192.168.1.60/query/active-app" not in rig.transport.gets


def test_poll_limited_sets_apps_refused(rig: Rig) -> None:
    rig.transport.tvs["192.168.1.60"].limited_apps = True
    rig.service.poll_status()
    assert rig.status()["apps_refused"] is True
    assert rig.status()["apps"] is None
    rig.service.poll_status()
    assert rig.transport.gets.count("192.168.1.60/query/apps") == 1


def test_apps_read_once_then_again_after_an_hour(rig: Rig) -> None:
    rig.service.poll_status()
    rig.service.poll_status()
    assert rig.transport.gets.count("192.168.1.60/query/apps") == 1
    rig.clock.advance(3601 * 1000)
    rig.service.poll_status()
    assert rig.transport.gets.count("192.168.1.60/query/apps") == 2


def test_poll_unanswering_tv_is_not_reachable_with_message(rig: Rig) -> None:
    rig.transport.tvs["192.168.1.60"].answering = False
    rig.service.poll_status()
    st = rig.status()
    assert st["reachable"] is False
    assert st["error"] == "The TV isn't answering. It may be fully powered off or have a new address."


def test_poll_covers_every_saved_tv() -> None:
    r = Rig([_saved(f"t{i}", f"192.168.1.{50 + i}", f"S{i}") for i in range(12)])
    for i in range(12):
        r.transport.tvs[f"192.168.1.{50 + i}"] = FakeTv(f"S{i}", f"TV {i}")
    r.service.poll_status()
    assert all(r.status(f"t{i}")["reachable"] for i in range(12))


def test_serial_adopted_and_saved_when_missing() -> None:
    r = Rig([_saved(serial="")])
    r.transport.tvs["192.168.1.60"] = FakeTv("NEWSERIAL")
    r.service.poll_status()
    assert r.store.load()[0].serial == "NEWSERIAL"
    assert r.status()["reachable"] is True


def test_wrong_device_blocks_status_and_commands() -> None:
    r = Rig([_saved(serial="S1")])
    r.transport.tvs["192.168.1.60"] = FakeTv("S2", "Bedroom TV")
    r.service.poll_status()
    st = r.status()
    assert st["reachable"] is False
    assert st["wrong_device"] == "Bedroom TV"
    with pytest.raises(CommandError) as e:
        r.service.send_key("a", "PowerOff")
    assert e.value.status_code == 409
    assert (
        e.value.message
        == "A different Roku, Bedroom TV, now answers at this address. Run a scan in Settings."
    )
    assert r.transport.posts == []


def test_fresh_identity_skips_the_recheck(rig: Rig) -> None:
    rig.service.poll_status()
    before = rig.transport.gets.count("192.168.1.60/query/device-info")
    rig.clock.advance(19_000)  # inside 2 * 10 s
    rig.service.send_key("a", "Home")
    assert rig.transport.gets.count("192.168.1.60/query/device-info") == before
    assert rig.transport.posts == ["192.168.1.60/keypress/Home"]


def test_stale_identity_is_rechecked_before_a_command(rig: Rig) -> None:
    rig.service.poll_status()
    before = rig.transport.gets.count("192.168.1.60/query/device-info")
    rig.clock.advance(21_000)
    rig.service.send_key("a", "Home")
    assert rig.transport.gets.count("192.168.1.60/query/device-info") == before + 1
    assert rig.transport.posts == ["192.168.1.60/keypress/Home"]
    # the TV is swapped; once the identity is old again the command is refused
    rig.transport.tvs["192.168.1.60"].serial = "OTHER"
    rig.clock.advance(21_000)
    with pytest.raises(CommandError) as e:
        rig.service.send_key("a", "Home")
    assert e.value.status_code == 409
    assert len(rig.transport.posts) == 1


def test_send_key_posts_allowed_path_and_schedules_refresh(rig: Rig) -> None:
    rig.service.send_key("a", "VolumeUp")
    rig.service.send_key("a", "Select", "down")
    assert rig.transport.posts == ["192.168.1.60/keypress/VolumeUp", "192.168.1.60/keydown/Select"]
    assert len(rig.timers) == 2
    delay, fn = rig.timers[0]
    assert delay == 1.0
    fn()
    assert rig.status()["reachable"] is True


def test_send_key_rejects_disallowed_key_without_network(rig: Rig) -> None:
    with pytest.raises(ValueError):
        rig.service.send_key("a", "Format")
    with pytest.raises(ValueError):
        rig.service.send_key("a", "Home", "wiggle")
    assert rig.transport.gets == [] and rig.transport.posts == []


def test_launch_validates_app_id(rig: Rig) -> None:
    rig.service.launch("a", "837")
    assert rig.transport.posts == ["192.168.1.60/launch/837"]
    with pytest.raises(ValueError):
        rig.service.launch("a", "../x")


def test_send_key_to_unanswering_tv_returns_message_quickly(rig: Rig) -> None:
    rig.transport.tvs["192.168.1.60"].answering = False
    with pytest.raises(CommandError) as e:
        rig.service.send_key("a", "Home")
    assert e.value.status_code == 502
    assert e.value.message == "The TV isn't answering. It may be fully powered off or have a new address."
    assert rig.timers == []


def test_command_refused_by_tv_is_502_with_its_message(rig: Rig) -> None:
    rig.service.poll_status()
    orig = rig.transport.__call__

    def refuse(method: str, url: str, timeout_s: float) -> EcpResponse:
        if method == "POST":
            return EcpResponse(403, {}, b"")
        return orig(method, url, timeout_s)

    rig.ecp._transport = refuse
    with pytest.raises(CommandError) as e:
        rig.service.send_key("a", "Home")
    assert e.value.status_code == 502
    assert e.value.message == "This TV's Network access setting (Limited) refuses commands"


def test_type_text_posts_one_keypress_per_character_in_order(rig: Rig) -> None:
    rig.service.type_text("a", "a b/")
    assert rig.transport.posts == [
        "192.168.1.60/keypress/Lit_a",
        "192.168.1.60/keypress/Lit_%20",
        "192.168.1.60/keypress/Lit_b",
        "192.168.1.60/keypress/Lit_%2F",
    ]
    with pytest.raises(ValueError):
        rig.service.type_text("a", "")


def test_icon_returns_bytes_and_type(rig: Rig) -> None:
    assert rig.service.icon("a", "837") == (b"PNG", "image/png")
    with pytest.raises(ValueError):
        rig.service.icon("a", "x/y")


def test_unknown_tv_raises(rig: Rig) -> None:
    calls: list[Callable[[], object]] = [
        lambda: rig.service.send_key("zzz", "Home"),
        lambda: rig.service.launch("zzz", "837"),
        lambda: rig.service.type_text("zzz", "x"),
        lambda: rig.service.icon("zzz", "837"),
        lambda: rig.service.refresh("zzz"),
    ]
    for call in calls:
        with pytest.raises(UnknownTv):
            call()


def test_settings_changed_updates_the_request_timeout(rig: Rig) -> None:
    rig.service.settings_changed(RokuSettings(request_timeout_s=5, status_interval_s=60))
    rig.service.refresh("a")
    assert set(rig.transport.timeouts) == {5}
    rig.service.poll_status()
    rig.clock.advance(100_000)  # beyond 2 * 10 s, inside 2 * 60 s
    rig.transport.gets.clear()
    rig.service.send_key("a", "Home")
    assert "192.168.1.60/query/device-info" not in rig.transport.gets


def test_save_document_replace_and_merge_messages(rig: Rig) -> None:
    doc = rig.service.document()
    assert doc["schema"] == "netview.roku/tvs@1"
    assert rig.service.save_document(json.dumps(doc)) == {"message": "Saved: 1 TV"}
    two = {
        "schema": doc["schema"],
        "tvs": [{"ip": "192.168.1.61"}, {"ip": "192.168.1.62"}, {"ip": "10.0.0.5"}],
    }
    assert rig.service.save_document(json.dumps(two)) == {"message": "Saved: 3 TVs"}
    assert [t.ip for t in rig.store.load()] == ["192.168.1.61", "192.168.1.62", "10.0.0.5"]
    scan_doc = {
        "schema": "ketiv.network-tools/roku-scan@1",
        "devices": [{"ip": "192.168.1.61", "name": "Renamed"}, {"ip": "192.168.1.70", "name": "New"}],
    }
    out = rig.service.save_document(json.dumps(scan_doc))
    assert out["message"] == "Merged: 1 added, 1 updated"
    assert next(t.name for t in rig.store.load()) == "Renamed"


def test_save_document_rejects_garbage(rig: Rig) -> None:
    with pytest.raises(DocumentError):
        rig.service.save_document("hello")
    with pytest.raises(DocumentError):
        rig.service.save_document("8.8.8.8")


def test_save_ip_list_reports_skipped(rig: Rig) -> None:
    rig.transport.tvs["192.168.1.61"] = FakeTv("S9", "Den")
    out = rig.service.save_document("192.168.1.61\n192.168.1.9\n")
    assert out["message"] == "Merged: 1 added, 0 updated. Skipped (no Roku answered): 192.168.1.9"
    assert out["skipped"] == ["192.168.1.9"]
    added = next(t for t in rig.store.load() if t.ip == "192.168.1.61")
    assert (added.serial, added.name, added.found_by) == ("S9", "Den", "manual")


def test_scan_merges_hits_and_second_scan_while_running_is_refused() -> None:
    release = threading.Event()
    entered = threading.Event()
    seen: list[Any] = []

    def scanner(probes: Any, ecp: Any, subnet: Any, timeout_s: float) -> ScanResult:
        seen.append((probes, subnet, timeout_s))
        entered.set()
        release.wait(5)
        return ScanResult([ScanHit("192.168.1.80", "S80", "Den", "M", "", True, "ssdp")], subnet, 1, 0, 1.5)

    r = Rig([], scanner)
    assert r.service.start_scan() is True
    assert entered.wait(5)
    assert r.service.scan_state()["running"] is True
    assert r.service.start_scan() is False
    release.set()
    for _ in range(500):
        if not r.service.scan_state()["running"]:
            break
        threading.Event().wait(0.01)
    state = r.service.scan_state()
    assert state["running"] is False
    assert (state["found"], state["by_ssdp"], state["by_sweep"], state["duration_s"], state["error"]) == (
        1, 1, 0, 1.5, "",
    )  # fmt: skip
    assert state["started_ms"] is not None and state["finished_ms"] is not None
    assert seen == [(r.probes, "192.168.1.0/24", 2)]
    assert [t.serial for t in r.store.load()] == ["S80"]


def test_run_scan_reports_failure_and_can_run_again() -> None:
    calls = {"n": 0}

    def scanner(*args: Any) -> ScanResult:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("socket gone")
        return ScanResult([], None, 0, 0, 0.1)

    r = Rig([], scanner)
    r.service.run_scan()
    assert r.service.scan_state()["error"] == "socket gone"
    assert r.service.scan_state()["running"] is False
    r.service.run_scan()
    assert r.service.scan_state()["error"] == ""


def _replace_with(rig: Rig, **changes: str) -> None:
    doc = rig.service.document()
    doc["tvs"][0].update(changes)
    rig.service.save_document(json.dumps(doc))


def test_changed_address_voids_the_fresh_identity(rig: Rig) -> None:
    rig.service.poll_status()
    rig.transport.tvs["192.168.1.61"] = FakeTv("OTHER", "Bedroom TV")
    _replace_with(rig, ip="192.168.1.61")
    assert rig.store.load()[0].id == "a"
    with pytest.raises(CommandError) as e:
        rig.service.send_key("a", "Home")  # still inside the 2 * status_interval window
    assert e.value.status_code == 409
    assert "192.168.1.61/query/device-info" in rig.transport.gets
    assert rig.transport.posts == []


def test_changed_serial_voids_the_fresh_identity(rig: Rig) -> None:
    rig.service.poll_status()
    _replace_with(rig, serial="S2")  # the TV still answers S1
    with pytest.raises(CommandError) as e:
        rig.service.send_key("a", "Home")
    assert e.value.status_code == 409
    assert rig.transport.posts == []


def test_adoption_never_takes_a_serial_another_entry_holds() -> None:
    r = Rig([_saved("a", "192.168.1.60", "S1"), _saved("b", "192.168.1.61", "")])
    r.transport.tvs["192.168.1.60"] = FakeTv("S1")
    r.transport.tvs["192.168.1.61"] = FakeTv("S1")
    r.service.poll_status()
    assert [t.serial for t in r.store.load()] == ["S1", ""]


def test_adoption_does_not_overwrite_a_serial_saved_in_between() -> None:
    r = Rig([_saved("a", "192.168.1.60", "")])
    r.transport.tvs["192.168.1.60"] = FakeTv("S1")
    stale = r.store.load()[0]  # the snapshot a poll would hold
    r.store.replace([replace(stale, serial="MINE")])
    live = r.service._live_for("a")
    r.service._check_identity(stale, parse_device_info(_info("S1", "Living Room TV")) or pytest.fail(), live)
    assert r.store.load()[0].serial == "MINE"


def test_refresh_rereads_apps_after_a_403_once_the_tv_allows_them(rig: Rig) -> None:
    rig.transport.tvs["192.168.1.60"].limited_apps = True
    rig.service.poll_status()
    assert rig.status()["apps_refused"] is True
    rig.service.poll_status()  # the periodic poll keeps the rule
    assert rig.transport.gets.count("192.168.1.60/query/apps") == 1
    rig.transport.tvs["192.168.1.60"].limited_apps = False
    rig.service.refresh("a")
    st = rig.status()
    assert st["apps_refused"] is False
    assert st["apps"]
    assert rig.transport.gets.count("192.168.1.60/query/apps") == 2


def test_refresh_rereads_fresh_apps_on_demand(rig: Rig) -> None:
    rig.service.poll_status()
    rig.service.refresh("a")
    assert rig.transport.gets.count("192.168.1.60/query/apps") == 2
