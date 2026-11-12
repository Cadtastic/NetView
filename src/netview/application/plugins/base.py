"""Plugin base class."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

from netview.application.capabilities import Capability
from netview.application.plugins.context import PluginContext
from netview.application.plugins.jobs import JobSpec
from netview.application.plugins.manifest import PluginManifest
from netview.application.plugins.ui import StorageSpec, UiContribution
from netview.application.plugins.user_permissions import UserPermission


class Plugin(ABC):
    manifest: ClassVar[PluginManifest]
    settings_model: ClassVar[type[Any] | None] = None
    """A pydantic BaseModel subclass."""

    user_permissions: ClassVar[tuple[UserPermission, ...]] = ()
    """What users may do in this plugin, beyond the automatic view, use and configure (SDK 1.5)."""

    settings: Any = None

    @abstractmethod
    def setup(self, ctx: PluginContext) -> None: ...

    def shutdown(self) -> None:
        return None

    def providers(self) -> Mapping[Capability, object]:
        return {}

    def jobs(self) -> list[JobSpec]:
        return []

    def router(self) -> Any | None:
        """A FastAPI APIRouter."""
        return None

    def ui(self) -> UiContribution | None:
        return None

    def storage(self) -> StorageSpec | None:
        return None

    def on_settings_changed(self, settings: Any) -> None:
        self.settings = settings
