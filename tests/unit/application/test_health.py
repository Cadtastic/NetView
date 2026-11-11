from collections.abc import Iterable
from ipaddress import IPv4Network

from usecase_helpers import SELF_IP, World, seen

from netview.application.capabilities import HealthTargets
from netview.application.queries.read_models import HostInfo
from netview.application.usecases.health import HealthTargetsQuery, PollHealth, WatchMonitor
from netview.domain.device import DeviceStatus
from netview.domain.events import EventKind
from netview.domain.samples import LatencySample
from netview.domain.watch import Watch, WatchProbe, WatchState, WatchStatus
from netview.sdk.testing.fakes import InMemoryMetrics

SUBNET = IPv4Network("192.168.1.0/24")
IP = "192.168.1.50"


def probe(
    ip: str = IP,
    t: int = 1000,
    ports: dict[int, str] | None = None,
    rtt: float | None = None,
    l2: bool | None = None,
) -> WatchProbe:
    return WatchProbe(ip, t, True, l2, None, rtt, ports or {})  # type: ignore[arg-type]


def up(t: int = 1000) -> WatchProbe:
    return probe(t=t, rtt=1.0)


def partly(t: int = 1000) -> WatchProbe:
    return probe(t=t, ports={22: "closed"}, rtt=1.0)


def add_watch(w: World, watch: Watch) -> None:
    with w.uow() as uow:
        uow.watches.add(watch)
        uow.commit()


def remove_watch(w: World, ip: str) -> None:
    with w.uow() as uow:
        uow.watches.remove(ip)
        uow.commit()


def monitor(w: World) -> WatchMonitor:
    return WatchMonitor(w.uow, w.bus, w.clock)


def only(m: WatchMonitor, w: World, ip: str = IP) -> WatchStatus:
    with w.uow() as uow:
        watches = uow.watches.list()
    return next(s for s in m.statuses(watches, SUBNET) if s.ip == ip)


def test_pending_to_up_writes_no_event() -> None:
    w = World()
    add_watch(w, Watch(IP, (), "NAS"))
    m = monitor(w)
    m.record([up()])
    assert only(m, w).state is WatchState.UP
    assert w.bus.published == []
    with w.uow() as uow:
        assert uow.events.recent() == []


def test_state_change_writes_one_watch_event_and_sets_since() -> None:
    w = World()
    add_watch(w, Watch(IP, (22,), "NAS"))
    m = monitor(w)
    m.record([probe(ports={22: "open"}, rtt=1.0, t=1000)])
    m.record([probe(ports={22: "closed"}, rtt=1.0, t=6000)])
    assert [e.kind for e in w.bus.published] == [EventKind.WATCH]
    event = w.bus.published[0]
    assert event.text == "NAS is now partly up (was up)"
    assert event.ip == IP
    status = only(m, w)
    assert status.state is WatchState.DEGRADED
    assert status.since_ms == 6000 and status.checked_ms == 6000
    assert status.history == (1, 0.5)
    with w.uow() as uow:
        assert [e.text for e in uow.events.recent()] == ["NAS is now partly up (was up)"]


def test_unlabelled_watch_uses_the_ip_in_the_event() -> None:
    w = World()
    add_watch(w, Watch(IP))
    m = monitor(w)
    m.record([up()])
    m.record([probe(t=2000)])
    assert w.bus.published[0].text == f"{IP} is now not on the network (was up)"


def test_pending_to_something_other_than_up_does_write_an_event() -> None:
    w = World()
    add_watch(w, Watch(IP, (), "NAS"))
    m = monitor(w)
    m.record([probe()])
    assert [e.text for e in w.bus.published] == ["NAS is now not on the network (was checking)"]


def test_same_state_again_writes_nothing_and_keeps_since() -> None:
    w = World()
    add_watch(w, Watch(IP))
    m = monitor(w)
    m.record([up(1000)])
    m.record([up(6000)])
    assert w.bus.published == []
    status = only(m, w)
    assert (status.since_ms, status.checked_ms) == (1000, 6000)


def _open(t: int) -> WatchProbe:
    return probe(t=t, ports={22: "open"}, rtt=1.0)


def test_history_is_capped_at_60() -> None:
    w = World()
    add_watch(w, Watch(IP, (22,)))
    m = monitor(w)
    for i in range(75):
        m.record([_open(i)])
    m.record([partly(100)])
    history = only(m, w).history
    assert len(history) == 60
    assert history[-1] == 0.5 and set(history[:-1]) == {1}


def test_history_values() -> None:
    w = World()
    add_watch(w, Watch(IP, (22,)))
    m = monitor(w)
    m.record([_open(1)])
    m.record([partly(2)])
    m.record([probe(t=3, ports={22: "filtered"})])
    assert only(m, w).history == (1, 0.5, 0)


def test_probe_for_an_unwatched_ip_is_ignored() -> None:
    w = World()
    add_watch(w, Watch(IP))
    m = monitor(w)
    m.record([probe(ip="192.168.1.99", rtt=1.0)])
    assert [s.ip for s in m.statuses([Watch(IP)], SUBNET)] == [IP]
    assert only(m, w).state is WatchState.PENDING
    assert w.bus.published == []


def test_removed_watch_disappears_and_readded_starts_pending() -> None:
    w = World()
    add_watch(w, Watch(IP))
    m = monitor(w)
    m.record([up()])
    remove_watch(w, IP)
    assert m.statuses([], SUBNET) == []
    m.record([up(2000)])  # a late result for the removed watch
    assert m.statuses([], SUBNET) == []
    add_watch(w, Watch(IP))
    status = only(m, w)
    assert status.state is WatchState.PENDING
    assert status.history == () and status.since_ms is None and status.checked_ms is None
    m.record([up(3000)])  # the first result after "checking" being up writes no event
    assert w.bus.published == []


def test_record_prunes_the_state_of_removed_watches() -> None:
    w = World()
    add_watch(w, Watch(IP))
    m = monitor(w)
    m.record([up()])
    remove_watch(w, IP)
    m.record([probe(ip="192.168.1.99")])  # any later call prunes against the current watches
    add_watch(w, Watch(IP))
    assert only(m, w).state is WatchState.PENDING


def test_changing_the_watched_ports_starts_over() -> None:
    w = World()
    add_watch(w, Watch(IP, (22,)))
    m = monitor(w)
    m.record([probe(ports={22: "open"}, rtt=1.0)])
    status = m.statuses([Watch(IP, (80,))], SUBNET)[0]
    assert status.state is WatchState.PENDING and status.ports == (80,)


def test_pending_status_details() -> None:
    m = monitor(World())
    statuses = m.statuses([Watch("192.168.1.9", (80,), "A"), Watch("10.1.1.1")], SUBNET)
    by_ip = {s.ip: s for s in statuses}
    s = by_ip["192.168.1.9"]
    assert s.state is WatchState.PENDING
    assert s.diagnosis == "Waiting for the first check."
    assert (s.label, s.ports, s.on_subnet, s.l2, s.mac, s.rtt_ms) == ("A", (80,), True, None, None, None)
    assert s.port_state == {} and s.history == ()
    assert by_ip["10.1.1.1"].on_subnet is False


def test_statuses_are_in_numeric_ip_order() -> None:
    m = monitor(World())
    watches = [Watch("192.168.1.10"), Watch("192.168.1.9"), Watch("192.168.1.100")]
    assert [s.ip for s in m.statuses(watches, SUBNET)] == ["192.168.1.9", "192.168.1.10", "192.168.1.100"]


def test_status_carries_the_probe_details() -> None:
    w = World()
    add_watch(w, Watch(IP, (22,)))
    m = monitor(w)
    m.record([WatchProbe(IP, 5000, True, True, "aa:bb:cc:dd:ee:01", 3.5, {22: "open"})])
    s = only(m, w)
    assert (s.l2, s.mac, s.rtt_ms, s.port_state) == (True, "aa:bb:cc:dd:ee:01", 3.5, {22: "open"})
    assert s.diagnosis == "Reachable: every watched port answers."


class _Provider:
    def __init__(self, items: Iterable[LatencySample | WatchProbe]) -> None:
        self.items = list(items)
        self.targets: HealthTargets | None = None

    def probe(self, targets: HealthTargets) -> Iterable[LatencySample | WatchProbe]:
        self.targets = targets
        return self.items


class _RecordingMonitor:
    def __init__(self) -> None:
        self.recorded: list[WatchProbe] = []

    def record(self, probes: Iterable[WatchProbe]) -> None:
        self.recorded.extend(probes)


def test_poll_health_stores_null_samples_and_hands_probes_on() -> None:
    metrics = InMemoryMetrics()
    spy = _RecordingMonitor()
    targets = HealthTargets(None, SUBNET, (), ())
    wp = probe()
    provider = _Provider(
        [LatencySample("health.gateway", 1, None), wp, LatencySample("health.internet", 1, 9.5)]
    )
    PollHealth(lambda: targets, metrics, spy)(provider)  # type: ignore[arg-type]
    assert metrics.series("health.gateway") == [(1, None)]
    assert metrics.series("health.internet") == [(1, 9.5)]
    assert spy.recorded == [wp]
    assert provider.targets is targets


def test_poll_health_with_a_real_monitor_ignores_unwatched_probes() -> None:
    w = World()
    metrics = InMemoryMetrics()
    provider = _Provider([probe(rtt=1.0)])
    PollHealth(lambda: HealthTargets(None, SUBNET, (), ()), metrics, monitor(w))(provider)
    assert metrics.names() == []
    assert w.bus.published == []


def host(gateway: str | None = "192.168.1.1") -> HostInfo:
    return HostInfo("h", SELF_IP, gateway, "192.168.1.0/24", "linux")


def test_targets_cap_at_64_online_devices_in_ip_order() -> None:
    w = World()
    w.record([seen(f"192.168.1.{i}", f"aa:bb:cc:00:00:{i:02x}") for i in range(2, 72)])
    targets = HealthTargetsQuery(w.uow, host, lambda: SUBNET)()
    assert len(targets.devices) == 64
    assert [ip for _, ip in targets.devices] == [f"192.168.1.{i}" for i in range(2, 66)]
    assert targets.devices[0] == ("aa:bb:cc:00:00:02", "192.168.1.2")
    assert targets.subnet == SUBNET and targets.gateway == "192.168.1.1" and targets.watches == ()


def test_targets_sort_by_numeric_ip_before_capping() -> None:
    w = World()
    w.record([seen("192.168.1.100", "aa:bb:cc:00:00:64"), seen("192.168.1.9", "aa:bb:cc:00:00:09")])
    targets = HealthTargetsQuery(w.uow, host, lambda: SUBNET)()
    assert [ip for _, ip in targets.devices] == ["192.168.1.9", "192.168.1.100"]


def test_targets_exclude_self_and_offline_devices() -> None:
    w = World()
    w.record(
        [
            seen("192.168.1.2", "aa:bb:cc:00:00:02"),
            seen(SELF_IP, None),
            seen("192.168.1.3", "aa:bb:cc:00:00:03"),
        ]
    )
    with w.uow() as uow:
        gone = uow.devices.get("aa:bb:cc:00:00:03")
        assert gone is not None
        gone.status = DeviceStatus.OFFLINE
        uow.devices.save(gone)
        uow.commit()
    targets = HealthTargetsQuery(w.uow, host, lambda: SUBNET)()
    assert targets.devices == (("aa:bb:cc:00:00:02", "192.168.1.2"),)


def test_targets_pass_a_missing_gateway_and_the_watches_through() -> None:
    w = World()
    add_watch(w, Watch(IP, (22,)))
    targets = HealthTargetsQuery(w.uow, lambda: host(None), lambda: SUBNET)()
    assert targets.gateway is None
    assert targets.watches == (Watch(IP, (22,)),)
