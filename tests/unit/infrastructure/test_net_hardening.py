"""Review fixes M12 and M19."""

import os
import socket
import threading
import time

import pytest

from netview.infrastructure.net import common, windows
from netview.infrastructure.net.tools import SystemNetworkTools


def test_dns_query_has_an_overall_deadline() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.settimeout(3)

    def junk() -> None:
        try:
            _, client = server.recvfrom(512)
        except OSError:
            return
        for _ in range(50):
            try:
                server.sendto(b"\xff\xfe\x81\x80junk", client)
            except OSError:
                return
            time.sleep(0.05)

    threading.Thread(target=junk, daemon=True).start()
    started = time.monotonic()
    result = common.dns_query("127.0.0.1", "example.com", 0.5, port=port)
    elapsed = time.monotonic() - started
    server.close()
    assert result is None
    assert elapsed < 0.5 + 0.3


BAD_IPS = ["", "1.2.3.4; calc", "-n 1 evil", "999.1.1.1", "1.2.3", "::1", "1.2.3.4 ", "a.b.c.d"]


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
@pytest.mark.parametrize("bad", BAD_IPS)
def test_invalid_ip_never_runs_a_subprocess(monkeypatch: pytest.MonkeyPatch, platform: str, bad: str) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(common, "run", lambda cmd, timeout=10: calls.append(cmd) or "")
    tools = SystemNetworkTools(platform)
    assert tools.ping(bad) is None
    assert tools.default_gateway(bad) is None
    assert tools.tcp_probe(bad, 80).state == "filtered"
    assert tools.dns_query(bad, "example.com") is None
    assert calls == []


def test_valid_ip_still_runs_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(common, "run", lambda cmd, timeout=10: calls.append(cmd) or "")
    SystemNetworkTools("linux").ping("10.0.0.1")
    assert calls
    assert calls[0][-1] == "10.0.0.1"


def test_windows_commands_use_absolute_system32_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SystemRoot", r"D:\Win")
    root = os.path.join(r"D:\Win", "System32")
    assert windows.ping_command("10.0.0.1", 800) == [
        os.path.join(root, "PING.EXE"),
        "-n",
        "1",
        "-w",
        "800",
        "10.0.0.1",
    ]
    assert windows.arp_command() == [os.path.join(root, "ARP.EXE"), "-a"]
    assert windows.route_command() == [os.path.join(root, "ROUTE.EXE"), "print", "-4", "0.0.0.0"]


def test_windows_system_root_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SystemRoot", raising=False)
    assert windows.arp_command()[0] == os.path.join(r"C:\Windows", "System32", "ARP.EXE")
