"""Run a discovery sweep through every discovery provider."""

import logging
import threading
from collections.abc import Callable
from ipaddress import IPv4Network
from typing import cast

from netview.application.capabilities import Capability, DiscoveryProvider
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.usecases.sightings import RecordSightings, SweepSummary
from netview.domain.errors import NoNetworkError, ScanInProgressError
from netview.domain.network import has_lan_address
from netview.domain.samples import Sighting


class RunScan:
    """One sweep at a time. ``local_ip`` (when given) is checked before any provider is called."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        record: RecordSightings,
        subnet: Callable[[], IPv4Network],
        log: logging.Logger,
        local_ip: Callable[[], str] | None = None,
    ) -> None:
        self._registry = registry
        self._record = record
        self._subnet = subnet
        self._log = log
        self._local_ip = local_ip
        self._lock = threading.Lock()

    def __call__(self) -> SweepSummary:
        if not self._lock.acquire(blocking=False):
            raise ScanInProgressError()
        try:
            return self._sweep()
        finally:
            self._lock.release()

    def _sweep(self) -> SweepSummary:
        providers = self._registry.require(Capability.DISCOVERY)
        if self._local_ip is not None and not has_lan_address(self._local_ip()):
            raise NoNetworkError()
        net = self._subnet()
        merged: dict[str, Sighting] = {}
        failed = 0
        for plugin_id, provider in providers:
            try:
                found = list(cast(DiscoveryProvider, provider).discover(net))
            except Exception:
                failed += 1
                self._log.exception("discovery provider %s failed", plugin_id)
                continue
            for s in found:
                prev = merged.get(s.ip)
                merged[s.ip] = s if prev is None else _merge(prev, s)
        return self._record(list(merged.values()), complete_sweep=failed < len(providers))


def _merge(a: Sighting, b: Sighting) -> Sighting:
    replied = a if a.rtt_ms is not None else b
    return Sighting(
        ip=a.ip,
        mac=a.mac if a.mac is not None else b.mac,
        rtt_ms=replied.rtt_ms,
        ttl=replied.ttl if replied.ttl is not None else (a.ttl or b.ttl),
        seen_ms=max(a.seen_ms, b.seen_ms),
    )
