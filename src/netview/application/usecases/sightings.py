"""Record a batch of discovery sightings into the device table."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.uow import UnitOfWork, UnitOfWorkFactory
from netview.application.ports.vendor import VendorLookup
from netview.application.usecases._display import LabelResolver
from netview.domain.device import Device, DeviceStatus
from netview.domain.errors import NoNetworkError
from netview.domain.events import DomainEvent, EventKind
from netview.domain.keys import SELF_KEY, key_for, norm_mac
from netview.domain.network import has_lan_address
from netview.domain.nickname import NicknameChange
from netview.domain.samples import Sighting


@dataclass(frozen=True)
class SweepSummary:
    seen: int
    replied: int
    quiet: int
    went_offline: int
    new: int
    duration_ms: int


class RecordSightings:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        vendors: VendorLookup,
        bus: EventBus,
        self_ip: Callable[[], str],
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._vendors = vendors
        self._bus = bus
        self._self_ip = self_ip
        self._first = True

    @staticmethod
    def _already_reported(uow: UnitOfWork, pending: list[DomainEvent], ip: str, new_owner: str) -> bool:
        """True when the newest CONFLICT event for this address already names the new owner.

        ``pending`` holds this batch's events, which are not stored yet.
        """
        last = next(
            (e for e in reversed(pending) if e.kind is EventKind.CONFLICT and e.ip == ip),
            None,
        ) or uow.events.last(EventKind.CONFLICT, ip)
        return last is not None and last.key == new_owner

    def __call__(self, sightings: Sequence[Sighting], complete_sweep: bool = True) -> SweepSummary:
        own_ip = self._self_ip()
        if not has_lan_address(own_ip):
            raise NoNetworkError()
        started = self._clock.now_ms()
        first = self._first
        events: list[DomainEvent] = []
        seen: set[str] = set()
        replied = quiet = new = offline = 0

        with self._uow() as uow:
            labels = LabelResolver(uow)
            for s in sightings:
                is_self = s.ip == own_ip
                mac = None if is_self else (norm_mac(s.mac) if s.mac else None)
                if not is_self and s.rtt_ms is None and mac is None:
                    continue
                key = key_for(s.ip, mac, is_self)
                ts = s.seen_ms

                ip_key = f"ip:{s.ip}"
                if mac is not None:
                    old = uow.devices.get(ip_key)
                    if old is not None:
                        # MAC learned later: fold the ip-keyed record into the MAC key.
                        ip_nick = uow.nicknames.get(ip_key)
                        mac_nick = uow.nicknames.get(mac)
                        uow.devices.remove(ip_key)
                        uow.identity.rekey(ip_key, mac)
                        uow.nicknames.rekey(ip_key, mac)
                        existing = uow.devices.get(mac)
                        if existing is None:
                            old.key = mac
                            old.mac = mac
                            uow.devices.add(old)
                        elif old.first_seen_ms < existing.first_seen_ms:
                            existing.first_seen_ms = old.first_seen_ms
                            uow.devices.save(existing)
                        if ip_nick and mac_nick and ip_nick != mac_nick:
                            # the MAC key's nickname wins; leave a trace of the one that was dropped
                            uow.nicknames.add_history(
                                NicknameChange(
                                    mac,
                                    mac_nick,
                                    mac_nick,
                                    f"merge: dropped ip-key nickname '{ip_nick}'",
                                    self._clock.now_ms(),
                                )
                            )
                        labels.reset()

                owner = uow.devices.get_by_ip(s.ip)
                device = uow.devices.get(key)
                if (
                    owner is not None
                    and owner.key != key
                    and owner.key != SELF_KEY
                    and not owner.key.startswith("ip:")
                    and owner.status != DeviceStatus.OFFLINE
                    and mac is not None
                    and not self._already_reported(uow, events, s.ip, key)
                ):
                    events.append(
                        DomainEvent(
                            EventKind.CONFLICT,
                            f"{s.ip} now answers from {mac} (was {owner.key}). "
                            "Two devices may share this address.",
                            ts,
                            s.ip,
                            key,
                        )
                    )

                status = DeviceStatus.ONLINE if s.rtt_ms is not None else DeviceStatus.QUIET
                if device is None:
                    is_new = not first and key != SELF_KEY
                    device = Device(
                        key=key,
                        ip=s.ip,
                        mac=mac,
                        vendor=self._vendors.vendor(mac),
                        first_seen_ms=ts,
                        last_seen_ms=ts,
                        status=status,
                        is_new=is_new,
                    )
                    uow.devices.add(device)
                    if is_new:
                        new += 1
                        text = f"New device {s.ip} {mac or ''} {device.vendor}".strip()
                        events.append(DomainEvent(EventKind.NEW, text, ts, s.ip, key))
                elif device.ip != s.ip:
                    name = labels.label(key, device.ip) or key
                    events.append(
                        DomainEvent(EventKind.MOVED, f"{name} moved {device.ip} -> {s.ip}", ts, s.ip, key)
                    )
                elif device.status == DeviceStatus.OFFLINE and not first:
                    name = labels.label(key, device.ip) or s.ip
                    events.append(DomainEvent(EventKind.ONLINE, f"{name} is back", ts, s.ip, key))

                device.ip = s.ip
                device.mac = mac
                device.rtt_ms = s.rtt_ms
                device.ttl = s.ttl if s.rtt_ms is not None else None
                device.status = status
                device.last_seen_ms = ts
                device.missed = 0
                device.is_self = is_self
                device.vendor = device.vendor or self._vendors.vendor(mac)
                uow.devices.save(device)
                seen.add(key)
                if s.rtt_ms is not None:
                    replied += 1
                else:
                    quiet += 1

            if complete_sweep:
                now = self._clock.now_ms()
                for device in uow.devices.list():
                    if device.key in seen:
                        continue
                    device.missed += 1
                    if device.status != DeviceStatus.OFFLINE:
                        device.status = DeviceStatus.OFFLINE
                        device.rtt_ms = None
                        offline += 1
                        name = labels.label(device.key, device.ip) or device.ip
                        events.append(
                            DomainEvent(
                                EventKind.OFFLINE,
                                f"{name} went offline",
                                now,
                                device.ip,
                                device.key,
                            )
                        )
                    uow.devices.save(device)

            for e in events:
                uow.events.add(e)
            uow.commit()

        if complete_sweep:
            self._first = False  # a partial batch from a plugin does not end the first sweep
        for e in events:
            self._bus.publish(e)
        return SweepSummary(
            seen=len(seen),
            replied=replied,
            quiet=quiet,
            went_offline=offline,
            new=new,
            duration_ms=self._clock.now_ms() - started,
        )
