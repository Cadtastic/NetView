"""Hand devices to identity providers on a schedule and record what they claim."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from netview.application.ports.clock import Clock
from netview.application.usecases.identity import ClaimIdentity

if TYPE_CHECKING:
    from netview.application.capabilities import IdentityProvider
    from netview.application.queries.read_models import DeviceView

MAX_PER_RUN = 128  # LM 1650


class PollIdentity:
    """One run per provider: the devices checked longest ago (or never) go first."""

    def __init__(
        self, devices: Callable[[], list[DeviceView]], claim: ClaimIdentity, clock: Clock
    ) -> None:
        self._devices = devices
        self._claim = claim
        self._clock = clock
        self._lock = threading.Lock()
        self._checked_s: dict[tuple[str, str], float] = {}  # (plugin id, device key) -> checked at

    def __call__(self, plugin_id: str, provider: IdentityProvider) -> None:
        now_s = self._clock.now_ms() / 1000
        with self._lock:
            eligible = [
                d
                for d in self._devices()
                if not d.is_self
                and d.status != "offline"
                and now_s - self._checked_s.get((plugin_id, d.key), float("-inf")) >= provider.recheck_after_s
            ]
            eligible.sort(key=lambda d: self._checked_s.get((plugin_id, d.key), float("-inf")))
            picked = eligible[:MAX_PER_RUN]
        if not picked:
            return
        claims = list(provider.identify(picked))
        with self._lock:
            for d in picked:
                self._checked_s[(plugin_id, d.key)] = now_s
        if claims:
            self._claim(claims)
