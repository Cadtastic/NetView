"""SystemSystemInfo and the OS output parsers, on recorded and hand-written fixtures."""

from pathlib import Path

import pytest

from netview.application.ports.system import TcpSocket, WifiInfo
from netview.infrastructure.net import common, linux, system_info, windows
from netview.infrastructure.net.system_info import SystemSystemInfo

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "net"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------- parsers


def test_parse_netstat_e_reads_the_bytes_row() -> None:
    rx, tx = windows.parse_netstat_e(fx("win_netstat_e.txt")) or (0, 0)
    assert rx > 0 and tx > 0
    assert windows.parse_netstat_e("Interface Statistics\n\nBytes  12  34\n") == (12, 34)
    assert windows.parse_netstat_e("") is None
    assert windows.parse_netstat_e("Bytes   x   y\n") is None


def test_parse_netstat_ano_drops_our_pid() -> None:
    everything = windows.parse_netstat_ano(fx("win_netstat_ano.txt"), own_pid=1)
    ours = windows.parse_netstat_ano(fx("win_netstat_ano.txt"), own_pid=77777)
    assert len(everything) == len(ours) + 1
    assert all(r.process != "77777" for r in ours)
    assert any(r.process == "77777" for r in everything)
    listening = next(r for r in ours if r.local_port == 135)
    assert listening == TcpSocket("0.0.0.0", 135, "0.0.0.0", 0, "LISTENING", "2248")
    web = next(r for r in ours if r.remote_port == 443 and r.local_port == 49865)
    assert (web.local_ip, web.remote_ip, web.state) == ("192.0.2.95", "198.51.100.11", "ESTABLISHED")


def test_parse_tasklist_maps_pid_to_name() -> None:
    names = windows.parse_tasklist(fx("win_tasklist.txt"))
    assert names["4"] == "System"
    assert names["2248"] == "svchost.exe"
    assert names["26216"] == "browser.exe"
    assert windows.parse_tasklist("") == {}


def test_parse_netsh_wlan_connected() -> None:
    wifi = windows.parse_netsh_wlan(fx("win_netsh_wlan.txt"))
    assert wifi == WifiInfo(
        ssid="ExampleNet",
        bssid="02:00:5e:10:00:11",
        signal_pct=87,
        radio="802.11ax",
        band="5 GHz",
        channel="44",
        rx_rate_mbps=1201.0,
        tx_rate_mbps=960.0,
        state="connected",
        auth="WPA3-Personal",
    )


def test_parse_netsh_wlan_when_not_on_wifi_is_none() -> None:
    assert windows.parse_netsh_wlan(fx("win_netsh_wlan_down.txt")) is None
    assert windows.parse_netsh_wlan("") is None
    assert windows.parse_netsh_wlan("The Wireless AutoConfig Service (wlansvc) is not running.") is None


def test_parse_proc_net_dev_skips_loopback() -> None:
    assert linux.parse_proc_net_dev(fx("linux_proc_net_dev.txt")) == (10_000_000, 3_200_000)
    assert linux.parse_proc_net_dev("") == (0, 0)
    assert linux.parse_proc_net_dev("h1\nh2\nthis line has no colon\n") is None


def test_parse_ss_reads_process_names_and_drops_our_pid() -> None:
    rows = linux.parse_ss(fx("linux_ss.txt"), own_pid=4242)
    assert len(rows) == 5
    assert all(r.local_port != 8080 for r in rows)
    ssh = next(r for r in rows if r.remote_port == 22)
    assert ssh == TcpSocket("192.0.2.95", 50100, "192.0.2.1", 22, "ESTAB", "ssh")
    sshd = next(r for r in rows if r.local_port == 22)
    assert (sshd.state, sshd.process, sshd.remote_port) == ("LISTEN", "sshd", 0)
    trying = next(r for r in rows if r.state == "SYN-SENT")
    assert trying.process == "" and trying.remote_ip == "192.0.2.7"
    assert len(linux.parse_ss(fx("linux_ss.txt"), own_pid=1)) == 6


def test_parse_ss_pid_match_is_exact() -> None:
    assert len(linux.parse_ss(fx("linux_ss.txt"), own_pid=424)) == 6  # pid=4242 is not pid 424


def test_parse_netstat_macos() -> None:
    text = (
        "Active Internet connections (including servers)\n"
        "Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)\n"
        "tcp4       0      0  192.0.2.95.52000       198.51.100.11.443      ESTABLISHED\n"
        "tcp4       0      0  *.22                   *.*                    LISTEN\n"
        "tcp6       0      0  *.80                   *.*                    LISTEN\n"
    )
    assert linux.parse_netstat_macos(text) == [
        TcpSocket("192.0.2.95", 52000, "198.51.100.11", 443, "ESTABLISHED", ""),
        TcpSocket("*", 22, "*", 0, "LISTEN", ""),
    ]


def test_parse_nmcli_picks_the_active_access_point() -> None:
    wifi = linux.parse_nmcli(fx("linux_nmcli.txt"))
    assert wifi is not None
    assert (wifi.ssid, wifi.signal_pct, wifi.channel, wifi.rx_rate_mbps) == ("ExampleNet", 82, "44", 866.0)
    assert wifi.state == "connected"
    assert linux.parse_nmcli("no:Other:40:1:54 Mbit/s\n") is None
    assert linux.parse_nmcli("") is None


def test_parse_nmcli_unescapes_colons_in_an_ssid() -> None:
    wifi = linux.parse_nmcli("yes:My\\:Net:70:6:130 Mbit/s\n")
    assert wifi is not None and wifi.ssid == "My:Net"


def test_windows_commands_use_the_absolute_system32_path() -> None:
    for command in (
        windows.netstat_e_command(),
        windows.netstat_ano_command(),
        windows.tasklist_command(),
        windows.netsh_wlan_command(),
    ):
        assert command[0].lower().endswith(".exe")
        assert "system32" in command[0].lower()
        assert command[0].count("\\") + command[0].count("/") >= 2


# ---------------------------------------------------------------------- the adapter


class Recorder:
    """Stands in for ``common.run``: answers by executable name and counts the calls."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], timeout: float = 10) -> str:
        self.calls.append(cmd)
        exe = cmd[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        return self.answers.get(exe, "")

    def count(self, exe: str) -> int:
        return sum(1 for c in self.calls if c[0].replace("\\", "/").rsplit("/", 1)[-1].lower() == exe)


def test_windows_adapter_reads_bytes_wifi_and_sockets_with_process_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Recorder(
        {
            "netstat.exe": fx("win_netstat_e.txt"),
            "netsh.exe": fx("win_netsh_wlan.txt"),
            "tasklist.exe": fx("win_tasklist.txt"),
        }
    )

    def answer(cmd: list[str], timeout: float = 10) -> str:
        if "-ano" in cmd:
            run.calls.append(cmd)
            return fx("win_netstat_ano.txt")
        return run(cmd, timeout)

    monkeypatch.setattr(common, "run", answer)
    info = SystemSystemInfo("win32", own_pid=77777)
    assert info.interface_bytes() == windows.parse_netstat_e(fx("win_netstat_e.txt"))
    wifi = info.wifi()
    assert wifi is not None and wifi.signal_pct == 87
    sockets = info.tcp_sockets()
    assert all(s.process != "netview.exe" for s in sockets)
    by_port = {(s.local_port, s.remote_port): s for s in sockets}
    assert by_port[(135, 0)].process == "svchost.exe"
    assert by_port[(49865, 443)].process == "browser.exe"
    # a PID that tasklist does not know stays as the PID text (LM 1491)
    assert info.tcp_sockets()


def test_windows_process_names_are_cached_for_thirty_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Recorder({"netstat.exe": fx("win_netstat_ano.txt"), "tasklist.exe": fx("win_tasklist.txt")})
    clock = [1000.0]
    monkeypatch.setattr(common, "run", run)
    monkeypatch.setattr(system_info.time, "monotonic", lambda: clock[0])
    info = SystemSystemInfo("win32", own_pid=1)
    info.tcp_sockets()
    info.tcp_sockets()
    assert run.count("tasklist.exe") == 1
    assert run.count("netstat.exe") == 2
    clock[0] += 31
    info.tcp_sockets()
    assert run.count("tasklist.exe") == 2


def test_windows_unknown_pid_stays_the_pid_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common, "run", Recorder({"netstat.exe": fx("win_netstat_ano.txt")}))
    sockets = SystemSystemInfo("win32", own_pid=1).tcp_sockets()
    assert next(s for s in sockets if s.local_port == 135).process == "2248"


def test_linux_adapter_reads_proc_net_dev_ss_and_nmcli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = tmp_path / "dev"
    proc.write_text(fx("linux_proc_net_dev.txt"), encoding="utf-8")
    run = Recorder({"ss": fx("linux_ss.txt"), "nmcli": fx("linux_nmcli.txt")})
    monkeypatch.setattr(common, "run", run)
    monkeypatch.setattr(system_info.shutil, "which", lambda name: f"/usr/bin/{name}")
    info = SystemSystemInfo("linux", own_pid=4242, proc_net_dev=proc)
    assert info.interface_bytes() == (10_000_000, 3_200_000)
    assert info.tcp_sockets()[0].process == "sshd"
    assert len(info.tcp_sockets()) == 5
    wifi = info.wifi()
    assert wifi is not None and wifi.ssid == "ExampleNet"
    assert run.count("ss") == 2 and run.count("nmcli") == 1


def test_linux_adapter_without_the_tools_or_proc_gives_empty_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(common, "run", Recorder({}))
    monkeypatch.setattr(system_info.shutil, "which", lambda name: None)
    info = SystemSystemInfo("linux", proc_net_dev=tmp_path / "missing")
    assert info.interface_bytes() is None
    assert info.wifi() is None
    assert info.tcp_sockets() == []


def test_macos_adapter_uses_netstat(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "tcp4       0      0  192.0.2.95.52000       198.51.100.11.443      ESTABLISHED\n"
    run = Recorder({"netstat": text})
    monkeypatch.setattr(common, "run", run)
    sockets = SystemSystemInfo("darwin").tcp_sockets()
    assert [(s.local_port, s.remote_port) for s in sockets] == [(52000, 443)]
    assert run.calls[0] == ["netstat", "-anp", "tcp"]


def test_default_own_pid_is_this_process() -> None:
    import os

    assert SystemSystemInfo()._own_pid == os.getpid()
