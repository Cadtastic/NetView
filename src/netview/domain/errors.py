"""Domain errors."""


class NetviewError(Exception):
    """Base class for all NetView errors."""


class ValidationError(NetviewError):
    """Input failed a domain rule.

    ``fields`` maps a field name to its own message when the input was a form (plugin settings),
    so a client can show each message next to its field.
    """

    def __init__(self, message: str = "", fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.fields: dict[str, str] = dict(fields or {})


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


class ConflictError(NetviewError):
    """The request conflicts with the current state (for example a plugin that is not loaded yet)."""


class CatalogUnavailableError(NetviewError):
    """The plugin catalog could not be fetched or read."""


class InstallError(NetviewError):
    """A plugin could not be installed."""


class AuthenticationError(NetviewError):
    """The caller is not signed in, or the credentials are wrong."""


class PermissionDeniedError(NetviewError):
    """The caller is signed in but lacks the permission."""


class SetupRequiredError(NetviewError):
    """First-run setup has not been completed."""

    def __init__(self, message: str = "setup required") -> None:
        super().__init__(message)


class TooManyAttemptsError(NetviewError):
    """Too many failed sign-in attempts; try again later."""

    def __init__(self, message: str = "Too many attempts. Try again later.") -> None:
        super().__init__(message)
