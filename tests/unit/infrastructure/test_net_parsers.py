import subprocess
from pathlib import Path

import pytest

from netview.application.ports.network import PingResult
from netview.infrastructure.net import linux, windows
from netview.infrastructure.net.tools import SystemNetworkTools

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "net"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_windows_ping_reply_has_ttl() -> None:
    result = windows.parse_ping(fx("win_ping_ok.txt"))
    assert isinstance(result, PingResult)
    assert result.ttl > 0


def test_windows_ping_unreachable_is_none() -> None:
    assert windows.parse_ping(fx("win_ping_unreachable.txt")) is None


def test_windows_ping_under_one_ms_halves() -> None:
    result = windows.parse_ping(fx("win_ping_lt1ms.txt"))
    assert result is not None
    assert result.rtt_ms == 0.5


def test_windows_arp_normalises_and_skips_broadcast() -> None:
    table = windows.parse_arp(fx("win_arp.txt"))
    assert table["192.0.2.1"] == "02:00:5e:10:00:01"
    assert "192.0.2.255" not in table
    assert "255.255.255.255" not in table
    assert not any(ip.startswith("224.") or ip.startswith("239.") for ip in table)


def test_windows_gateway_prefers_route_on_local_interface() -> None:
    assert windows.parse_default_gateway(fx("win_route.txt"), "192.0.2.95") == "192.0.2.1"


def test_windows_gateway_none_without_default_route() -> None:
    assert windows.parse_default_gateway("no routes here", "192.168.1.95") is None


def test_windows_ping_command() -> None:
    command = windows.ping_command("10.0.0.1", 800)
    assert command[0].lower().endswith("ping.exe")
    assert command[1:] == ["-n", "1", "-w", "800", "10.0.0.1"]


def test_linux_ping_reply() -> None:
    result = linux.parse_ping(fx("linux_ping_ok.txt"))
    assert result == PingResult(rtt_ms=1.84, ttl=64)


def test_linux_ping_unreachable_is_none() -> None:
    assert linux.parse_ping("From 192.168.1.95 icmp_seq=1 Destination Host Unreachable") is None


def test_linux_neighbours_skip_failed_and_incomplete() -> None:
    table = linux.parse_arp(fx("linux_ip_neigh.txt"))
    assert table == {
        "192.0.2.1": "02:00:5e:10:00:01",
        "192.0.2.25": "02:00:5e:10:00:02",
        "192.0.2.211": "02:00:5e:10:00:03",
    }


def test_linux_gateway() -> None:
    assert linux.parse_default_gateway(fx("linux_route.txt"), "192.0.2.95") == "192.0.2.1"


def test_linux_ping_command_rounds_timeout_up_to_a_second() -> None:
    assert linux.ping_command("10.0.0.1", 800) == ["ping", "-c", "1", "-W", "1", "10.0.0.1"]
    assert linux.ping_command("10.0.0.1", 2600) == ["ping", "-c", "1", "-W", "3", "10.0.0.1"]


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_tools_survive_missing_commands(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("no such command")

    monkeypatch.setattr(subprocess, "run", boom)
    tools = SystemNetworkTools(platform)
    assert tools.ping("192.168.1.1") is None
    assert tools.arp_table() == {}
    assert tools.default_gateway("192.168.1.95") is None


def test_tools_survive_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("ping", 1)

    monkeypatch.setattr(subprocess, "run", slow)
    tools = SystemNetworkTools("linux")
    assert tools.ping("192.168.1.1") is None
    assert tools.arp_table() == {}


def test_tools_parse_command_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["stdin"] == subprocess.DEVNULL
        return subprocess.CompletedProcess(cmd, 0, fx("win_ping_ok.txt").encode(), b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = SystemNetworkTools("win32").ping("192.168.1.1")
    assert result is not None
    assert result.ttl > 0
