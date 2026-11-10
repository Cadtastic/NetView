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


class NoNetworkError(NetviewError):
    """This device has no usable LAN address, so a scan would only find phantom hosts."""

    def __init__(self, message: str = "no network: this device has no LAN address") -> None:
        super().__init__(message)


class ScanInProgressError(NetviewError):
    """A scan is already running; scans run one at a time."""

    def __init__(self, message: str = "scan already running") -> None:
        super().__init__(message)
