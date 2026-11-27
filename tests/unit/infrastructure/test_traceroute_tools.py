import subprocess
import sys
import time
from pathlib import Path

import pytest

from netview.application.ports.network import TraceHop
from netview.infrastructure.net import common
from netview.infrastructure.net import tools as tools_module
from netview.infrastructure.net.tools import SystemNetworkTools
from netview.sdk import TraceResult
from netview.sdk.testing.fakes import FakeNetworkTools

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "net" / "traceroute"


def _runner(lines, calls=None, ok=True):
    def run_lines(cmd, timeout, on_line):
        if calls is not None:
            calls.append((cmd, timeout))
        for line in lines:
            on_line(line)
        return ok

    return run_lines


def _fixture_lines(name):
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def test_traceroute_refuses_host_names_and_runs_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(common, "run_lines", _runner([], calls))
    result = SystemNetworkTools("win32").traceroute("example.com; calc")
    assert result.error == "not an IP address"
    assert result.hops == ()
    assert result.reached is False
    assert calls == []


def test_limits_are_clamped(monkeypatch):
    calls = []
    monkeypatch.setattr(common, "run_lines", _runner([], calls))
    SystemNetworkTools("win32").traceroute("1.1.1.1", max_hops=500, probe_timeout_ms=1)
    cmd, timeout = calls[0]
    assert cmd[cmd.index("-h") + 1] == "64"
    assert cmd[cmd.index("-w") + 1] == "100"
    assert timeout == 64 * 3 * 100 / 1000 + 10


def test_windows_reached_streams_and_reports(monkeypatch):
    monkeypatch.setattr(common, "run_lines", _runner(_fixture_lines("tracert_win_reached.txt")))
    seen: list[TraceHop] = []
    result = SystemNetworkTools("win32").traceroute("1.1.1.1", on_hop=seen.append)
    assert result.reached is True
    assert result.error is None
    assert list(result.hops) == seen
    assert [h.n for h in seen] == list(range(1, 11))


def test_silent_destination_returns_within_timeout(monkeypatch):
    rows = [f"{n:3d}     *        *        *     Request timed out." for n in range(1, 31)]
    monkeypatch.setattr(common, "run_lines", _runner(rows))
    result = SystemNetworkTools("win32").traceroute("192.0.2.1")
    assert len(result.hops) == 30
    assert result.reached is False


def test_timed_out_run_keeps_hops_and_says_so(monkeypatch):
    monkeypatch.setattr(common, "run_lines", _runner(_fixture_lines("tracert_win_reached.txt")[:6], ok=False))
    result = SystemNetworkTools("win32").traceroute("1.1.1.1")
    assert result.error == "timed out"
    assert len(result.hops) == 3
    assert result.reached is False


def test_on_hop_called_in_order(monkeypatch):
    monkeypatch.setattr(common, "run_lines", _runner(_fixture_lines("traceroute_linux_reached.txt")))
    monkeypatch.setattr(tools_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    seen: list[int] = []
    result = SystemNetworkTools("linux").traceroute("1.1.1.1", on_hop=lambda h: seen.append(h.n))
    assert seen == [1, 2, 3, 4, 5, 6, 7, 8]
    assert result.reached is True


def test_linux_falls_back_to_tracepath_then_reports_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(common, "run_lines", _runner(_fixture_lines("tracepath_linux.txt"), calls))
    monkeypatch.setattr(
        tools_module.shutil, "which", lambda name: "/usr/bin/tracepath" if name == "tracepath" else None
    )
    result = SystemNetworkTools("linux").traceroute("1.1.1.1")
    assert calls[0][0][0] == "tracepath"
    assert [h.n for h in result.hops] == [1, 2, 3, 4, 5, 6]  # duplicate hop 1 merged
    assert result.hops[0].rtts_ms == (0.388,)  # best RTT kept
    assert result.reached is True

    calls.clear()
    monkeypatch.setattr(tools_module.shutil, "which", lambda name: None)
    missing = SystemNetworkTools("linux").traceroute("1.1.1.1")
    assert missing.error == "traceroute is not installed"
    assert calls == []


def test_run_lines_streams_output_and_reports_failure_to_start():
    got: list[str] = []
    assert common.run_lines([sys.executable, "-c", "print('a'); print('b')"], 20, got.append) is True
    assert got == ["a", "b"]
    assert common.run_lines(["definitely-not-a-real-command-xyz"], 5, got.append) is False


def test_fake_network_tools_replays_hops():
    hops = (TraceHop(1, "10.0.0.1", (1.0, 1.0, 1.0)), TraceHop(2, "1.1.1.1", (5.0, None, 5.0)))
    fake = FakeNetworkTools(traces={"1.1.1.1": TraceResult("1.1.1.1", hops, True)})
    seen: list[TraceHop] = []
    assert fake.traceroute("1.1.1.1", on_hop=seen.append).reached is True
    assert tuple(seen) == hops
    assert fake.traceroute("9.9.9.9").error is not None


def test_valid_ip_refuses_scope_ids():
    assert common.valid_ip("fe80::1%evil.example.com") is False
    assert common.valid_ip("::1%-n x") is False
    assert common.valid_ip("fe80::1%eth0") is False
    assert common.valid_ip("2606:4700:4700::1111") is True


def test_scoped_targets_run_nothing(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("a command was run")

    monkeypatch.setattr(common, "run_lines", boom)
    monkeypatch.setattr(common, "run", boom)
    tools = SystemNetworkTools("win32")
    result = tools.traceroute("fe80::1%eth0")
    assert result.error == "not an IP address"
    assert result.hops == ()
    assert tools.ping("fe80::1%eth0") is None


def test_run_lines_kills_a_hung_command_at_the_timeout():
    got: list[str] = []
    code = "import time; print('x', flush=True); time.sleep(30)"
    started = time.monotonic()
    assert common.run_lines([sys.executable, "-c", code], 0.5, got.append) is False
    assert time.monotonic() - started < 10
    assert got == ["x"]


def test_run_lines_reaps_the_child_when_on_line_raises(monkeypatch):
    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", recording_popen)

    def explode(line: str) -> None:
        raise RuntimeError("boom")

    code = "import time; print('x', flush=True); time.sleep(30)"
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="boom"):
        common.run_lines([sys.executable, "-c", code], 20, explode)
    assert time.monotonic() - started < 10
    assert spawned[0].poll() is not None  # killed and waited for, not left running
