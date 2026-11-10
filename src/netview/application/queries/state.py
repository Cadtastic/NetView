"""Queries that assemble read models from the repositories."""

import ipaddress
from collections.abc import Callable

from netview.application.capabilities import Capability
from netview.application.plugins.jobs import Scheduler
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.ports.uow import UnitOfWork, UnitOfWorkFactory
from netview.application.ports.vendor import VendorLookup
from netview.application.queries.read_models import DeviceView, HostInfo, NetworkState
from netview.domain.device import Device
from netview.domain.errors import NotFoundError
from netview.domain.naming import NameClaim, best_claim, display_name
from netview.domain.watch import Watch

_EVENT_LIMIT = 300


def build_device_view(
    uow: UnitOfWork,
    device: Device,
    vendors: VendorLookup | None = None,
    claims: dict[str, list[NameClaim]] | None = None,
    nicknames: dict[str, str] | None = None,
    watches: list[Watch] | None = None,
) -> DeviceView:
    """Join a device with its nickname, claims, hints and watch.

    Lists of devices pass ``claims``, ``nicknames`` and ``watches`` loaded once; a single device
    loads its own. The vendor is looked up at read time when none is stored.
    """
    key = device.key
    nickname = nicknames.get(key) if nicknames is not None else uow.nicknames.get(key)
    key_claims = claims.get(key, []) if claims is not None else uow.identity.claims(key)
    best = best_claim(key_claims)
    types = uow.identity.types(key)
    watch = next(
        (w for w in (watches if watches is not None else uow.watches.list()) if w.ip == device.ip), None
    )
    vendor = device.vendor or (vendors.vendor(device.mac) if vendors is not None and device.mac else "")
    return DeviceView(
        key=key,
        ip=device.ip,
        mac=device.mac,
        vendor=vendor,
        nickname=nickname,
        device_name=best.name if best else "",
        name_source=best.source if best else "",
        type=types[-1].type if types else "",
        hints=[h.text for h in uow.identity.hints(key)],
        status=device.status.value,
        rtt_ms=device.rtt_ms,
        ttl=device.ttl,
        first_seen_ms=device.first_seen_ms,
        last_seen_ms=device.last_seen_ms,
        is_new=device.is_new,
        is_self=device.is_self,
        watched=watch is not None,
        display_name=display_name(nickname, best, watch.label if watch else None),
    )


def _ip_sort_key(ip: str) -> tuple[int, int, str]:
    try:
        return (0, int(ipaddress.IPv4Address(ip)), ip)
    except ValueError:
        return (1, 0, ip)


class GetNetworkState:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        registry: CapabilityRegistry,
        scheduler: Scheduler,
        host: Callable[[], HostInfo],
        vendors: VendorLookup | None = None,
    ) -> None:
        self._uow = uow
        self._registry = registry
        self._scheduler = scheduler
        self._host = host
        self._vendors = vendors

    def __call__(self) -> NetworkState:
        with self._uow() as uow:
            watches = uow.watches.list()
            devices = sorted(uow.devices.list(), key=lambda d: _ip_sort_key(d.ip))
            claims = uow.identity.all_claims()
            nicknames = uow.nicknames.all()
            views = [build_device_view(uow, d, self._vendors, claims, nicknames, watches) for d in devices]
            events = uow.events.recent(_EVENT_LIMIT)
        capabilities = [c.value for c in Capability if self._registry.providers(c)]
        return NetworkState(
            host=self._host(),
            devices=views,
            events=events,
            watches=watches,
            capabilities=capabilities,
            jobs=self._scheduler.status(),
        )


class GetDevice:
    def __init__(self, uow: UnitOfWorkFactory, vendors: VendorLookup | None = None) -> None:
        self._uow = uow
        self._vendors = vendors

    def __call__(self, key: str) -> DeviceView:
        with self._uow() as uow:
            device = uow.devices.get(key)
            if device is None:
                raise NotFoundError(f"no device with key {key!r}")
            return build_device_view(uow, device, self._vendors)
