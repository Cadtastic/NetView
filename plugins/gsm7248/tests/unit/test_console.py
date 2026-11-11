from __future__ import annotations

import re

import pytest
from netview_local_plugins.gsm7248.console import (
    SESSION,
    ConsoleError,
    ConsoleTarget,
    SerialConsole,
    clean_reply,
    probe_script,
)
from netview_local_plugins.gsm7248.settings import Gsm7248Settings
from pydantic import ValidationError

TARGET = ConsoleTarget("192.168.1.36", "root", "/dev/ttyS0", 38400)


class FakeRunner:
    def __init__(self, result: tuple[int, bytes, str] | ConsoleError = (0, b"", "")) -> None:
        self.result = result
        self.ran: list[list[str]] = []
        self.spawned: list[list[str]] = []

    def run(self, argv: list[str], timeout_s: float) -> tuple[int, bytes, str]:
        self.ran.append(argv)
        if isinstance(self.result, ConsoleError):
            raise self.result
        return self.result

    def spawn(self, argv: list[str]) -> None:
        self.spawned.append(argv)


def which_all(name: str) -> str | None:
    return f"C:/bin/{name}.exe"


def console(runner: FakeRunner, platform: str = "win32", which: object = which_all) -> SerialConsole:
    return SerialConsole(runner, platform=platform, which=which, now_ms=lambda: 1234)  # type: ignore[arg-type]


def test_probe_connected_returns_the_switch_text() -> None:
    runner = FakeRunner((0, b"NETVIEW:REPLY\n\r\n\x1b[2K\r\nUser:", ""))
    status = console(runner).probe(TARGET)
    assert (status.state, status.text, status.at_ms) == ("connected", "User:", 1234)
    argv = runner.ran[0]
    assert argv[:5] == ["C:/bin/ssh.exe", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    assert argv[5] == "root@192.168.1.36"
    assert argv[6] == probe_script(TARGET)
    assert len(argv) == 7


def test_probe_accepts_windows_line_ends_from_ssh() -> None:
    assert console(FakeRunner((0, b"NETVIEW:REPLY\r\nUser:", ""))).probe(TARGET).state == "connected"


def test_probe_silent_when_nothing_comes_back() -> None:
    assert console(FakeRunner((0, b"NETVIEW:REPLY\n\r\n \x00", ""))).probe(TARGET).state == "silent"


def test_probe_in_use_and_no_device() -> None:
    assert console(FakeRunner((0, b"NETVIEW:IN_USE\n", ""))).probe(TARGET).state == "in_use"
    status = console(FakeRunner((0, b"NETVIEW:NO_DEVICE\n", ""))).probe(TARGET)
    assert status.state == "no_device"
    assert "/dev/ttyS0" in status.detail


def test_probe_unreachable_reports_the_last_ssh_line() -> None:
    err = "Warning: something\nroot@192.168.1.36: Permission denied (publickey).\n"
    status = console(FakeRunner((255, b"", err))).probe(TARGET)
    assert status.state == "unreachable"
    assert status.detail == "root@192.168.1.36: Permission denied (publickey)."
    assert (
        console(FakeRunner((255, b"", ""))).probe(TARGET).detail == "ssh to 192.168.1.36 ended with code 255"
    )


def test_probe_never_raises_when_ssh_cannot_run() -> None:
    status = console(FakeRunner(ConsoleError("could not run ssh: not found"))).probe(TARGET)
    assert (status.state, status.detail) == ("unreachable", "could not run ssh: not found")


def test_a_reply_that_looks_like_a_marker_is_still_a_reply() -> None:
    status = console(FakeRunner((0, b"NETVIEW:REPLY\nNETVIEW:IN_USE\n", ""))).probe(TARGET)
    assert status.state == "connected"


def test_probe_script_checks_for_a_session_before_it_writes() -> None:
    script = probe_script(TARGET)
    assert '"' not in script
    assert "\n" not in script
    assert script.index(SESSION) < script.index("fuser") < script.index("stty") < script.index("printf")
    assert "stty -F /dev/ttyS0 38400 " in script
    assert script.count("printf") == 1


def test_clean_reply_keeps_printable_text_only() -> None:
    assert clean_reply(b"\r\n\x1b[1mUser:\x1b[0m\x07\r\n\r\n(GSM7248) >") == "User:\n(GSM7248) >"
    assert len(clean_reply(b"x" * 1000)) == 300


def test_open_starts_windows_terminal_with_a_fixed_command() -> None:
    runner = FakeRunner()
    console(runner).open(TARGET)
    assert runner.spawned == [
        [
            "C:/bin/wt.exe",
            "-w",
            "0",
            "new-tab",
            "--title",
            "GSM7248 console",
            "C:/bin/ssh.exe",
            "-t",
            "root@192.168.1.36",
            f"screen -D -R -S {SESSION} /dev/ttyS0 38400",
        ]
    ]


def test_open_is_refused_off_windows_or_without_wt() -> None:
    runner = FakeRunner()
    assert not console(runner, platform="linux").can_open()
    with pytest.raises(ConsoleError):
        console(runner, platform="linux").open(TARGET)
    no_wt = console(runner, which=lambda name: None if name == "wt" else "ssh")
    assert not no_wt.can_open()
    with pytest.raises(ConsoleError):
        no_wt.open(TARGET)
    assert runner.spawned == []


def test_settings_console_is_off_by_default() -> None:
    s = Gsm7248Settings()
    assert s.console_enabled is False
    assert s.console_target() is None


def test_settings_console_target() -> None:
    s = Gsm7248Settings(console_enabled=True)
    assert s.console_target() == ConsoleTarget("192.168.1.36", "root", "/dev/ttyS0", 38400)
    custom = Gsm7248Settings(
        console_enabled=True,
        console_ssh_host="pve.lan",
        console_ssh_user="ops",
        console_device="/dev/ttyUSB0",
        console_baud="9600",
    )
    assert custom.console_target() == ConsoleTarget("pve.lan", "ops", "/dev/ttyUSB0", 9600)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("console_ssh_host", "pve; rm -rf /"),
        ("console_ssh_host", "-oProxyCommand=calc"),
        ("console_ssh_host", "a b"),
        ("console_ssh_user", "root;id"),
        ("console_ssh_user", "-l"),
        ("console_ssh_user", "Root"),
        ("console_device", "/dev/ttyS0; reboot"),
        ("console_device", "/dev/../etc/passwd"),
        ("console_device", "/etc/passwd"),
        ("console_device", "/dev/tty S0"),
        ("console_baud", "38400; id"),
    ],
)
def test_settings_reject_values_that_could_change_the_command(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Gsm7248Settings(**{field: value})


def test_console_values_are_plain_tokens() -> None:
    target = Gsm7248Settings(console_enabled=True).console_target()
    assert target is not None
    for value in (target.host, target.user, target.device, str(target.baud)):
        assert re.fullmatch(r"[A-Za-z0-9_./-]+", value)
