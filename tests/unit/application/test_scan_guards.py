import logging
import threading
from collections.abc import Iterable
from ipaddress import IPv4Network

import pytest
from usecase_helpers import World, seen

from netview.application.capabilities import Capability
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.usecases.scan import RunScan
from netview.domain.device import DeviceStatus
from netview.domain.errors import NoNetworkError, ScanInProgressError
from netview.domain.samples import Sighting

NET = IPv4Network("192.168.1.0/24")
MAC = "90:39:5f:00:00:01"


class _Provider:
    def __init__(self, sightings: list[Sighting]) -> None:
        self._s = sightings
        self.calls = 0

    def discover(self, subnet: IPv4Network) -> Iterable[Sighting]:
        self.calls += 1
        return self._s


class _Blocking:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def discover(self, subnet: IPv4Network) -> Iterable[Sighting]:
        self.entered.set()
        self.release.wait(5)
        return []


def _scan(w: World, local_ip: str | None, *providers: object) -> RunScan:
    registry = CapabilityRegistry()
    for i, p in enumerate(providers):
        registry.register(f"p{i}", Capability.DISCOVERY, p)
    local = None if local_ip is None else (lambda: local_ip)
    return RunScan(registry, w.record, lambda: NET, logging.getLogger("test"), local)


@pytest.mark.parametrize("local", ["127.0.0.1", "127.8.9.10", "169.254.3.4", "0.0.0.0", "garbage"])
def test_scan_without_lan_address_raises_no_network(local: str) -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    ping_all = _Provider([seen(f"127.0.0.{i}", None, rtt=1.0) for i in range(1, 6)])
    with pytest.raises(NoNetworkError):
        _scan(w, local, ping_all)()
    assert ping_all.calls == 0
    with w.uow() as uow:
        assert [d.key for d in uow.devices.list()] == [MAC]
        d = uow.devices.get(MAC)
        assert d is not None and d.status is DeviceStatus.ONLINE
        assert uow.events.recent() == []


def test_scan_with_lan_address_runs() -> None:
    w = World()
    assert _scan(w, "192.168.1.95", _Provider([seen("192.168.1.10", MAC)]))().seen == 1


def test_second_scan_while_one_runs_raises_in_progress_and_lock_is_released() -> None:
    w = World()
    blocking = _Blocking()
    scan = _scan(w, None, blocking)
    result: list[object] = []
    worker = threading.Thread(target=lambda: result.append(scan()))
    worker.start()
    assert blocking.entered.wait(5)
    with pytest.raises(ScanInProgressError):
        scan()
    blocking.release.set()
    worker.join(5)
    assert len(result) == 1
    scan()  # the lock was released


def test_lock_is_released_when_a_scan_fails() -> None:
    w = World()
    scan = _scan(w, "127.0.0.1", _Provider([]))
    for _ in range(2):
        with pytest.raises(NoNetworkError):
            scan()
