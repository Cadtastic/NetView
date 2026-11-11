from netview.domain.watch import WATCH_LABELS, Watch, WatchProbe, WatchState, assess_watch

IP = "192.168.1.50"


def probe(
    ports: dict[int, str] | None = None,
    rtt: float | None = None,
    l2: bool | None = None,
    on_subnet: bool = True,
) -> WatchProbe:
    return WatchProbe(IP, 1000, on_subnet, l2, None, rtt, ports or {})  # type: ignore[arg-type]


def test_every_port_open_is_up() -> None:
    w = Watch(IP, (443, 22))
    state, diag = assess_watch(w, probe({443: "open", 22: "open"}))
    assert state is WatchState.UP
    assert diag == "Reachable: every watched port answers."


def test_no_ports_and_ping_reply_is_up() -> None:
    state, diag = assess_watch(Watch(IP), probe(rtt=1.2))
    assert state is WatchState.UP
    assert diag == "Reachable: answers ping."


def test_zero_rtt_still_counts_as_a_reply() -> None:
    assert assess_watch(Watch(IP), probe(rtt=0.0))[0] is WatchState.UP


def test_some_ports_open_is_degraded_and_names_the_closed_port() -> None:
    state, diag = assess_watch(Watch(IP, (443, 22)), probe({443: "open", 22: "filtered"}))
    assert state is WatchState.DEGRADED
    assert "port 22 is not open" in diag
    assert diag.startswith("Host answers, but port 22 is not open.")


def test_several_closed_ports_use_the_plural() -> None:
    _, diag = assess_watch(Watch(IP, (80, 443, 22)), probe({80: "open", 443: "closed", 22: "closed"}))
    assert "port 443, 22 are not open" in diag


def test_ping_reply_with_no_open_port_is_degraded() -> None:
    state, _ = assess_watch(Watch(IP, (22,)), probe({22: "filtered"}, rtt=2.0))
    assert state is WatchState.DEGRADED


def test_refused_port_means_the_host_answers() -> None:
    assert assess_watch(Watch(IP, (22,)), probe({22: "closed"}))[0] is WatchState.DEGRADED


def test_arp_only_is_present() -> None:
    state, diag = assess_watch(Watch(IP, (22,)), probe({22: "filtered"}, l2=True))
    assert state is WatchState.PRESENT
    assert diag.startswith("Answers ARP, so it is on this network")


def test_nothing_on_the_subnet_is_absent() -> None:
    state, diag = assess_watch(Watch(IP), probe(l2=False))
    assert state is WatchState.ABSENT
    assert "isn't on this network segment" in diag


def test_nothing_outside_the_subnet_is_down() -> None:
    state, diag = assess_watch(Watch(IP), probe(on_subnet=False))
    assert state is WatchState.DOWN
    assert diag == "No reply. This address is outside the local subnet, so the gateway must route to it."


def test_labels() -> None:
    assert WATCH_LABELS[WatchState.PENDING] == "checking"
    assert WATCH_LABELS[WatchState.DEGRADED] == "partly up"
    assert WATCH_LABELS[WatchState.PRESENT] == "on the network only"
    assert WATCH_LABELS[WatchState.ABSENT] == "not on the network"
    assert WATCH_LABELS[WatchState.DOWN] == "not replying"
    assert {s.value for s in WatchState} == {"pending", "up", "degraded", "present", "absent", "down"}
