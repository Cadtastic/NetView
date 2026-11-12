"""Builders for the API tests: AppServices wired from in-memory fakes."""

import logging
import uuid
from dataclasses import dataclass, replace
from ipaddress import IPv4Network
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netview.application.auth.catalog import build_catalog
from netview.application.auth.principal import SYSTEM_PRINCIPAL
from netview.application.plugins.plugin_json import CatalogEntry, PluginIndex, PluginJson, build_index
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.ports.plugin_admin import PluginInfo
from netview.application.ports.plugin_catalog import CatalogSnapshot, Progress
from netview.application.ports.themes import ThemeCatalog, ThemeInfo
from netview.application.queries.read_models import HostInfo
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.services import AppServices, AuthServices
from netview.application.usecases.auth.admin import PolicyAdmin, RoleAdmin, UserAdmin
from netview.application.usecases.auth.sessions import Authorizer, SessionService
from netview.application.usecases.auth.setup import SetupService
from netview.application.usecases.auth.sign_in import ChangeOwnPassword, LoginThrottle, SignIn
from netview.application.usecases.forget import ForgetDevice
from netview.application.usecases.health import WatchMonitor
from netview.application.usecases.inspection import RunInspection
from netview.application.usecases.install_plugin import InstallJobs
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.plugin_catalog import PluginCatalogService
from netview.application.usecases.scan import RunScan
from netview.application.usecases.sightings import RecordSightings
from netview.application.usecases.traffic import TrafficLedger
from netview.application.usecases.watches import AddWatch, RemoveWatch
from netview.domain.auth import ADMIN_ROLE, User
from netview.domain.errors import CatalogUnavailableError, ConflictError, NotFoundError, ValidationError
from netview.domain.samples import Sighting
from netview.infrastructure.auth.memory_store import InMemoryAuthStore
from netview.infrastructure.event_bus import InMemoryEventBus
from netview.infrastructure.metrics import LONG_MAXLEN, LONG_PREFIXES, RingMetricsStore
from netview.infrastructure.state_notifier import InMemoryStateNotifier
from netview.presentation.api.app import create_app
from netview.sdk.testing.fakes import FakeClock, FakeVendors, InMemoryUnitOfWorkFactory

DEMO_ID = "7"
"""The stub plugin's runtime key: a source_id, which is what addresses carry."""
DEMO_GUID = "9a8b7c6d-1111-4222-8333-444455556666"
"""Its guid: what permission ids are built from."""
SELF_IP = "192.168.1.95"
ALLOWED = {"localhost", "127.0.0.1", "[::1]"}


class PlainHasher:
    def hash(self, password: str) -> str:
        return "h:" + password

    def verify(self, hash: str, password: str) -> bool:
        return hash == "h:" + password

    def needs_rehash(self, hash: str) -> bool:
        return False


PASSWORD = "correct horse battery"


class StubScheduler:
    def add(self, owner: str, spec: Any) -> None: ...
    def remove_owner(self, owner: str) -> None: ...
    def run_now(self, owner: str, name: str) -> None: ...
    def status(self) -> list[Any]:
        return []


class StubPluginAdmin:
    def __init__(self) -> None:
        self.plugins = {
            DEMO_ID: PluginInfo(
                DEMO_ID,
                "Demo",
                "1.0.0",
                "A demo",
                "active",
                settings={"interval": 5},
                guid=DEMO_GUID,
                source_id=int(DEMO_ID),
                display_name="Demo",
                card_key="entry_point:demo",
            )
        }
        self.calls: list[tuple[str, Any]] = []

    def list(self) -> list[PluginInfo]:
        return list(self.plugins.values())

    def guids(self) -> dict[str, str]:
        return {p.id: p.guid for p in self.plugins.values() if p.guid is not None}

    def get(self, plugin_id: str) -> PluginInfo:
        try:
            return self.plugins[plugin_id]
        except KeyError:
            raise NotFoundError(f"unknown plugin {plugin_id!r}") from None

    def _refuse_pending(self, info: PluginInfo) -> None:
        if info.state == "pending":
            raise ConflictError(f"{info.name} loads the next time netview starts")

    def update_settings(self, plugin_id: str, values: dict[str, Any]) -> PluginInfo:
        info = self.get(plugin_id)
        self._refuse_pending(info)
        if values.get("interval", 0) < 0:
            raise ValidationError("interval must be positive", fields={"interval": "Must be positive"})
        self.calls.append(("settings", values))
        info.settings = dict(values)
        return info

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo:
        info = self.get(plugin_id)
        self._refuse_pending(info)
        self.calls.append(("enabled", enabled))
        info.enabled = enabled
        info.restart_required = True
        return info


def catalog_plugin(plugin_id: str, **kw: Any) -> PluginJson:
    fields: dict[str, Any] = {
        "id": plugin_id,
        "name": plugin_id.title(),
        "version": "0.1.0",
        "description": f"The {plugin_id} plugin",
        "guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, plugin_id)),
        "display_name": plugin_id.title(),
        "plugin_type": "other",
        "sdk_version": ">=1.3,<2",
        "capabilities": ("api",),
        "permissions": ("api",),
    }
    fields.update(kw)
    return PluginJson(**fields)


def catalog_index(*ids: str) -> PluginIndex:
    return build_index([catalog_plugin(i) for i in ids], "main", "https://example.test/archive.zip")


class MemCatalogStore:
    def __init__(self) -> None:
        self.snapshot: CatalogSnapshot | None = None

    def load(self) -> CatalogSnapshot | None:
        return self.snapshot

    def save(self, snapshot: CatalogSnapshot) -> None:
        self.snapshot = snapshot


class StubCatalogFetcher:
    source = "https://example.test/plugins/index.json"

    def __init__(self) -> None:
        self.result: PluginIndex | CatalogUnavailableError = catalog_index("alpha", "beta")

    def fetch(self) -> PluginIndex:
        if isinstance(self.result, CatalogUnavailableError):
            raise self.result
        return self.result


class StubInstaller:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.installed: list[str] = []

    def install(self, entry: CatalogEntry, archive_url: str, progress: Progress) -> None:
        progress("downloading", 50)
        progress("installing", None)
        if self.error:
            raise self.error
        self.installed.append(entry.plugin.id)


class StubThemes:
    def list(self) -> list[ThemeInfo]:
        return []

    def user_dir(self) -> str:
        return ""


@dataclass
class ApiWorld:
    services: AppServices
    uow: InMemoryUnitOfWorkFactory
    bus: InMemoryEventBus
    registry: CapabilityRegistry
    admin: StubPluginAdmin
    clock: FakeClock
    notifier: InMemoryStateNotifier
    metrics: RingMetricsStore
    fetcher: StubCatalogFetcher
    installer: StubInstaller
    auth_store: InMemoryAuthStore
    hasher: PlainHasher

    @property
    def auth(self) -> AuthServices:
        assert self.services.auth is not None
        return self.services.auth

    def add_user(self, username: str, role_ids: list[str] | tuple[str, ...] = ("default",)) -> str:
        """A local user with ``PASSWORD``; returns the username."""
        self.auth.users.create_local(SYSTEM_PRINCIPAL, username, "", PASSWORD, set(role_ids))
        with self.auth_store() as uow:
            user = uow.users.by_username(username)
            assert user is not None
            uow.users.save(replace(user, must_change_password=False))
            uow.commit()
        return username

    def grant(self, username: str, *permissions: str) -> str:
        """A user holding a role of exactly ``permissions``."""
        role = self.auth.roles.create(f"role for {username}")
        self.auth.roles.update(SYSTEM_PRINCIPAL, role.id, permissions=set(permissions))
        return self.add_user(username, [role.id])

    def session_token(self, username: str = "admin") -> str:
        user = next(u for u in self.auth.users.list() if u.username == username)
        return self.auth.sessions.create(user.id, "testclient", "pytest")

    def add_device(self, ip: str, mac: str | None = "aa:bb:cc:dd:ee:01") -> str:
        record = RecordSightings(self.uow, self.clock, FakeVendors(), self.bus, lambda: SELF_IP)
        record([Sighting(ip, mac, 1.0, 64, self.clock.now_ms())])
        return mac or f"ip:{ip}"


def _events(uow: InMemoryUnitOfWorkFactory, limit: int) -> list[Any]:
    with uow() as u:
        return u.events.recent(limit)


def _latest(uow: InMemoryUnitOfWorkFactory, ip: str) -> Any:
    with uow() as u:
        return u.inspections.latest(ip)


def _builtin_admin(now_ms: int) -> User:
    return User(
        id=0,
        username="admin",
        display_name="admin",
        email=None,
        enabled=True,
        builtin=True,
        must_change_password=False,
        role_ids=frozenset({ADMIN_ROLE}),
        provider="local",
        created_ms=now_ms,
        last_sign_in_ms=None,
    )


def build_world(themes: ThemeCatalog | None = None, seed_admin: bool = True) -> ApiWorld:
    uow = InMemoryUnitOfWorkFactory()
    clock = FakeClock()
    bus = InMemoryEventBus()
    notifier = InMemoryStateNotifier()
    registry = CapabilityRegistry()
    metrics = RingMetricsStore(long_prefixes=LONG_PREFIXES, long_maxlen=LONG_MAXLEN)
    scheduler = StubScheduler()
    admin = StubPluginAdmin()
    record = RecordSightings(uow, clock, FakeVendors(), bus, lambda: SELF_IP)
    fetcher = StubCatalogFetcher()
    catalog = PluginCatalogService(
        MemCatalogStore(),
        fetcher,
        lambda: catalog_index("alpha"),
        admin,
        clock,
        "1.3",
        lambda name: True,
    )
    installer = StubInstaller()
    installs = InstallJobs(catalog, installer, admin, lambda work: work(), "1.3", lambda name: True)
    auth_store = InMemoryAuthStore()
    hasher = PlainHasher()
    authorizer = Authorizer(auth_store)
    policy_admin = PolicyAdmin(auth_store)
    sessions = SessionService(auth_store, clock, authorizer, policy_admin.get)
    throttle = LoginThrottle(clock, policy_admin.get)
    auth = AuthServices(
        sessions=sessions,
        sign_in=SignIn(auth_store, hasher, sessions, throttle, clock),
        change_password=ChangeOwnPassword(auth_store, hasher, sessions, throttle, policy_admin.get, clock),
        setup=SetupService(auth_store, hasher, sessions, throttle, clock, "home", None, policy_admin.get),
        users=UserAdmin(auth_store, hasher, sessions, authorizer, policy_admin.get, clock),
        roles=RoleAdmin(auth_store, authorizer, lambda: build_catalog(admin.list())),
        policy=policy_admin,
        authorizer=authorizer,
        catalog=lambda: build_catalog(admin.list()),
        mode="home",
    )
    host = HostInfo("test-host", SELF_IP, "192.168.1.1", "192.168.1.0/24", "test")
    services = AppServices(
        state=GetNetworkState(
            uow,
            registry,
            scheduler,
            lambda: host,
            monitor=WatchMonitor(uow, bus, clock),
            ledger=TrafficLedger(metrics),
        ),
        device=GetDevice(uow),
        set_nickname=SetNickname(uow, clock, bus),
        forget_device=ForgetDevice(uow, bus, clock),
        add_watch=AddWatch(uow, bus, clock),
        remove_watch=RemoveWatch(uow, bus, clock),
        run_scan=RunScan(registry, record, lambda: IPv4Network("192.168.1.0/24"), logging.getLogger("t")),
        run_inspection=RunInspection(registry, uow, clock),
        events=lambda limit: _events(uow, limit),
        latest_inspection=lambda ip: _latest(uow, ip),
        plugins=admin,
        bus=bus,
        scheduler=scheduler,
        notifier=notifier,
        themes=themes or StubThemes(),
        metrics=metrics,
        catalog=catalog,
        installs=installs,
        auth=auth,
    )
    world = ApiWorld(
        services, uow, bus, registry, admin, clock, notifier, metrics, fetcher, installer, auth_store, hasher
    )
    if seed_admin:
        with auth_store() as uow_:
            uow_.users.add(_builtin_admin(clock.now_ms()), hasher.hash(PASSWORD))
            uow_.commit()
    return world


def make_app(world: ApiWorld, routers: list[Any] | None = None, ui: list[Any] | None = None) -> FastAPI:
    return create_app(world.services, routers or [], ui or [], set(ALLOWED), guids=world.admin.guids())


def make_client(app: FastAPI, with_header: bool = True, user: str | None = "admin") -> TestClient:
    """A client whose Host is localhost; ``with_header`` adds X-Netview: 1.

    ``user`` is signed in through a session made straight in the auth service; ``None`` is anonymous.
    """
    cookies = {}
    if user is not None:
        auth = app.state.services.auth
        found = next(u for u in auth.users.list() if u.username == user)
        cookies["netview_session"] = auth.sessions.create(found.id, "testclient", "pytest")
    return TestClient(
        app,
        base_url="http://localhost",
        headers={"X-Netview": "1"} if with_header else {},
        cookies=cookies,
    )
