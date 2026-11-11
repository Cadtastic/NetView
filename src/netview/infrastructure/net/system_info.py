"""SystemSystemInfo: this device's own byte counters, Wi-Fi link and TCP sockets (LM 274-360)."""

import dataclasses
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from netview.application.ports.system import TcpSocket, WifiInfo
from netview.infrastructure.net import common, linux, windows

PID_NAMES_TTL_S = 30.0


class SystemSystemInfo:
    """Implements SystemInfo. Never raises: failures give ``None`` or an empty list."""

    def __init__(
        self,
        platform: str = sys.platform,
        own_pid: int | None = None,
        proc_net_dev: str | os.PathLike[str] = "/proc/net/dev",
    ) -> None:
        self._win = platform == "win32"
        self._mac = platform == "darwin"
        self._own_pid = os.getpid() if own_pid is None else own_pid
        self._proc_net_dev = Path(proc_net_dev)
        self._pid_names: dict[str, str] = {}
        self._pid_names_at = float("-inf")
        self._lock = threading.Lock()

    def interface_bytes(self) -> tuple[int, int] | None:
        if self._win:
            return windows.parse_netstat_e(common.run(windows.netstat_e_command()))
        try:
            text = self._proc_net_dev.read_text(encoding="utf-8")
        except OSError:
            return None
        return linux.parse_proc_net_dev(text)

    def wifi(self) -> WifiInfo | None:
        if self._win:
            return windows.parse_netsh_wlan(common.run(windows.netsh_wlan_command()))
        if shutil.which("nmcli"):
            return linux.parse_nmcli(common.run(linux.NMCLI_COMMAND))
        return None

    def tcp_sockets(self) -> list[TcpSocket]:
        if self._win:
            rows = windows.parse_netstat_ano(common.run(windows.netstat_ano_command()), self._own_pid)
            names = self._names()
            return [dataclasses.replace(r, process=names.get(r.process, r.process)) for r in rows]
        if self._mac:
            return linux.parse_netstat_macos(common.run(linux.MACOS_NETSTAT_COMMAND))
        if shutil.which("ss"):
            return linux.parse_ss(common.run(linux.SS_COMMAND), self._own_pid)
        return []

    def _names(self) -> dict[str, str]:
        """PID -> process name, refreshed at most every 30 s."""
        with self._lock:
            now = time.monotonic()
            if now - self._pid_names_at > PID_NAMES_TTL_S:
                self._pid_names = windows.parse_tasklist(common.run(windows.tasklist_command()))
                self._pid_names_at = now
            return self._pid_names
