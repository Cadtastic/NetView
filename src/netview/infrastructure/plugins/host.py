"""Loads plugins and manages their lifecycle, settings and enabled flag (spec section 7)."""

from __future__ import annotations

import builtins
import logging
import shutil
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError as PydanticValidationError

from netview.application.auth.catalog import automatic_ids, validate_declared
from netview.application.capabilities import Capability
from netview.application.plugins.base import Plugin
from netview.application.plugins.conflicts import TIER_DATA_DIR, Candidate, pick_winners
from netview.application.plugins.context import PluginContext, PluginIdentity
from netview.application.plugins.jobs import JobSpec, Scheduler
from netview.application.plugins.manifest import SDK_VERSION
from netview.application.plugins.plugin_json import PluginJson
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.plugins.settings_requirements import unmet_requirements
from netview.application.plugins.ui import UiContribution
from netview.application.plugins.validation import (
    manifest_mismatch,
    validate_manifest,
    validate_providers,
)
from netview.application.ports.plugin_admin import PluginInfo, UninstallResult
from netview.application.ports.repositories import PluginState
from netview.application.ports.uow import UnitOfWorkFactory
from netview.domain.errors import ConflictError, NotFoundError, ValidationError
from netview.infrastructure.db.engine import make_plugin_engine, plugin_data_file
from netview.infrastructure.db.migrate import upgrade_plugin
from netview.infrastructure.plugins.discovery import DiscoveredPlugin, find_folders, import_folder
from netview.infrastructure.plugins.folders import (
    direct_child,
    folder_plugins,
    move_to_trash,
    read_plugin_json,
)
from netview.infrastructure.plugins.settings_codec import (
    dump_for_display,
    dump_for_storage,
    field_errors,
    mask_raw,
    merge_patch,
    safe_validation_message,
    unsupported_secrets,
)

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


def _card_info(
    pj: PluginJson | None,
    card_key: str,
    state: Literal["active", "disabled", "failed", "pending"],
    *,
    folder: Path | None,
    folder_name: str | None,
    error: str | None = None,
    source_id: int | None = None,
    owns_data: bool = False,
) -> PluginInfo:
    """A card for a plugin that did not load (or not yet), named from its plugin.json where there is one."""
    fallback = folder.name if folder is not None else card_key
    return PluginInfo(
        id=str(source_id) if source_id is not None else card_key,
        name=pj.name if pj is not None else fallback,
        version=pj.version if pj is not None else "",
        description=pj.description if pj is not None else "",
        state=state,
        error=error,
        capabilities=sorted(pj.capabilities) if pj is not None else [],
        permissions=sorted(pj.permissions) if pj is not None else [],
        enabled=True,
        source="folder" if folder is not None else "builtin",
        guid=pj.guid if pj is not None else None,
        source_id=source_id,
        display_name=pj.display_name if pj is not None else fallback,
        plugin_type=pj.plugin_type if pj is not None else None,
        card_key=card_key,
        folder=folder_name,
        owns_data=owns_data,
    )


def _close_context(ctx: Any) -> None:
    close = getattr(ctx, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            log.exception("closing a plugin context failed")


def _config_errors(model: Any, schema: dict[str, Any] | None, raw: dict[str, Any]) -> dict[str, str]:
    """What the stored settings lack before the plugin can work; empty when it is configured."""
    if model is None:
        return {}
    try:
        settings = model.model_validate(raw)
    except PydanticValidationError as exc:
        return field_errors(exc)
    return unmet_requirements(schema, dump_for_storage(settings))


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
        data_dir: Path,
        uow: UnitOfWorkFactory,
        registry: CapabilityRegistry,
        scheduler: Scheduler,
        context_factory: Callable[[PluginIdentity, Any], PluginContext],
        seeds: dict[str, dict[str, Any]],
        discovered: builtins.list[DiscoveredPlugin],
        setup_timeout_s: float = SETUP_TIMEOUT_S,
        poller: Poller | None = None,
        folder_bases: Sequence[tuple[Path, int]] = (),
        blocked: Mapping[str, str] | None = None,
        unfinished_uninstalls: Mapping[Path, str] | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._uow = uow
        self._registry = registry
        self._scheduler = scheduler
        self._context_factory = context_factory
        self._seeds = seeds
        self._discovered = discovered
        self._setup_timeout_s = setup_timeout_s
        self._poller = poller
        self._folder_bases = tuple(folder_bases)
        self._folders = tuple(base for base, _ in folder_bases)
        self._blocked = dict(blocked or {})
        """guid -> why moving its saved data out of netview.db failed; it is not loaded now."""
        self._unfinished = dict(unfinished_uninstalls or {})
        """resolved folder -> why its uninstall could not finish; such a folder is never loaded."""
        self._records: dict[str, _Record] = {}
        self._gone: set[str] = set()
        """Keys of plugins uninstalled while running: their routes and static files answer 404."""
        self._lock = threading.RLock()

    # ---- loading -------------------------------------------------------------------------------

    def load_all(self) -> None:
        """Find every plugin, settle same-guid conflicts, then load the winners.

        Built-ins come from ``discovered`` (already imported). Folders are read from their plugin.json and are
        imported only once they have won, as ``netview_local_plugins.p<source_id>``. A registered winner is
        known by ``str(source_id)``; a card that lost, or has no usable guid, by its ``card_key``.
        """
        cands: list[Candidate] = []
        failed: list[DiscoveredPlugin] = []
        builtins_by_key: dict[str, DiscoveredPlugin] = {}
        folders_by_key: dict[str, tuple[Path, PluginJson]] = {}
        for item in self._discovered:
            if item.cls is None:
                failed.append(item)
                continue
            builtins_by_key[item.source] = item
            cands.append(Candidate(item.source, item.cls.manifest.guid, 0, None))
        for fc in find_folders(self._folder_bases):
            key = f"folder:{fc.folder.resolve()}"
            if (why := self._unfinished.get(fc.folder.resolve())) is not None:
                self._records[key] = self._unfinished_record(fc.plugin_json, key, fc.folder, why)
                continue  # an uninstall is pending for it: never imported
            if fc.plugin_json is None:
                failed.append(
                    DiscoveredPlugin(key, None, fc.error or "plugin.json is missing or invalid", fc.folder)
                )
                continue
            folders_by_key[key] = (fc.folder, fc.plugin_json)
            cands.append(Candidate(key, fc.plugin_json.guid, fc.tier, str(fc.folder.resolve())))

        with self._uow() as uow:
            last = uow.plugin_registry.last_folders()
        winners, losers = pick_winners(cands, last)

        source_ids: dict[str, int] = {}
        for cand in winners:
            guid = cand.guid or ""
            with self._uow() as uow:
                source_id = uow.plugin_registry.assign(guid)
                uow.commit()
            source_ids[guid] = source_id
            if cand.card_key in builtins_by_key:
                item = builtins_by_key[cand.card_key]
            else:
                folder, pj = folders_by_key[cand.card_key]
                item = import_folder(folder, source_id)
                if item.cls is not None and (diff := manifest_mismatch(item.cls.manifest, pj)):
                    item = DiscoveredPlugin(
                        item.source,
                        None,
                        "plugin.json and the manifest disagree on: " + ", ".join(diff),
                        folder,
                    )
            if item.cls is None:
                rec = self._failed_record(item, source_id, owns_data=True)
                self._records[rec.info.id] = rec
                continue
            record = self._load_one(item.cls, source_id, item.source, item.folder)
            self._records[record.info.id] = record
            if cand.folder is not None and record.info.state != "failed":
                with self._uow() as uow:
                    uow.plugin_registry.set_last_folder(guid, cand.folder)
                    uow.commit()

        for item in failed:
            self._records.setdefault(item.source, self._failed_record(item))
        for loser_key, winner in losers.items():
            self._add_loser(loser_key, winner, builtins_by_key, folders_by_key, source_ids)

    def _unfinished_record(self, pj: PluginJson | None, key: str, folder: Path, why: str) -> _Record:
        """A stopped card for a folder whose uninstall could not finish; it can be uninstalled again."""
        error = f"Uninstall didn't finish: {why}. It will be removed when netview restarts"
        return _Record(
            _card_info(pj, key, "failed", folder=folder, folder_name=self._folder_name(folder), error=error)
        )

    def _folder_name(self, folder: Path | None) -> str | None:
        """The folder's name when it is a direct child of ``<data dir>/plugins``, else None."""
        if folder is None:
            return None
        for base, tier in self._folder_bases:
            if tier == TIER_DATA_DIR and folder.resolve().parent == base.resolve():
                return folder.name
        return None

    def _add_loser(
        self,
        loser_key: str,
        winner: Candidate,
        builtins_by_key: dict[str, DiscoveredPlugin],
        folders_by_key: dict[str, tuple[Path, PluginJson]],
        source_ids: dict[str, int],
    ) -> None:
        if winner.card_key in builtins_by_key:
            cls = builtins_by_key[winner.card_key].cls
            winner_name = cls.manifest.name if cls is not None else winner.card_key
        else:
            winner_name = folders_by_key[winner.card_key][1].name
        where = winner.folder if winner.folder is not None else "built in"
        error = f"Same guid as {winner_name} (loaded from {where})"
        source_id = source_ids.get(winner.guid or "")
        if loser_key in builtins_by_key:
            cls = builtins_by_key[loser_key].cls
            assert cls is not None
            m = cls.manifest
            info = PluginInfo(
                loser_key,
                m.name,
                m.version,
                m.description,
                "failed",
                error=error,
                source="builtin",
                guid=m.guid,
                source_id=source_id,
                display_name=m.display_name,
                plugin_type=str(getattr(m.plugin_type, "value", m.plugin_type)),
                card_key=loser_key,
                owns_data=False,
            )
            self._records.setdefault(loser_key, _Record(info))
            return
        folder, pj = folders_by_key[loser_key]
        info = _card_info(
            pj, loser_key, "failed", folder=folder, folder_name=self._folder_name(folder), error=error
        )
        info.source_id = source_id
        self._records.setdefault(loser_key, _Record(info))

    def _failed_record(
        self, item: DiscoveredPlugin, source_id: int | None = None, owns_data: bool = False
    ) -> _Record:
        """A plugin that could not be imported, named from its plugin.json where there is a valid one."""
        pj = read_plugin_json(item.folder) if item.folder is not None else None
        info = _card_info(
            pj,
            item.source,
            "failed",
            folder=item.folder,
            folder_name=self._folder_name(item.folder),
            error=item.error or "failed to load",
            source_id=source_id,
            owns_data=owns_data,
        )
        return _Record(info)

    def _load_one(
        self,
        cls: type[Plugin],
        source_id: int,
        card_key: str,
        folder: Path | None,
    ) -> _Record:
        manifest = cls.manifest
        info = PluginInfo(
            id=str(source_id),
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            state="failed",
            capabilities=sorted(str(c) for c in manifest.capabilities),
            permissions=sorted(str(p) for p in manifest.permissions),
            source="folder" if folder is not None else "builtin",
            guid=manifest.guid,
            source_id=source_id,
            display_name=manifest.display_name,
            plugin_type=str(getattr(manifest.plugin_type, "value", manifest.plugin_type)),
            card_key=card_key,
            folder=self._folder_name(folder),
            owns_data=True,
        )
        record = _Record(info)
        try:
            self._load(cls, record)
        except Exception as exc:
            log.warning(
                "plugin %s (p%s) failed to load: %s", manifest.display_name, source_id, _describe(exc)
            )
            record.plugin = None
            record.router = None
            record.ui = None
            info.state = "failed"
            info.error = str(exc) or _describe(exc)
            info.ui_module = None
        return record

    def _load(self, cls: type[Plugin], record: _Record) -> None:
        info = record.info
        owner = info.id  # str(source_id): the scheduler, capability registry and URLs know the plugin by this
        guid = cls.manifest.guid
        errors = validate_manifest(cls.manifest, SDK_VERSION)
        if errors:
            raise ValueError("; ".join(errors))
        if (move_error := self._blocked.get(guid)) is not None:
            # loading it now would make an empty data file and strand the old data in netview.db for good
            raise ValueError(
                f"Moving its saved data failed: {move_error}. NetView retries at the next start."
            )

        plugin = cls()
        settings_model = cls.settings_model
        record.settings_model = settings_model
        info.settings_schema = settings_model.model_json_schema() if settings_model else None

        declared = tuple(cls.user_permissions)
        errors = validate_declared(cls.manifest.display_name, declared, set(automatic_ids(info)))
        if errors:
            raise ValueError("; ".join(errors))
        info.user_permissions = list(declared)

        if settings_model is not None and (bad := unsupported_secrets(settings_model)):
            raise ValueError(
                "settings model has secrets the host cannot mask (only top-level SecretStr fields "
                f"are supported): {', '.join(bad)}"
            )

        errors = validate_providers(plugin)
        storage = plugin.storage()
        if errors:
            raise ValueError("; ".join(errors))

        state = self._read_or_create_state(guid)
        info.enabled = state.enabled
        info.config_errors = _config_errors(settings_model, info.settings_schema, state.settings)
        info.settings = (
            mask_raw(state.settings, settings_model) if settings_model is not None else dict(state.settings)
        )
        if not state.enabled:
            info.state = "disabled"
            return

        settings: Any = None
        if settings_model is not None:
            try:
                settings = settings_model.model_validate(state.settings)
            except PydanticValidationError as exc:
                raise ValueError(f"invalid stored settings: {safe_validation_message(exc)}") from None
            info.settings = dump_for_display(settings)
        plugin.settings = settings

        data_file: Path | None = None
        if storage is not None:
            data_file = plugin_data_file(self._data_dir, guid)
            data_file.parent.mkdir(parents=True, exist_ok=True)  # only a plugin with storage makes the folder
            engine = make_plugin_engine(data_file)
            try:
                upgrade_plugin(engine, storage.versions_dir)
            finally:
                engine.dispose()
            state.installed_version = cls.manifest.version
            self._save_state(state)

        identity = PluginIdentity(guid, info.source_id or 0, cls.manifest.display_name, data_file)
        ctx = self._context_factory(identity, settings)
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
                    self._registry.register(owner, capability, provider)
            except Exception:
                self._registry.unregister_plugin(owner)
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
            info.ui_module = f"/plugins/{owner}/static/{record.ui.module}"

    # ---- state persistence ---------------------------------------------------------------------

    def _read_or_create_state(self, guid: str) -> PluginState:
        with self._uow() as uow:
            state = uow.plugin_state.get(guid)
            if state is not None:
                return state
            seed = dict(self._seeds.get(guid, {}))
            enabled = bool(seed.pop("enabled", True))
            state = PluginState(guid, enabled, seed, None)
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

    def guid_of(self, owner: str) -> str:
        """The guid of the plugin known as ``owner`` (its ``str(source_id)``); ``owner`` itself if unknown."""
        record = self._records.get(owner)
        return record.info.guid if record is not None and record.info.guid is not None else owner

    def is_present(self, source_id: str) -> bool:
        """False once the plugin known as ``source_id`` was uninstalled."""
        return source_id not in self._gone

    def guids(self) -> dict[str, str]:
        """``str(source_id)`` to guid, for every plugin that was registered."""
        return {
            r.info.id: r.info.guid
            for r in builtins.list(self._records.values())
            if r.info.guid is not None and r.info.id == str(r.info.source_id)
        }

    def routers(self) -> builtins.list[tuple[str, Any]]:
        return [(r.info.id, r.router) for r in builtins.list(self._records.values()) if r.router is not None]

    def ui_contributions(self) -> builtins.list[tuple[str, UiContribution]]:
        return [(r.info.id, r.ui) for r in builtins.list(self._records.values()) if r.ui is not None]

    def plugin(self, plugin_id: str) -> Plugin | None:
        return self._record(plugin_id).plugin

    # ---- PluginAdmin ---------------------------------------------------------------------------

    def _record(self, plugin_id: str) -> _Record:
        try:
            return self._records[plugin_id]
        except KeyError:
            raise NotFoundError(f"unknown plugin {plugin_id!r}") from None

    def _pending(self) -> builtins.list[PluginInfo]:
        """Plugin folders with a plugin.json that were not loaded at start (copied or installed since)."""
        records = builtins.list(self._records.values())
        known_guids = {r.info.guid for r in records if r.info.guid is not None}
        known_cards = {r.info.card_key for r in records}
        found: builtins.list[PluginInfo] = []
        for folder, pj in folder_plugins(self._folders):
            key = f"folder:{folder.resolve()}"
            if pj.guid in known_guids or key in known_cards:
                continue
            found.append(_card_info(pj, key, "pending", folder=folder, folder_name=self._folder_name(folder)))
        return found

    def _refuse_if_pending(self, plugin_id: str) -> None:
        if plugin_id in self._records:
            return
        for info in self._pending():
            if info.id == plugin_id:
                raise ConflictError(f"{info.name} loads the next time netview starts")

    def list(self) -> builtins.list[PluginInfo]:
        return [r.info for r in builtins.list(self._records.values())] + self._pending()

    def get(self, plugin_id: str) -> PluginInfo:
        if plugin_id in self._records:
            return self._records[plugin_id].info
        for info in self._pending():
            if info.id == plugin_id:
                return info
        raise NotFoundError(f"unknown plugin {plugin_id!r}")

    def update_settings(self, plugin_id: str, values: dict[str, Any]) -> PluginInfo:
        self._refuse_if_pending(plugin_id)
        record = self._record(plugin_id)
        info = record.info
        model = record.settings_model
        if model is None or info.guid is None or not info.owns_data:
            raise ValidationError(f"plugin {plugin_id!r} has no settings")
        with self._uow() as uow:
            state = uow.plugin_state.get(info.guid) or PluginState(info.guid, info.enabled, {}, None)
            # a PATCH changes only the fields it names; merge onto the stored (revealed) settings
            merged = merge_patch(state.settings, values, model)
            try:
                new = model.model_validate(merged)
            except PydanticValidationError as exc:
                raise ValidationError(safe_validation_message(exc), fields=field_errors(exc)) from None
            # a save must leave the plugin configured: every schema requirement met
            unmet = unmet_requirements(info.settings_schema, dump_for_storage(new))
            if unmet:
                raise ValidationError("; ".join(f"{k}: {v}" for k, v in unmet.items()), fields=unmet)
            state.settings = dump_for_storage(new)
            uow.plugin_state.save(state)
            uow.commit()
        info.settings = dump_for_display(new)
        info.config_errors = {}
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
        self._refuse_if_pending(plugin_id)
        record = self._record(plugin_id)
        info = record.info
        if info.guid is None or not info.owns_data:
            raise ConflictError(f"{info.name} cannot be turned on or off")
        with self._uow() as uow:
            state = uow.plugin_state.get(info.guid) or PluginState(info.guid, enabled, {}, None)
            state.enabled = enabled
            uow.plugin_state.save(state)
            uow.commit()
        info.enabled = enabled
        info.restart_required = enabled != (info.state == "active")
        return info

    # ---- uninstall -----------------------------------------------------------------------------

    def _plugins_dir(self) -> Path | None:
        """``<data dir>/plugins``: the only place a plugin can be uninstalled from."""
        for base, tier in self._folder_bases:
            if tier == TIER_DATA_DIR:
                return base
        return None

    def uninstall(self, folder: str, delete_data: bool) -> UninstallResult:
        """Stop the plugin in ``<data dir>/plugins/<folder>``, remove its folder and, if asked, its data.

        Raises ConflictError for anything that is not a direct child of that folder, and for a request to
        delete data the card does not own; NotFoundError when no plugin is in that folder. The registry row
        stays, so a reinstall gets the same source_id.
        """
        with self._lock:
            return self._uninstall(folder, delete_data)

    def _uninstall(self, folder: str, delete_data: bool) -> UninstallResult:
        base = self._plugins_dir()
        resolved = direct_child(base, folder) if base is not None else None
        if base is None or resolved is None:
            raise ConflictError(f"{folder!r} is not a plugin folder that can be uninstalled")
        record = next(
            (r for r in builtins.list(self._records.values()) if r.info.folder == resolved.name), None
        )
        info = record.info if record is not None else None
        if info is None:
            info = next((i for i in self._pending() if i.folder == resolved.name), None)
        if info is None:
            raise NotFoundError(f"no plugin in the folder {folder!r}")
        guid = info.guid
        if delete_data and (guid is None or not info.owns_data):
            raise ConflictError(f"{info.name} does not own the saved data of its plugin; it was not deleted")
        if delete_data and guid in self._blocked:
            raise ConflictError("Its saved data is still being moved; try again after a restart")

        if record is not None:
            self._stop(record)
        module = f"netview_local_plugins.p{info.source_id}"
        if record is not None and info.id == str(info.source_id):  # a duplicate shares the owner's number
            for name in [n for n in list(sys.modules) if n == module or n.startswith(module + ".")]:
                del sys.modules[name]

        moved_error: str | None = None
        if resolved.exists():
            try:
                trashed = move_to_trash(base, resolved)
            except OSError as exc:
                moved_error = str(exc) or type(exc).__name__
                with self._uow() as uow:
                    uow.plugin_registry.add_pending_uninstall(str(resolved))
                    uow.commit()
                key = f"folder:{resolved}"
                self._records[key] = self._unfinished_record(
                    read_plugin_json(resolved), key, resolved, moved_error
                )
                log.warning("cannot rename %s; it is removed at the next start: %s", resolved, exc)
            else:
                shutil.rmtree(trashed, ignore_errors=True)  # clear_trash finishes what this cannot
        if moved_error is None:  # moved, or gone already: no record may outlive a later reinstall
            with self._uow() as uow:
                uow.plugin_registry.clear_pending_uninstall(str(resolved))
                uow.commit()

        error: str | None = None
        if delete_data and guid is not None:
            error = self._delete_data(guid)
        if moved_error is not None:
            return UninstallResult(False, moved_error)
        return UninstallResult(True, error)

    def _stop(self, record: _Record) -> None:
        key = record.info.id
        self._scheduler.remove_owner(key)
        self._registry.unregister_plugin(key)
        if record.plugin is not None:
            try:
                record.plugin.shutdown()
            except Exception:
                log.exception("plugin %s shutdown failed", key)
        _close_context(record.ctx)
        record.plugin = None
        record.ctx = None
        self._records.pop(key, None)
        self._gone.add(key)

    def _delete_data(self, guid: str) -> str | None:
        """Remove ``<guid>.db`` (and its -wal and -shm) and the saved state; the message when a file stays."""
        db = plugin_data_file(self._data_dir, guid)
        error: str | None = None
        for path in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("cannot delete %s: %s", path, exc)
                error = f"its saved data was not fully deleted: {exc}"
        with self._uow() as uow:
            uow.plugin_state.delete(guid)
            uow.commit()
        return error
