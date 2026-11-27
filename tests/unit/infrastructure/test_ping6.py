from pathlib import Path

import pytest

from netview.application.ports.network import PingResult
from netview.infrastructure.net import common, linux, tools, windows

FIXTURES = Path(__file__).parents[2] / "fixtures" / "net" / "ping6"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_windows_ipv6_reply_has_rtt_and_no_ttl() -> None:
    result = windows.parse_ping(_read("ping6_win_reply.txt"), require_ttl=False)
    assert result == PingResult(rtt_ms=24.0, ttl=None)


def test_windows_ipv6_unreachable_is_none() -> None:
    assert windows.parse_ping(_read("ping6_win_unreachable.txt"), require_ttl=False) is None


def test_linux_ipv6_reply_parses() -> None:
    result = linux.parse_ping(_read("ping6_linux_reply.txt"), require_ttl=False)
    assert result == PingResult(rtt_ms=24.1, ttl=57)


def test_ipv4_without_ttl_is_still_none() -> None:
    assert windows.parse_ping(_read("ping6_win_reply.txt")) is None
    assert linux.parse_ping("Reply from 10.0.0.1: time=3ms") is None


def test_ping_command_adds_dash_6_only_for_ipv6() -> None:
    assert "-6" in windows.ping_command("2606:4700:4700::1111", 800)
    assert "-6" not in windows.ping_command("1.1.1.1", 800)
    assert "-6" in linux.ping_command("2606:4700:4700::1111", 800)
    assert "-6" not in linux.ping_command("1.1.1.1", 800)
    assert linux.macos_ping_command("2606:4700:4700::1111", 800)[0] == "ping6"
    assert linux.macos_ping_command("1.1.1.1", 800)[0] == "ping"


@pytest.mark.parametrize("value", ["1.1.1.1", "2606:4700:4700::1111", "::1"])
def test_valid_ip_accepts_literals(value: str) -> None:
    assert common.valid_ip(value)


@pytest.mark.parametrize("value", ["example.com", "", "1.1.1.1; rm", None, 5])
def test_valid_ip_rejects_the_rest(value: object) -> None:
    assert not common.valid_ip(value)


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_ping_refuses_host_names(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    def fail(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("no command may run")

    monkeypatch.setattr(common, "run", fail)
    assert tools.SystemNetworkTools(platform).ping("example.com") is None


def test_ping_ipv6_runs_and_parses_without_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common, "run", lambda *_a, **_k: _read("ping6_win_reply.txt"))
    result = tools.SystemNetworkTools("win32").ping("2606:4700:4700::1111")
    assert result == PingResult(rtt_ms=24.0, ttl=None)


def test_linux_ipv6_falls_back_to_ping6_when_dash_6_prints_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], timeout: float = 10) -> str:
        calls.append(cmd)
        return "" if cmd[0] == "ping" else _read("ping6_linux_reply.txt")

    monkeypatch.setattr(common, "run", fake_run)
    result = tools.SystemNetworkTools("linux").ping("2606:4700:4700::1111")
    assert [c[0] for c in calls] == ["ping", "ping6"]
    assert result == PingResult(rtt_ms=24.1, ttl=57)


def test_linux_ipv4_and_nonempty_ipv6_do_not_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], timeout: float = 10) -> str:
        calls.append(cmd)
        return ""

    monkeypatch.setattr(common, "run", fake_run)
    tools.SystemNetworkTools("linux").ping("1.1.1.1")
    assert len(calls) == 1
    monkeypatch.setattr(
        common, "run", lambda cmd, timeout=10: calls.append(cmd) or _read("ping6_linux_reply.txt")
    )
    calls.clear()
    tools.SystemNetworkTools("linux").ping("2606:4700:4700::1111")
    assert len(calls) == 1
