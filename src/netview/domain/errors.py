"""Domain errors."""


class NetviewError(Exception):
    """Base class for all netview errors."""


class ValidationError(NetviewError):
    """Input failed a domain rule."""


class NotFoundError(NetviewError):
    """A requested entity does not exist."""


class CapabilityUnavailableError(NetviewError):
    """No enabled plugin provides the requested capability."""

    def __init__(self, capability: str) -> None:
        super().__init__(f"no enabled plugin provides {capability}")
        self.capability = capability
