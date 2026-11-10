"""Shared helper: the label used in event texts."""

from netview.application.ports.uow import UnitOfWork
from netview.domain.naming import best_claim, display_name


def label_for(uow: UnitOfWork, key: str) -> str:
    """Display name for a key (nickname, best claim, watch label), or '' when none."""
    device = uow.devices.get(key)
    watch_label = None
    if device is not None:
        watch_label = next((w.label for w in uow.watches.list() if w.ip == device.ip), None)
    return display_name(uow.nicknames.get(key), best_claim(uow.identity.claims(key)), watch_label)
