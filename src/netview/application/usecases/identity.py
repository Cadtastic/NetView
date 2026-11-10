"""Record name claims, type claims and hints."""

from collections.abc import Sequence

from netview.application.ports.event_bus import EventBus
from netview.application.ports.uow import UnitOfWorkFactory
from netview.domain.events import DomainEvent, EventKind
from netview.domain.naming import Hint, NameClaim, TypeClaim, best_claim


class ClaimIdentity:
    def __init__(self, uow: UnitOfWorkFactory, bus: EventBus) -> None:
        self._uow = uow
        self._bus = bus

    def __call__(self, items: Sequence[NameClaim | TypeClaim | Hint]) -> None:
        events: list[DomainEvent] = []
        with self._uow() as uow:
            keys = {i.key for i in items}
            before_name: dict[str, str | None] = {}
            before_type: dict[str, str | None] = {}
            for k in keys:
                best = best_claim(uow.identity.claims(k))
                before_name[k] = best.name if best else None
                types = uow.identity.types(k)
                before_type[k] = types[-1].type if types else None

            newest_type: dict[str, str] = {}
            hints: dict[tuple[str, str], list[Hint]] = {}
            for item in items:
                if isinstance(item, NameClaim):
                    uow.identity.upsert_claim(item)
                elif isinstance(item, TypeClaim):
                    uow.identity.upsert_type(item)
                    newest_type[item.key] = item.type
                else:
                    hints.setdefault((item.key, item.source), []).append(item)
            for (key, source), group in hints.items():
                uow.identity.replace_hints(key, source, group)

            for key in sorted(keys):
                device = uow.devices.get(key)
                ip = device.ip if device else None
                after = best_claim(uow.identity.claims(key))
                if after is not None and after.name != before_name[key]:
                    events.append(
                        DomainEvent(
                            EventKind.NAME,
                            f"{ip or key} is named {after.name} ({after.source})",
                            after.checked_ms,
                            ip,
                            key,
                        )
                    )
                new_type = newest_type.get(key)
                if new_type is not None and new_type != before_type[key]:
                    t_ms = after.checked_ms if after else 0
                    events.append(
                        DomainEvent(EventKind.TYPE, f"{ip or key} looks like a {new_type}", t_ms, ip, key)
                    )
            for e in events:
                uow.events.add(e)
            uow.commit()
        for e in events:
            self._bus.publish(e)
