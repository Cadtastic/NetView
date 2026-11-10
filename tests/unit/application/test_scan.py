import logging
from collections.abc import Iterable
from ipaddress import IPv4Network

import pytest
from usecase_helpers import World, seen

from netview.application.capabilities import Capability
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.usecases.scan import RunScan
from netview.domain.device import DeviceStatus
from netview.domain.errors import CapabilityUnavailableError
from netview.domain.samples import Sighting

NET = IPv4Network("192.168.1.0/24")
MAC = "90:39:5f:00:00:01"


class _Provider:
    def __init__(self, sightings: list[Sighting]) -> None:
        self._s = sightings

    def discover(self, subnet: IPv4Network) -> Iterable[Sighting]:
        return self._s


class _Broken:
    def discover(self, subnet: IPv4Network) -> Iterable[Sighting]:
        raise RuntimeError("boom")


def _scan(w: World, *providers: object) -> RunScan:
    registry = CapabilityRegistry()
    for i, p in enumerate(providers):
        registry.register(f"p{i}", Capability.DISCOVERY, p)
    return RunScan(registry, w.record, lambda: NET, logging.getLogger("test"))


def test_run_scan_without_providers_raises_capability_unavailable() -> None:
    with pytest.raises(CapabilityUnavailableError):
        _scan(World())()


def test_run_scan_merges_two_providers() -> None:
    w = World()
    ping = _Provider([seen("192.168.1.10", None, rtt=2.0)])
    arp = _Provider(
        [
            seen("192.168.1.10", MAC, rtt=None),
            seen("192.168.1.11", "aa:bb:cc:00:00:02", rtt=None),
        ]
    )
    summary = _scan(w, ping, arp)()
    assert summary.seen == 2 and summary.replied == 1 and summary.quiet == 1
    with w.uow() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.status is DeviceStatus.ONLINE and d.rtt_ms == 2.0


def test_run_scan_all_providers_fail_keeps_status() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    summary = _scan(w, _Broken(), _Broken())()
    assert summary.went_offline == 0
    with w.uow() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.status is DeviceStatus.ONLINE


def test_run_scan_one_provider_fails_other_still_counts() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    summary = _scan(w, _Broken(), _Provider([]))()
    assert summary.went_offline == 1


def test_run_scan_with_empty_network_does_not_crash() -> None:
    w = World()
    summary = _scan(w, _Provider([]))()
    assert summary.seen == 0
