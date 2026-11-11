"""The switch's serial console, reached through an SSH host that has the serial cable (the Proxmox server).

netview only ever sends one carriage return (the probe). Everything else is the user typing in their
own terminal.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

SESSION = "netview-gsm7248"
TERMINAL_TITLE = "GSM7248 console"

HOST_PATTERN = r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$"
USER_PATTERN = r"^[a-z_][a-z0-9_-]{0,31}$"
DEVICE_PATTERN = r"^/dev/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$"

_PROBE_TIMEOUT_S = 15.0
_REPLY_MARK = b"NETVIEW:REPLY\n"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CONTROL = re.compile(r"[^\x20-\x7e\n]")
_MAX_TEXT = 300

ConsoleState = Literal["connected", "silent", "in_use", "no_device", "unreachable"]


class ConsoleError(Exception):
    """The console could not be probed or opened; the message is safe to show."""


@dataclass(frozen=True)
class ConsoleTarget:
    """Where the serial line is. Every field is pattern-checked by the settings model."""

    host: str
    user: str
    device: str
    baud: int

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}"


@dataclass(frozen=True)
class ConsoleStatus:
    state: ConsoleState
    detail: str
    text: str
    at_ms: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CommandRunner(Protocol):
    def run(self, argv: list[str], timeout_s: float) -> tuple[int, bytes, str]:
        """Run to completion: (exit code, stdout, stderr). Raises ConsoleError if it cannot run."""

    def spawn(self, argv: list[str]) -> None:
        """Start and do not wait. Raises ConsoleError if it cannot start."""


class SubprocessRunner:
    """The real runner. Argument lists only: nothing goes through a shell on this computer."""

    def run(self, argv: list[str], timeout_s: float) -> tuple[int, bytes, str]:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            done = subprocess.run(
                argv,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_s,
                check=False,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConsoleError(f"{argv[0]} did not finish within {timeout_s:.0f} s") from exc
        except OSError as exc:
            raise ConsoleError(f"could not run {argv[0]}: {exc.strerror or exc}") from exc
        return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace")

    def spawn(self, argv: list[str]) -> None:
        try:
            subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as exc:
            raise ConsoleError(f"could not start {argv[0]}: {exc.strerror or exc}") from exc


def probe_script(target: ConsoleTarget) -> str:
    """The remote probe script, on one line and without double quotes (it crosses two command lines).

    It never writes to the line while a console session holds it. Otherwise it sets the line, starts reading,
    sends one carriage return and prints what came back within two seconds after the ``NETVIEW:REPLY`` line.
    """
    dev = target.device
    busy = "echo NETVIEW:IN_USE; exit 0"
    return "; ".join(
        [
            f"if screen -ls 2>/dev/null | grep -q '[.]{SESSION}[[:space:]]'; then {busy}; fi",
            f"if [ ! -c {dev} ]; then echo NETVIEW:NO_DEVICE; exit 0; fi",
            f"if command -v fuser >/dev/null 2>&1 && fuser {dev} >/dev/null 2>&1; then {busy}; fi",
            f"if ! stty -F {dev} {target.baud} cs8 -parenb -cstopb -crtscts clocal raw -echo 2>/dev/null; "
            "then echo NETVIEW:NO_DEVICE; exit 0; fi",
            "echo NETVIEW:REPLY",
            f"(sleep 0.3; printf '\\r' > {dev}) & timeout 2 cat {dev} | head -c 512",
            "wait",
            "exit 0",
        ]
    )


def clean_reply(raw: bytes) -> str:
    """What the switch sent as plain text: no escape sequences or blank lines, the last 300 characters."""
    text = _ANSI.sub("", raw.decode("utf-8", "replace")).replace("\r", "\n")
    lines = [line.strip() for line in _CONTROL.sub("", text).split("\n")]
    return "\n".join(line for line in lines if line)[-_MAX_TEXT:]


class SerialConsole:
    def __init__(
        self,
        runner: CommandRunner,
        platform: str = sys.platform,
        which: Callable[[str], str | None] = shutil.which,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self._runner = runner
        self._platform = platform
        self._which = which
        self._now_ms = now_ms

    def _ssh(self) -> str:
        return self._which("ssh") or "ssh"

    def probe(self, target: ConsoleTarget) -> ConsoleStatus:
        """Ask the SSH host whether the switch answers on the serial line. Never raises."""

        def status(state: ConsoleState, detail: str, text: str = "") -> ConsoleStatus:
            return ConsoleStatus(state, detail, text, self._now_ms())

        argv = [
            self._ssh(),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            target.destination,
            probe_script(target),
        ]
        try:
            code, out, err = self._runner.run(argv, _PROBE_TIMEOUT_S)
        except ConsoleError as exc:
            return status("unreachable", str(exc))
        head, mark, reply = out.replace(b"\r\n", b"\n").partition(_REPLY_MARK)
        if mark:
            text = clean_reply(reply)
            if text:
                return status("connected", "The switch answered on the serial line", text)
            return status(
                "silent", "Nothing came back: the switch is off, the cable is out or the speed is wrong"
            )
        if b"NETVIEW:IN_USE" in head:
            return status("in_use", f"A console session is open on {target.device}")
        if b"NETVIEW:NO_DEVICE" in head:
            return status("no_device", f"{target.device} is not a usable serial port on {target.host}")
        lines = [line.strip() for line in err.splitlines() if line.strip()]
        return status("unreachable", lines[-1] if lines else f"ssh to {target.host} ended with code {code}")

    def can_open(self) -> bool:
        """Opening a terminal needs Windows Terminal and ssh on this computer."""
        return self._platform == "win32" and self._which("wt") is not None and self._which("ssh") is not None

    def open_argv(self, target: ConsoleTarget) -> list[str]:
        wt = self._which("wt") or "wt"
        remote = f"screen -D -R -S {SESSION} {target.device} {target.baud}"
        return [
            wt,
            "-w",
            "0",
            "new-tab",
            "--title",
            TERMINAL_TITLE,
            self._ssh(),
            "-t",
            target.destination,
            remote,
        ]

    def open(self, target: ConsoleTarget) -> None:
        """Open a Windows Terminal tab on the console; opening again reattaches to the same screen session."""
        if not self.can_open():
            raise ConsoleError("Opening a terminal needs Windows Terminal (wt.exe) and ssh on this computer")
        self._runner.spawn(self.open_argv(target))
