"""AppServices: everything the presentation layer may touch."""

from collections.abc import Callable
from dataclasses import dataclass

from netview.application.plugins.jobs import Scheduler
from netview.application.ports.event_bus import EventBus
from netview.application.ports.metrics import MetricsStore
from netview.application.ports.plugin_admin import PluginAdmin
from netview.application.ports.state_notifier import StateNotifier
from netview.application.ports.themes import ThemeCatalog
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.usecases.forget import ForgetDevice
from netview.application.usecases.inspection import RunInspection
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.plugin_catalog import PluginCatalogService
from netview.application.usecases.scan import RunScan
from netview.application.usecases.watches import AddWatch, RemoveWatch
from netview.domain.events import DomainEvent
from netview.domain.inspection import InspectionReport


@dataclass
class AppServices:
    state: GetNetworkState
    device: GetDevice
    set_nickname: SetNickname
    forget_device: ForgetDevice
    add_watch: AddWatch
    remove_watch: RemoveWatch
    run_scan: RunScan
    run_inspection: RunInspection
    events: Callable[[int], list[DomainEvent]]
    latest_inspection: Callable[[str], InspectionReport | None]
    plugins: PluginAdmin
    bus: EventBus
    scheduler: Scheduler
    notifier: StateNotifier
    themes: ThemeCatalog
    metrics: MetricsStore
    catalog: PluginCatalogService
