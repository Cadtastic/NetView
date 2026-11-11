from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from netview_local_plugins.roku.discovery import MAX_SWEEP, ScanResult, scan
from netview_local_plugins.roku.ecp import EcpClient, EcpResponse

from netview.sdk import SsdpEntry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ROKU_BODY = (FIXTURES / "device-info-on.xml").read_bytes()
NOT_ROKU_BODY = (FIXTURES / "not-roku.xml").read_bytes()


class FakeProbes:
    def __init__(self, entries: list[SsdpEntry] | None = None) -> None:
        self.entries = entries or []
        self.sts: list[str] = []

    def ssdp_search(
        self, target: str | None = None, timeout_s: float = 2.5, st: str = "ssdp:all"
    ) -> list[SsdpEntry]:
        self.sts.append(st)
        return list(self.entries)


class FakeTransport:
    def __init__(self, rokus: set[str], not_roku: set[str] | None = None) -> None:
        self.rokus = rokus
        self.not_roku = not_roku or set()
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, method: str, url: str, timeout_s: float) -> EcpResponse:
        match = re.match(r"http://([\d.]+):8060/query/device-info$", url)
        assert match, url
        ip = match.group(1)
        with self._lock:
            self.calls.append(ip)
        if ip in self.rokus:
            return EcpResponse(200, {}, ROKU_BODY)
        if ip in self.not_roku:
            return EcpResponse(200, {}, NOT_ROKU_BODY)
        raise OSError("refused")


def entry(ip: str, location: str | None = None) -> SsdpEntry:
    return SsdpEntry(ip, location or f"http://{ip}:8060/", "Roku", "uuid:x", ("roku:ecp",))


def run(
    probes: FakeProbes,
    transport: FakeTransport,
    subnet: str | None,
    clock: Callable[[], float] = time.monotonic,
) -> ScanResult:
    return scan(probes, EcpClient(transport), subnet, 0.5, workers=16, clock=clock)


def test_scan_combines_ssdp_and_sweep_found_by() -> None:
    probes = FakeProbes([entry("192.168.1.60"), entry("192.168.1.62")])
    transport = FakeTransport({"192.168.1.60", "192.168.1.61", "192.168.1.62"})
    result = run(probes, transport, "192.168.1.0/24")
    assert [(h.ip, h.found_by) for h in result.hits] == [
        ("192.168.1.60", "ssdp+sweep"),
        ("192.168.1.61", "sweep"),
        ("192.168.1.62", "ssdp+sweep"),
    ]
    assert result.hits[0].serial == "X01234567890"


def test_scan_ssdp_only_address_outside_sweep_is_fetched_once() -> None:
    probes = FakeProbes([entry("192.168.9.62")])
    transport = FakeTransport({"192.168.9.62", "192.168.1.60"})
    result = run(probes, transport, "192.168.1.0/24")
    by_ip = {h.ip: h.found_by for h in result.hits}
    assert by_ip == {"192.168.1.60": "sweep", "192.168.9.62": "ssdp"}
    assert transport.calls.count("192.168.9.62") == 1
    assert [h.ip for h in result.hits] == sorted(by_ip, key=lambda s: tuple(map(int, s.split("."))))


def test_scan_sends_roku_search_target() -> None:
    probes = FakeProbes()
    run(probes, FakeTransport(set()), None)
    assert probes.sts == ["roku:ecp"]


def test_scan_skips_sweep_above_1024_addresses() -> None:
    assert MAX_SWEEP == 1024
    probes = FakeProbes([entry("192.168.1.60")])
    transport = FakeTransport({"192.168.1.60", "192.168.2.5"})
    result = run(probes, transport, "192.168.0.0/21")
    assert transport.calls == ["192.168.1.60"]
    assert [h.found_by for h in result.hits] == ["ssdp"]
    assert result.by_sweep == 0


def test_scan_sweeps_a_22() -> None:
    transport = FakeTransport({"192.168.3.200"})
    result = run(FakeProbes(), transport, "192.168.0.0/22")
    assert len(transport.calls) == 1022
    assert [h.ip for h in result.hits] == ["192.168.3.200"]


def test_scan_ignores_non_roku_answers_and_public_ssdp_locations() -> None:
    probes = FakeProbes(
        [
            entry("8.8.8.8"),
            entry("192.168.1.5", "http://8.8.8.8:8060/"),
            entry("192.168.1.6", "http://192.168.1.6:80/x"),
        ]
    )
    transport = FakeTransport({"8.8.8.8"}, not_roku={"192.168.1.7"})
    result = run(probes, transport, "192.168.1.4/30")
    assert result.hits == []
    assert "8.8.8.8" not in transport.calls


def test_scan_counts_and_duration() -> None:
    ticks = iter([10.0, 12.5])
    probes = FakeProbes([entry("192.168.1.60"), entry("192.168.1.62")])
    transport = FakeTransport({"192.168.1.60", "192.168.1.61", "192.168.1.62"})
    result = run(probes, transport, "192.168.1.0/24", clock=lambda: next(ticks))
    assert (result.by_ssdp, result.by_sweep) == (2, 3)
    assert result.duration_s == 2.5
    assert result.subnet == "192.168.1.0/24"
