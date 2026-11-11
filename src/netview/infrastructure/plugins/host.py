"""Loads plugins and manages their lifecycle, settings and enabled flag (spec section 7)."""

from __future__ import annotations

import builtins
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from netview.application.capabilities import Capability
from netview.application.plugins.base import Plugin
from netview.application.plugins.context import PluginContext
from netview.application.plugins.jobs import JobSpec, Scheduler
from netview.application.plugins.manifest import SDK_VERSION
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.plugins.ui import UiContribution
from netview.application.plugins.validation import (
    validate_manifest,
    validate_providers,
    validate_storage,
)
from netview.application.ports.plugin_admin import PluginInfo
from netview.application.ports.repositories import PluginState
from netview.application.ports.uow import UnitOfWorkFactory
from netview.domain.errors import NotFoundError, ValidationError
from netview.infrastructure.db.migrate import upgrade_plugin
from netview.infrastructure.plugins.discovery import DiscoveredPlugin

log = logging.getLogger(__name__)

SETUP_TIMEOUT_S = 10.0
RESERVED_JOB_PREFIX = "poll."  # the host schedules ``poll.<capability>`` jobs itself

Poller = Callable[[str, Capability, object], JobSpec | None]


@dataclass
class _Record:
    info: PluginInfo
    plugin: Plugin | None = None
    router: Any | None = None
    ui: UiContribution | None = None
    ctx: PluginContext | None = None
    providers: dict[Capability, object] = field(default_factory=dict)
    settings_model: Any = None
    loaded: bool = field(default=False)


def _describe(exc: BaseException) -> str:
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _close_context(ctx: Any) -> None:
    close = getattr(ctx, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            log.exception("closing a plugin context failed")


def _run_with_timeout(fn: Callable[[], None], timeout_s: float) -> None:
    """Run ``fn`` on a daemon thread; raise TimeoutError if it has not returned in time.

    The thread is abandoned on timeout (Python cannot kill it) but, being a daemon, it never
    keeps the process alive.
    """
    outcome: builtins.list[BaseException | None] = []

    def target() -> None:
        try:
            fn()
        except BaseException as exc:
            outcome.append(exc)
        else:
            outcome.append(None)

    thread = threading.Thread(target=target, name="netview-plugin-setup", daemon=True)
    thread.start()
    thread.join(timeout_s)
    if not outcome:
        raise TimeoutError(f"setup timed out after {timeout_s:g} s")
    if outcome[0] is not None:
        raise outcome[0]


class PluginHost:
    def __init__(
        self,
        engine: Engine,
        uow: UnitOfWorkFactory,
        registry: CapabilityRegistry,
        scheduler: Scheduler,
        context_factory: Callable[[str, Any], PluginContext],
        seeds: dict[str, dict[str, Any]],
        discovered: builtins.list[DiscoveredPlugin],
        setup_timeout_s: float = SETUP_TIMEOUT_S,
        poller: Poller | None = None,
    ) -> None:
        self._engine = engine
        self._uow = uow
        self._registry = registry
        self._scheduler = scheduler
        self._context_factory = context_factory
        self._seeds = seeds
        self._discovered = discovered
        self._setup_timeout_s = setup_timeout_s
        self._poller = poller
        self._records: dict[str, _Record] = {}

    # ---- loading -------------------------------------------------------------------------------

    def load_all(self) -> None:
        seen_ids: set[str] = set()
        for item in self._discovered:
            if item.cls is None:
                key = item.source
                self._records[key] = _Record(
                    PluginInfo(key, key, "", "", "failed", error=item.error or "failed to load")
                )
                continue
            record = self._load_one(item.cls, seen_ids)
            key = (
                record.info.id if record.info.id not in self._records else f"{record.info.id} ({item.source})"
            )
            self._records[key] = record

    def _load_one(self, cls: type[Plugin], seen_ids: set[str]) -> _Record:
        manifest = cls.manifest
        info = PluginInfo(
            id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            state="failed",
            capabilities=sorted(str(c) for c in manifest.capabilities),
            permissions=sorted(str(p) for p in manifest.permissions),
        )
        record = _Record(info)
        try:
            self._load(cls, record, seen_ids)
        except Exception as exc:
            log.warning("plugin %s failed to load: %s", manifest.id, _describe(exc))
            record.plugin = None
            record.router = None
            record.ui = None
            info.state = "failed"
            info.error = str(exc) or _describe(exc)
            info.ui_module = None
        return record

    def _load(self, cls: type[Plugin], record: _Record, seen_ids: set[str]) -> None:
        info = record.info
        plugin_id = info.id
        errors = validate_manifest(cls.manifest, SDK_VERSION, seen_ids)
        if errors:
            raise ValueError("; ".join(errors))
        seen_ids.add(plugin_id)

        plugin = cls()
        settings_model = cls.settings_model
        record.settings_model = settings_model
        info.settings_schema = settings_model.model_json_schema() if settings_model else None

        errors = validate_providers(plugin)
        storage = plugin.storage()
        if storage is not None:
            errors += validate_storage(plugin_id, storage.metadata)
        if errors:
            raise ValueError("; ".join(errors))

        state = self._read_or_create_state(plugin_id)
        info.enabled = state.enabled
        info.settings = dict(state.settings)
        if not state.enabled:
            info.state = "disabled"
            return

        settings: Any = None
        if settings_model is not None:
            try:
                settings = settings_model.model_validate(state.settings)
            except PydanticValidationError as exc:
                raise ValueError(f"invalid stored settings: {exc}") from exc
            info.settings = settings.model_dump(mode="json")
        plugin.settings = settings

        if storage is not None:
            upgrade_plugin(self._engine, plugin_id, storage.versions_dir)
            state.installed_version = cls.manifest.version
            self._save_state(state)

        ctx = self._context_factory(plugin_id, settings)
        try:
            _run_with_timeout(lambda: plugin.setup(ctx), self._setup_timeout_s)

            # providers may only exist once setup() has run, so check again before registering
            errors = validate_providers(plugin)
            if errors:
                raise ValueError("; ".join(errors))
            for spec in plugin.jobs():
                if spec.name.startswith(RESERVED_JOB_PREFIX):
                    raise ValueError(f'job name "{spec.name}" is reserved')
            providers = dict(plugin.providers())
            try:
                for capability, provider in providers.items():
                    self._registry.register(plugin_id, capability, provider)
            except Exception:
                self._registry.unregister_plugin(plugin_id)
                raise
        except BaseException:
            _close_context(ctx)
            raise
        record.plugin = plugin
        record.ctx = ctx
        record.providers = providers
        record.router = plugin.router()
        record.ui = plugin.ui()
        info.state = "active"
        info.error = None
        if record.ui is not None:
            info.ui_module = f"/plugins/{plugin_id}/static/{record.ui.module}"

    # ---- state persistence ---------------------------------------------------------------------

    def _read_or_create_state(self, plugin_id: str) -> PluginState:
        with self._uow() as uow:
            state = uow.plugin_state.get(plugin_id)
            if state is not None:
                return state
            seed = dict(self._seeds.get(plugin_id, {}))
            enabled = bool(seed.pop("enabled", True))
            state = PluginState(plugin_id, enabled, seed, None)
            uow.plugin_state.save(state)
            uow.commit()
            return state

    def _save_state(self, state: PluginState) -> None:
        with self._uow() as uow:
            uow.plugin_state.save(state)
            uow.commit()

    # ---- lifecycle -----------------------------------------------------------------------------

    def _jobs(self, record: _Record) -> builtins.list[JobSpec]:
        """The plugin's own jobs, then one poll job per provider the core knows how to poll."""
        plugin = record.plugin
        if plugin is None:
            return []
        plugin_id = record.info.id
        specs = [s for s in plugin.jobs() if not s.name.startswith(RESERVED_JOB_PREFIX)]
        if self._poller is not None:
            for capability, provider in record.providers.items():
                spec = self._poller(plugin_id, capability, provider)
                if spec is not None:
                    specs.append(spec)
        return specs

    def start_jobs(self) -> None:
        for record in self._records.values():
            for spec in self._jobs(record):
                self._scheduler.add(record.info.id, spec)

    def shutdown(self) -> None:
        for record in self._records.values():
            if record.plugin is None:
                continue
            self._scheduler.remove_owner(record.info.id)
            try:
                record.plugin.shutdown()
            except Exception:
                log.exception("plugin %s shutdown failed", record.info.id)
            _close_context(record.ctx)

    def routers(self) -> builtins.list[tuple[str, Any]]:
        return [(r.info.id, r.router) for r in self._records.values() if r.router is not None]

    def ui_contributions(self) -> builtins.list[tuple[str, UiContribution]]:
        return [(r.info.id, r.ui) for r in self._records.values() if r.ui is not None]

    def plugin(self, plugin_id: str) -> Plugin | None:
        return self._record(plugin_id).plugin

    # ---- PluginAdmin ---------------------------------------------------------------------------

    def _record(self, plugin_id: str) -> _Record:
        try:
            return self._records[plugin_id]
        except KeyError:
            raise NotFoundError(f"unknown plugin {plugin_id!r}") from None

    def list(self) -> builtins.list[PluginInfo]:
        return [r.info for r in self._records.values()]

    def get(self, plugin_id: str) -> PluginInfo:
        return self._record(plugin_id).info

    def update_settings(self, plugin_id: str, values: dict[str, Any]) -> PluginInfo:
        record = self._record(plugin_id)
        info = record.info
        model = record.settings_model
        if model is None:
            raise ValidationError(f"plugin {plugin_id!r} has no settings")
        merged = {**info.settings, **values}  # a PATCH changes only the fields it names
        try:
            new = model.model_validate(merged)
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc
        dumped: dict[str, Any] = json.loads(new.model_dump_json())

        with self._uow() as uow:
            state = uow.plugin_state.get(plugin_id) or PluginState(plugin_id, info.enabled, {}, None)
            state.settings = dumped
            uow.plugin_state.save(state)
            uow.commit()
        info.settings = dumped
        if record.ctx is not None:
            record.ctx.settings = new  # the live context must not keep the old settings

        plugin = record.plugin
        if plugin is not None:
            plugin.on_settings_changed(new)
            self._scheduler.remove_owner(plugin_id)
            for spec in self._jobs(record):
                self._scheduler.add(plugin_id, spec)
        else:
            info.restart_required = True
        return info

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo:
        record = self._record(plugin_id)
        info = record.info
        with self._uow() as uow:
            state = uow.plugin_state.get(plugin_id) or PluginState(plugin_id, enabled, {}, None)
            state.enabled = enabled
            uow.plugin_state.save(state)
            uow.commit()
        info.enabled = enabled
        info.restart_required = enabled != (info.state == "active")
        return info
