"""Capability registry."""

from netview.application.capabilities import Capability
from netview.domain.errors import CapabilityUnavailableError


class CapabilityRegistry:
    def __init__(self) -> None:
        self._entries: list[tuple[str, Capability, object]] = []

    def register(self, plugin_id: str, capability: Capability, provider: object) -> None:
        self._entries.append((plugin_id, capability, provider))

    def providers(self, capability: Capability) -> list[tuple[str, object]]:
        return [(pid, prov) for pid, cap, prov in self._entries if cap == capability]

    def require(self, capability: Capability) -> list[tuple[str, object]]:
        found = self.providers(capability)
        if not found:
            raise CapabilityUnavailableError(capability.value)
        return found

    def unregister_plugin(self, plugin_id: str) -> None:
        self._entries = [e for e in self._entries if e[0] != plugin_id]
