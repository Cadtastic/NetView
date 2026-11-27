from pathlib import Path

from netview.application.ports.network import TraceHop
from netview.infrastructure.net import traceroute as tr

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "net" / "traceroute"


def _feed(name: str, parse) -> list[TraceHop]:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [hop for line in text.splitlines() if (hop := parse(line)) is not None]


def test_tracert_reached_hops_and_rtts():
    hops = _feed("tracert_win_reached.txt", tr.parse_windows_line)
    assert len(hops) == 10
    assert hops[0].ip == "10.27.10.1"
    assert hops[0].rtts_ms == (0.5, 0.5, 0.5)
    assert hops[2].rtts_ms == (30.0, 23.0, 24.0)
    assert hops[-1].ip == "1.1.1.1"


def test_tracert_silent_tail_marks_hops_none():
    hops = _feed("tracert_win_unreachable_target.txt", tr.parse_windows_line)
    assert len(hops) == 30
    assert hops[-1] == TraceHop(30, None, (None, None, None))
    mid = _feed("tracert_win_silent_tail.txt", tr.parse_windows_line)
    assert [h.n for h in mid if h.ip is None] == [8, 9, 12, 13, 14, 15]
    assert mid[-1].ip == "150.171.110.9"


def test_tracert_unreachable_target_not_reached():
    hops = _feed("tracert_win_unreachable_target.txt", tr.parse_windows_line)
    assert tr.reached("192.0.2.1", hops) is False
    assert tr.reached("1.1.1.1", _feed("tracert_win_reached.txt", tr.parse_windows_line)) is True


def test_tracert_ipv6_rows_parse():
    hops = _feed("tracert_win_ipv6.txt", tr.parse_windows_line)
    assert [h.ip for h in hops] == ["fd27:cad:1::1", "2001:db8:100::1", None, "2606:4700:4700::1111"]
    assert tr.reached("2606:4700:4700::1111", hops) is True


def test_tracert_no_route_is_a_hop_without_ip_or_rtts():
    hops = _feed("tracert_win_ipv6_no_route.txt", tr.parse_windows_line)
    assert hops == [TraceHop(1, None, ())]
    assert tr.reached("2606:4700:4700::1111", hops) is False


def test_traceroute_linux_reached():
    hops = _feed("traceroute_linux_reached.txt", tr.parse_traceroute_line)
    assert len(hops) == 8
    assert hops[0].rtts_ms == (0.412, 0.388, 0.371)
    assert hops[4] == TraceHop(5, None, (None, None, None))
    assert tr.reached("1.1.1.1", hops)


def test_traceroute_multi_ip_row_takes_first_ip_and_three_rtts():
    hops = {h.n: h for h in _feed("traceroute_linux_multi_ip.txt", tr.parse_traceroute_line)}
    assert hops[6].ip == "206.224.69.51"
    assert hops[6].rtts_ms == (23.411, 22.975, 23.204)
    assert hops[4].rtts_ms == (25.031, None, 24.66)
    assert hops[8].ip == "203.0.113.9"
    assert hops[8].rtts_ms == (30.112, 29.804, 30.051)


def test_tracepath_rows_and_localhost_ignored():
    hops = _feed("tracepath_linux.txt", tr.parse_tracepath_line)
    assert [h.n for h in hops] == [1, 1, 2, 3, 4, 5, 6]
    assert hops[4] == TraceHop(4, None, (None,))
    assert hops[5].ip == "206.224.69.51"
    assert hops[5].rtts_ms == (23.411,)
    assert tr.parse_tracepath_line(" 1?: [LOCALHOST]                      pmtu 1500") is None


def test_header_and_footer_lines_are_ignored():
    for line in ("Tracing route to 1.1.1.1 over a maximum of 30 hops", "Trace complete.", "", "# note"):
        assert tr.parse_windows_line(line) is None
    assert tr.parse_traceroute_line("traceroute to 1.1.1.1 (1.1.1.1), 30 hops max, 60 byte packets") is None
    assert tr.parse_tracepath_line("     Resume: pmtu 1500 hops 6 back 6") is None


def test_commands_and_clamping():
    win = tr.windows_command("2001:db8::1", 500, 1)
    assert win[0].upper().endswith("TRACERT.EXE")
    assert win[1:] == ["-d", "-h", "64", "-w", "100", "-6", "2001:db8::1"]
    assert tr.windows_command("1.1.1.1", 30, 1000)[-2:] == ["-4", "1.1.1.1"]
    expected = ["traceroute", "-n", "-m", "1", "-w", "1", "-q", "3", "1.1.1.1"]
    assert tr.linux_command("1.1.1.1", 0, 1400) == expected
    assert tr.linux_command("::1", 30, 5000)[-2:] == ["-6", "::1"]
    assert tr.tracepath_command("::1", 30) == ["tracepath", "-n", "-m", "30", "-6", "::1"]
    assert tr.run_timeout(30, 1000) == 30 * 3 * 1.0 + 10
