# Plugin identity, types and uninstall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plugins are identified by an author guid, labelled by `display_name`, grouped by `plugin_type`, addressed by a database-assigned `source_id`, keep data in their own SQLite file, and can be uninstalled when they live in `<data dir>/plugins`.

**Architecture:** The application layer gets the new manifest fields, a `PluginType` enum and a pure conflict resolver. The infrastructure layer gets:
- a plugin registry table (guid → source_id);
- a per-plugin database engine;
- a one-time legacy move;
- uninstall in `PluginHost`.

Runtime keys (URLs, scheduler, capability registry, module names) use `str(source_id)`. Persisted keys (`plugin_state`, report sections, auth `role_permissions`) use the guid. The author-written `id` is kept alongside the new fields until Task 11 removes it, so every task ends with green gates.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, SQLite (WAL), plain ES-module JS with `node --test`, uv.

**Spec:** `docs/superpowers/specs/2026-11-12-plugin-identity-and-uninstall-design.md`. Executors read it alongside this plan; section numbers below (§n) refer to it.

## Global Constraints

- **Precondition:** `feature/auth-stage1` is merged to main and this branch is rebased onto it before Task 1 (Task 0). Auth names used below (`AuthMiddleware`, `plugin_group`, `default_permission_for`, `plugin_default_guard`, `PluginContext.require`, `auth.can`, migration `0004_auth.py`) come from `netview-auth/docs/superpowers/plans/2026-11-12-auth-stage1-core.md`. Check each one against the merged code before relying on it.
- `plugin_type` values, exactly: `router`, `switch`, `access_point`, `firewall`, `modem`, `server`, `nas`, `computer`, `tv`, `printer`, `camera`, `ups`, `iot`, `software`, `other`.
- guid format: lower-case UUID, regex `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`.
- Fixed guids (use verbatim, also as the legacy map):

  | legacy id | guid | display_name | plugin_type |
  |---|---|---|---|
  | lan_discovery | `4eddf684-deb5-41cf-9588-020746307ade` | LAN discovery | software |
  | health | `9f4cd689-1a67-4c89-abff-ac9252568d97` | Health | software |
  | identity | `4b77e778-dc26-4ac0-8b2e-fe3995363df1` | Identity | software |
  | inspection | `ac1dc07d-123c-4414-a4c8-72013d00f267` | Inspection | software |
  | local_host | `0a505ba4-bbbd-40b8-a77d-8f5dbe1470a8` | This device | software |
  | gsm7248 | `3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4` | GSM7248 | switch |
  | gs105e | `c66a564b-0254-44cf-bb74-1c7f6ebae6be` | GS105E | switch |
  | starlink | `67216b55-f454-4876-b26f-336e505c83ce` | Starlink | router |
  | roku | `241d4d28-4a70-406c-833c-a7b4d5b389a9` | Roku | tv |

- Plugin data file: `<data dir>/plugin-data/<guid>.db`. Its Alembic version table is `alembic_version`.
- Folder module name: `netview_local_plugins.p<source_id>`.
- Web addresses: `/api/v1/plugins/<source_id>/…`, `/plugins/<source_id>/static/…`, UI route `#/p/<source_id>/<page id>`.
- Uninstall only for folders that resolve to a direct child of `<data dir>/plugins`. Never `--plugin-dir`/`plugin_dirs`, never built-ins.
- Uninstall needs the same auth guard as install (`require_admin`) **(plan's call: uninstall deletes code, same risk class as install)**.
- Backup file name: `netview.db.bak-<YYYY-MM-DD>-before-plugin-identity`. Use SQLite's backup API, and skip the backup if the file already exists.
- Dialog copy (§8): title "Uninstall <name>?"; body "Its folder is deleted. It stops now and is fully gone after netview restarts."; checkbox "Also delete its saved settings and data" (unchecked); buttons "Cancel" / "Uninstall" (danger). Failure: "Uninstall didn't finish: <reason>. It will be removed when netview restarts". Toast: "<name> uninstalled".
- Gates (all must pass at the end of every task): `uv run pytest -q`, `npm test`, `uv run ruff check .`, `uv run mypy src plugins`, `uv run lint-imports`, `uv run python scripts/build_plugin_index.py --check`.
- Never point a test or a browser check at the real `network/netview-dev` data dir. Use a copy.
- Commits on `feature/plugin-identity`. Author email stays the repo's no-reply address. Do not push.

## Review Focus

1. **Renamed copy in the data folder** (`plugins/roku` copied to `<data>/plugins/aaa_roku`, same guid): the original stays active, the copy is a failed card "Same guid as Roku (loaded from …)", and NetView starts. Covered by Task 3 `test_renamed_copy_never_displaces_original`.
2. **Uninstalling a duplicate with delete_data:** the server refuses, and the owner's `<guid>.db` and `plugin_state` row are untouched. Covered by Task 9 `test_delete_data_refused_for_duplicate`.
3. **The legacy move interrupted halfway** (copy fails on the second table): `netview.db` keeps every old table, no `<guid>.db` is left behind, and the next start retries cleanly. Covered by Task 8 `test_move_failure_leaves_core_db_untouched`.
4. **A web address of an uninstalled plugin, used before restart** (open tab, bookmark): its API and static paths return 404, not a 500 or a stale page. The nav tab is gone without a reload. Covered by Task 9 `test_routes_404_after_uninstall` and Task 10 `removePlugin` test.
5. **A folder plugin whose `plugin.json` disagrees with its manifest** (e.g. a copy whose author edited only one file): it shows a failed card naming the fields that differ, and never half-loads. Covered by Task 3 `test_manifest_plugin_json_mismatch_fails`.

---

### Task 0: Rebase onto main after auth merges

- [ ] **Step 1:** Confirm `feature/auth-stage1` is merged: `git -C "R:/source/claude projects/HomeLab/netview-main" log --oneline main | grep -i auth` shows its commits. If it is not merged, stop and report. Do not start Task 1.
- [ ] **Step 2:** In this worktree: `git rebase main`. Expected: the only commits on top of main are the 4 docs commits, with no conflicts.
- [ ] **Step 3:** Run all gates. Expected: all green (baseline).
- [ ] **Step 4:** Note in the SDD ledger the latest core migration number on main (expected `0004_auth`) and the real names of the auth symbols listed in Global Constraints. Later tasks use those names.

### Task 1: New manifest fields and `PluginType`

**Files:**
- Create: `src/netview/application/plugins/plugin_type.py`
- Modify: `src/netview/application/plugins/manifest.py`, `validation.py`, `plugin_json.py`, `src/netview/sdk/__init__.py`, all nine plugin manifests (`src/netview/plugins/builtin/*/plugin.py`, `plugins/*/plugin.py`), the four `plugins/*/plugin.json`, every sample plugin in `tests/integration/plugins/sample_plugins/`, `plugins/index.json`, `src/netview/infrastructure/plugins/catalog.json` (regenerate with `scripts/build_plugin_index.py --execute`)
- Test: `tests/unit/application/test_plugin_type.py`, `tests/integration/plugins/test_validation.py`, `tests/unit/application/test_plugin_json.py` (or the existing plugin_json test file)

**Interfaces:**
- Produces:
  - `class PluginType(StrEnum)` with exactly the 15 values.
  - `GUID_RE: re.Pattern[str]` in `validation.py`.
  - `PluginManifest` gains the required fields `guid: str`, `display_name: str` and `plugin_type: PluginType` (after `description`). `id` stays for now.
  - `PluginJson` gains `guid: str`, `display_name: str` and `plugin_type: str`.
  - `validate_manifest(m, sdk_version, seen_ids)` also rejects a bad guid ("guid … must be a lower-case UUID"), an empty display_name, and a plugin_type that is not a `PluginType`.
  - `plugin_json_to_dict` writes the three fields after `description`.
  - The SDK exports `PluginType`.

- [ ] **Step 1: Write failing tests**
  - `test_plugin_type_values`: `[t.value for t in PluginType] == ["router","switch","access_point","firewall","modem","server","nas","computer","tv","printer","camera","ups","iot","software","other"]`.
  - `test_manifest_rejects_bad_guid` (`"ABC"`, an upper-case UUID), `test_manifest_rejects_empty_display_name`, `test_manifest_rejects_unknown_plugin_type` (`"toaster"`): each error list is non-empty and names the field.
  - `test_plugin_json_requires_new_fields`: parsing without each field raises `ValidationError` naming it, and `plugin_type: "toaster"` raises.
  - `test_plugin_json_round_trip_new_fields`.
  - `test_every_plugin_has_fixed_guid`: a table test against the Global Constraints table for all nine (`manifest.guid`, `display_name`, `plugin_type`).
- [ ] **Step 2:** Run `uv run pytest tests/unit/application tests/integration/plugins/test_validation.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Add the fields to all nine plugins, the sample plugins and the four `plugin.json` files, using the values from Global Constraints. Sample plugins get fresh guids, `display_name` equal to their `name`, and `plugin_type` `other`. Regenerate the index and catalog.
- [ ] **Step 4:** Run all gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(plugins): guid, display_name and plugin_type on every plugin`.

### Task 2: Plugin registry table and repository

**Files:**
- Create: `src/netview/infrastructure/db/core_versions/0005_plugin_registry.py` (number = the latest on main + 1)
- Modify: `src/netview/infrastructure/db/models.py`, `repositories.py`, the UoW port (`src/netview/application/ports/repositories.py` and `uow.py`), `src/netview/sdk/testing/fakes.py`
- Test: `tests/integration/db/test_plugin_registry.py`, `tests/integration/db/test_migrate.py`

**Interfaces:**
- Produces:
  - Table `plugin_registry(source_id INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT NOT NULL UNIQUE, last_folder TEXT NULL)`.
  - Table `plugin_uninstall_pending(folder TEXT PRIMARY KEY)`: an absolute resolved path.
  - Port `PluginRegistryRepository` with:
    - `assign(guid: str) -> int`: returns the existing source_id, or inserts and returns a new one;
    - `source_id(guid: str) -> int | None`;
    - `last_folders() -> dict[str, str]`;
    - `set_last_folder(guid: str, folder: str) -> None`;
    - `add_pending_uninstall(folder: str) -> None`;
    - `pending_uninstalls() -> list[str]`;
    - `clear_pending_uninstall(folder: str) -> None`.
  - Exposed as `uow.plugin_registry`.
  - `PluginStateRepository` gains `delete(plugin_id: str) -> None`.
  - In-memory fakes of all of these.

- [ ] **Step 1: Failing tests**
  - `test_assign_is_stable`: assigning the same guid twice returns the same int, and two guids get different ints.
  - `test_source_id_survives_reopen`: a file DB, assign, close, reopen, same id.
  - `test_registry_row_never_deleted_by_state_delete`.
  - `test_pending_uninstall_round_trip`.
  - `test_migrate_creates_registry_tables`.
  - The same `assign` and `pending` cases against the in-memory fake.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. `AUTOINCREMENT` matters: it means a deleted max id is never reused.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(db): plugin registry assigns a source_id per guid`.

### Task 3: Discovery reads `plugin.json` first, resolves conflicts, imports by source_id

**Files:**
- Create: `src/netview/application/plugins/conflicts.py`
- Modify: `src/netview/infrastructure/plugins/discovery.py`, `folders.py`, `host.py` (the load path only), `src/netview/bootstrap.py`
- Test: `tests/unit/application/test_conflicts.py`, `tests/integration/plugins/test_discovery_conflicts.py`

**Interfaces:**
- Consumes: `uow.plugin_registry.assign/last_folders/set_last_folder` (Task 2), `PluginJson.guid` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class Candidate: card_key: str; guid: str | None; tier: int; folder: str | None`. Tiers: `0` built-in, `1` `plugin_dirs`, `2` `<data dir>/plugins`. `card_key` is `"entry_point:<name>"` or `"folder:<resolved path>"`.
  - `pick_winners(cands: Sequence[Candidate], last_folder: Mapping[str, str]) -> tuple[list[Candidate], dict[str, Candidate]]`: the winners, plus a map from each loser's card_key to the candidate that beat it. A candidate whose guid is `None` is neither (the caller makes it a failed card). Order per guid:
    1. tier 0;
    2. `folder == last_folder[guid]`;
    3. lower tier;
    4. folder path ascending.
  - `discover_plugin_classes` is split into:
    - `find_entry_points(group) -> list[DiscoveredPlugin]`;
    - `find_folders(bases: Sequence[tuple[Path, int]]) -> list[FolderCandidate]` (`folder`, `tier`, `plugin_json: PluginJson | None`, `error: str | None`), which does not import anything;
    - `import_folder(folder: Path, source_id: int) -> DiscoveredPlugin`, which imports as `netview_local_plugins.p<source_id>`.
  - A folder with no or invalid `plugin.json` becomes a failed card: "plugin.json is missing or invalid".
  - `manifest_mismatch(m: PluginManifest, pj: PluginJson) -> list[str]` in `validation.py`. It lists the names of the shared fields that differ (name, version, description, guid, display_name, plugin_type, sdk_version, capabilities, permissions). A non-empty result fails the plugin with "plugin.json and the manifest disagree on: <fields>".
  - After a winner loads, `set_last_folder(guid, folder)`.
  - Loser card error: `"Same guid as <winner name> (loaded from <winner folder or 'built in'>)"`.

- [ ] **Step 1: Failing tests**
  - `test_conflicts.py`:
    - `test_builtin_beats_folder`;
    - `test_last_folder_beats_tier`;
    - `test_plugin_dirs_beats_data_dir`;
    - `test_path_breaks_ties`;
    - `test_no_guid_is_neither_winner_nor_loser`.
  - `test_discovery_conflicts.py` (tmp dirs, copies of `plugins/roku` with its `tests` folder excluded):
    - `test_renamed_copy_never_displaces_original`: the repo `roku` in plugin_dirs plus `aaa_roku` in the data dir. Roku is `active`, the copy is `failed` with the error starting "Same guid as Roku", and `load_all()` does not raise.
    - `test_folder_name_irrelevant`: the folder `whatever` loads as `netview_local_plugins.p<n>`.
    - `test_missing_plugin_json_fails_card`.
    - `test_manifest_plugin_json_mismatch_fails`: the version is edited in `plugin.json` only, and the error names `version`.
    - `test_last_folder_recorded`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Bootstrap builds `[(data_dir/plugins, 2), *((d, 1) for d in plugin_dirs)]`. The host flow is:
  1. find;
  2. pick winners;
  3. assign source_ids for winners;
  4. import each winner;
  5. check the manifest against `plugin.json`;
  6. load.

  Keep `PluginInfo.id` = the legacy id in this task (Task 4 switches the keys).
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(plugins): guid conflicts resolved by fixed order; folders imported by source_id`.

### Task 4: Host, API and state keyed by guid and source_id; migration re-keys; backup

**Files:**
- Create: `src/netview/infrastructure/db/core_versions/0006_plugin_guid_keys.py`, `src/netview/infrastructure/db/backup.py`
- Modify:
  - `src/netview/application/ports/plugin_admin.py`
  - `src/netview/infrastructure/plugins/host.py`
  - `src/netview/application/plugins/context.py` and `src/netview/infrastructure/plugins/context.py`
  - `src/netview/bootstrap.py`
  - `src/netview/presentation/api/schemas.py`, `routers/plugins.py`, `app.py`
  - `src/netview/infrastructure/settings.py` (the `plugins` seed docs)
  - `plugins/conftest.py`
  - the plugins' `service.py` source labels (gsm7248, gs105e)
- Test: `tests/integration/plugins/test_host.py` (+ the gallery and review variants), `tests/integration/db/test_migrate.py`, `tests/integration/db/test_backup.py`, `tests/integration/api/test_plugins_api.py` (or the existing plugins API test)

**Interfaces:**
- Consumes: the Task 3 winners with `source_id`.
- Produces:
  - `PluginInfo` gains:
    - `guid: str | None`, `source_id: int | None`, `display_name: str`, `plugin_type: str | None`;
    - `card_key: str`;
    - `folder: str | None`: the folder name when the plugin lives directly in `<data dir>/plugins`, else `None`;
    - `uninstallable: bool`: true when `folder` is not `None`;
    - `owns_data: bool`: true for the winner card of its guid.
  - `PluginInfo.id` becomes `str(source_id)` for registered plugins, else `card_key`. `PluginOut` mirrors all of these.
  - Host records are keyed by `PluginInfo.id`. The scheduler owner, capability registry owner, `routers()` and `ui_contributions()` keys are all `str(source_id)`. `ui_module` = `/plugins/<source_id>/static/<module>`.
  - `plugin_state` rows are keyed by guid; the column stays `plugin_id`, and its docstring says it holds the guid. Seeds (`AppSettings.plugins`) are keyed by guid.
  - `PluginContext` loses `plugin_id` and gains `guid: str`, `source_id: int` and `display_name: str`. `context_factory(identity: PluginIdentity, settings)` takes `@dataclass(frozen=True) class PluginIdentity: guid: str; source_id: int; display_name: str` (in `application/plugins/context.py`). Logger name: `netview.plugin.p<source_id>`.
  - `backup_before_plugin_identity(db_path: Path, today: date) -> Path | None`: makes the backup when the core DB exists and its Alembic revision is below `0006`. Returns the path, or `None` if it was skipped.
  - Migration `0006` holds a literal copy of the legacy map (frozen on purpose: migrations must not import app code). It:
    - re-keys `plugin_state.plugin_id` from legacy id → guid;
    - re-keys each section's `plugin_id` in `inspection_reports.sections_json`;
    - re-keys `role_permissions.permission_id` from `<legacy>.<rest>` → `<guid>.<rest>`;
    - leaves rows with unknown ids alone and logs them.
  - gsm7248 and gs105e take their claim `source` label from `ctx.display_name` (same text as today).

- [ ] **Step 1: Failing tests**
  - `test_info_keys`: a loaded folder plugin has `id == str(source_id)`, and `ui_module.startswith(f"/plugins/{source_id}/static/")`.
  - `test_state_keyed_by_guid`: toggling enabled writes a `plugin_state` row whose key is the guid.
  - `test_seed_by_guid`.
  - `test_uninstallable_only_in_data_dir`: the same plugin is `uninstallable` in the data dir, and not in plugin_dirs or as a built-in.
  - `test_owns_data_winner_only`.
  - `test_migration_0006_rekeys`: a DB at 0005 seeded with:
    - `plugin_state('roku', …)`;
    - an inspection report whose section has `plugin_id: "inspection"`;
    - `role_permissions(…, 'gsm7248.console')`;
    - `plugin_state('mystery', …)`.

    After upgrade, those three become guid-keyed and `mystery` is unchanged.
  - `test_backup_made_once`: the backup exists after the first call, and the second call returns `None` without touching it.
  - `test_backup_skipped_when_already_migrated`.
  - API: `GET /api/v1/plugins` items carry `guid`, `source_id`, `display_name`, `plugin_type`, `card_key`, `uninstallable` and `owns_data`, and `GET /api/v1/plugins/<source_id>/…` reaches a sample plugin route.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Bootstrap order:
  1. backup;
  2. `upgrade_core`;
  3. host load.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(plugins): runtime keys use source_id, saved state uses guid; one-time re-key and backup`.

### Task 5: Auth adapts to guid permissions and source_id addresses

**Files:**
- Modify (real paths per Task 0's notes): `src/netview/application/auth/catalog.py` (`plugin_group`, `default_permission_for`), `src/netview/presentation/api/permissions.py` (`plugin_default_guard`), the auth middleware module, `src/netview/infrastructure/plugins/context.py` (`require`), `src/netview/presentation/api/app.py`, the JS auth gate (`loadPlugins` / `auth.can`)
- Test: `tests/integration/plugins/test_plugin_permissions.py`, `tests/integration/api/test_plugin_guards.py`, the JS test for `loadPlugins` if one exists

**Interfaces:**
- Consumes: `PluginInfo.guid` and `source_id` (Task 4).
- Produces:
  - Automatic plugin permission ids are `<guid>.view|use|configure`. Declared ones are `<guid>.<id>`, and labels still use the plugin name.
  - `ctx.require("console")` → `<guid>.console`.
  - The middleware's static rule maps `/plugins/<source_id>/static/…` to `<guid>.view` through a `source_id → guid` lookup supplied by the host. It replaces `plugin_ids: Callable[[], set[str]]` with `plugin_guids: Callable[[], Mapping[str, str]]`. An unknown source_id is passed through to routing, which gives a 404.
  - `plugin_default_guard(guid)` is used for routers mounted at `/api/v1/plugins/<source_id>`.
  - JS checks `auth.can(info.guid + ".view")`.

- [ ] **Step 1: Failing tests**
  - `test_permission_ids_use_guid`: `plugin_group(info)` ids are `[f"{G}.view", f"{G}.use", f"{G}.configure"]` for gsm7248's guid `G`.
  - `test_static_needs_guid_view`: a user holding `<guid>.view` gets 200 on `/plugins/<source_id>/static/ui.js`, and a user without it gets 403.
  - `test_api_default_guard_by_guid`.
  - `test_require_prefixes_guid`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(auth): plugin permissions keyed by guid; plugin addresses mapped from source_id`.

### Task 6 (front end): nav labels, guid on slots, report links, type chip

**Files:**
- Modify:
  - `src/netview/presentation/web/static/js/main.js`
  - `slots.js`
  - `report/dialog.js`
  - `settings/gallery.js`, `settings/installed.js`, `settings/plugins-tab.js`
  - `plugins/gs105e/static/report.js`
  - each plugin page spec whose `title` was its tab name (gsm7248 `page.js:133`, and the roku, gs105e and starlink pages, if any)
  - the CSS for the type chip
- Test: `tests/js/*.test.mjs` (main/nav, gallery, report dialog), `plugins/gs105e/tests/js/*`

**Interfaces:**
- Consumes: `PluginOut.guid`, `display_name`, `plugin_type`, `card_key`, and `id` (= source_id string).
- Produces:
  - Slot specs carry `pluginId` (the source_id string), `pluginGuid` and `pluginDisplayName`.
  - `navLabel(spec, pageCountForPlugin) -> string`: returns `pluginDisplayName` when the plugin has one page, else `${pluginDisplayName} · ${spec.title || spec.id}`.
  - The report dialog matches `s.pluginGuid === section.plugin_id`.
  - The gs105e report link is built from `pluginId` (passed in by the host), not `#/p/gs105e/…`.
  - Gallery cards are keyed by `card_key`, and the overlay opens by `card_key`.
  - `typeChipHtml(type) -> string` renders a chip with a label map (e.g. `access_point` → "Access point", `tv` → "TV", `iot` → "IoT", `nas` → "NAS", `ups` → "UPS"). It returns an empty string for `null`.

- [ ] **Step 1: Failing tests**
  - `navLabel` single-page and multi-page cases.
  - The report dialog matches by guid.
  - `installedCardHtml` uses `data-key="<card_key>"` and shows the type chip.
  - The gs105e report link uses the provided pluginId.
- [ ] **Step 2:** `npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement. Remove page `title` values that only repeated the plugin name.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): nav uses display_name; slots carry guid; cards keyed by card_key with a type chip`.

### Task 7: One database file per plugin

**Files:**
- Modify:
  - `src/netview/infrastructure/db/engine.py`, `migrate.py`
  - `src/netview/application/plugins/validation.py` (remove `validate_storage`)
  - `src/netview/infrastructure/plugins/context.py`, `host.py`
  - `src/netview/bootstrap.py`
  - `plugins/{gsm7248,gs105e,roku,starlink}/storage.py` and their migration files: table and index names lose the `<id>_` prefix, revision ids unchanged
  - tests that relied on `bad_prefix.py` (delete that sample plugin)
- Test: `tests/integration/db/test_plugin_engine.py`, `tests/integration/plugins/test_host.py`, each plugin's own storage tests

**Interfaces:**
- Produces:
  - `plugin_data_file(data_dir: Path, guid: str) -> Path`, which returns `data_dir / "plugin-data" / f"{guid}.db"`.
  - `make_plugin_engine(path: Path) -> Engine`: a WAL file engine whose authorizer denies `SQLITE_ATTACH` and `SQLITE_DETACH`, and nothing else.
  - `upgrade_plugin(engine: Engine, versions_dir: Path) -> None`, with version table `alembic_version`.
  - `DefaultPluginContext` gets `data_file: Path | None`. `unit_of_work()` raises `RuntimeError("this plugin declares no storage")` when it is `None`.
  - The host creates `plugin-data/` lazily, and only for plugins with storage.

- [ ] **Step 1: Failing tests**
  - `test_attach_denied`: `ATTACH DATABASE '<core db>' AS c` on a plugin engine raises.
  - `test_plugin_tables_live_in_own_file`: after loading the sample `good` plugin, its table exists in `<guid>.db` and not in `netview.db`.
  - `test_no_storage_no_file`.
  - `test_unit_of_work_without_storage_raises`.
  - The plugin storage tests still pass with the unprefixed names.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(plugins): each plugin keeps its tables in its own database file`.

### Task 8: Move legacy plugin tables out of `netview.db`

**Files:**
- Create: `src/netview/infrastructure/plugins/legacy.py`
- Modify: `src/netview/bootstrap.py`
- Test: `tests/integration/plugins/test_legacy_move.py`

**Interfaces:**
- Produces:
  - `LEGACY_PLUGIN_GUIDS: Mapping[str, str]`: the nine pairs from Global Constraints.
  - `move_legacy_plugin_tables(core_db: Path, data_dir: Path, legacy: Mapping[str, str] = LEGACY_PLUGIN_GUIDS) -> list[str]`: returns the legacy ids it moved. For each legacy id that has `<id>_*` tables or `alembic_version_<id>` in `core_db`, and whose `plugin_data_file(data_dir, guid)` does not exist:
    1. build `<guid>.db.part`;
    2. recreate each table and index with the prefix removed from its own name (and from `ON <table>` for indexes), taking the SQL from `sqlite_master`;
    3. copy the rows;
    4. copy the version row into `alembic_version`;
    5. rename `.part` → `.db`;
    6. drop the old tables and the version table in one core transaction.

    Any exception for that id deletes the `.part`, leaves `core_db` unchanged, logs the error, and moves on to the next id.
  - Bootstrap order: backup → `upgrade_core` → `move_legacy_plugin_tables` → host load.

- [ ] **Step 1: Failing tests** (fixtures build a core DB with `gsm7248_port_samples` (2 rows, 1 index), `roku_tvs` (1 row), `alembic_version_gsm7248='gsm7248_0001'` and `alembic_version_roku='roku_0001'`, using each plugin's real old CREATE SQL; check the real revision ids in each `0001_initial.py`):
  - `test_moves_tables_and_rows`: `<gsm guid>.db` has `port_samples` with 2 rows and the index, `alembic_version` = `gsm7248_0001`, and `netview.db` no longer has `gsm7248_*`.
  - `test_rerun_is_noop`: the second call returns `[]`.
  - `test_move_failure_leaves_core_db_untouched`: monkeypatch the row copy to raise on the second table. `netview.db` still has both old tables, and no `<guid>.db` or `.part` exists.
  - `test_existing_file_skips`.
  - `test_plugin_loads_on_moved_data`: run the move, then load gsm7248 from the repo folder against that data dir. The plugin is `active` and its migration is a no-op (same head).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(plugins): one-time move of legacy plugin tables into per-plugin files`.

### Task 9: Uninstall (server)

**Files:**
- Modify:
  - `src/netview/infrastructure/plugins/host.py`
  - `src/netview/infrastructure/plugins/folders.py` (`TRASH = ".trash"`, `clear_trash`, `finish_pending_uninstalls`)
  - `src/netview/application/ports/plugin_admin.py`
  - `src/netview/presentation/api/routers/plugins.py`, `schemas.py`, `app.py`
  - `src/netview/bootstrap.py`
- Test: `tests/integration/plugins/test_uninstall.py`, `tests/integration/api/test_plugins_uninstall_api.py`

**Interfaces:**
- Consumes: `PluginInfo.folder/owns_data` (Task 4), `plugin_data_file` (Task 7), the registry pending methods (Task 2).
- Produces:
  - `PluginAdmin.uninstall(folder: str, delete_data: bool) -> UninstallResult`, with `@dataclass class UninstallResult: finished: bool; error: str | None`. It raises:
    - `ConflictError` when the folder is not a direct, non-dot child of `<data dir>/plugins` after `resolve()`, or when `delete_data` is set and the folder's card does not own the data;
    - `NotFoundError` when the folder is unknown.
  - Steps, in order:
    1. Stop the plugin. This means `scheduler.remove_owner(key)`, `registry.unregister_plugin(key)`, `plugin.shutdown()` and `_close_context(ctx)`, after which the record is removed and `key` is added to `self._gone`.
    2. Rename the folder to `.trash/<folder>-<epoch ms>`. If that fails, record `add_pending_uninstall(resolved)` and return `finished=False` with the error text.
    3. `shutil.rmtree` the trash entry (ignore errors; `clear_trash` at the next start finishes it).
    4. If `delete_data`: unlink `<guid>.db`, `-wal` and `-shm`, then `plugin_state.delete(guid)`.
    5. The registry row stays.
  - `PluginHost.is_present(source_id: str) -> bool`.
  - `create_app` mounts plugin routers with `Depends(plugin_present(source_id))`, which raises `NotFoundError` once `is_present` is false. Plugin static files use `PresentStaticFiles(directory, present: Callable[[], bool])`, which answers 404 when not present.
  - Startup: `clear_staging`, then `finish_pending_uninstalls(base, pending, clear)` (move each to trash and delete it, clearing on success) and `clear_trash`. This runs after `upgrade_core` and before discovery.
  - `POST /api/v1/plugins/uninstall` takes `UninstallIn{folder: str, delete_data: bool = False}` and returns `UninstallOut{finished: bool, error: str | None}`, guarded by `require_admin`.

- [ ] **Step 1: Failing tests**
  - `test_uninstall_removes_folder_and_card`: the folder is gone, `list()` lacks the card, and the scheduler has no jobs for the key.
  - `test_uninstall_refused_outside_data_dir`: plugin_dirs plugin, built-in, `..`, `.staging`, and a junction or symlink pointing outside (skip the symlink case if the OS refuses to create it).
  - `test_keep_data_by_default`: `<guid>.db` and the state row remain. A reinstall (copying the folder back and restarting the host) gets the same `source_id` and its settings.
  - `test_delete_data_removes_file_and_state`.
  - `test_delete_data_refused_for_duplicate`: the owner's file and state are untouched.
  - `test_uninstall_pending_card`: a folder added after start is removed.
  - `test_rename_failure_marks_pending`: monkeypatch `Path.rename` to raise `PermissionError`. The result is `finished=False`, the folder is in `pending_uninstalls()`, and a new host start removes it without loading it.
  - `test_routes_404_after_uninstall`: the plugin API and static paths return 404.
  - `test_uninstall_requires_admin` (API).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(plugins): uninstall plugins from the data folder`.

### Task 10 (front end): Uninstall button, dialog and live removal

**Files:**
- Modify:
  - `src/netview/presentation/web/static/js/settings/plugins-tab.js` (the overlay body)
  - `settings/gallery.js`, `settings/available.js`
  - `slots.js`, `main.js`, `nav.js`
  - `toast.js` usage
  - CSS for the danger button and dialog (reuse the existing dialog and button tokens)
- Test: `tests/js/uninstall.test.mjs`, `tests/js/slots.test.mjs`

**Interfaces:**
- Consumes: `POST /api/v1/plugins/uninstall`, `PluginOut.uninstallable/owns_data/folder/name/id`.
- Produces:
  - `uninstallSectionHtml(info) -> string`: returns `""` unless `info.uninstallable`.
  - `confirmUninstallHtml(info) -> string`, with the copy from Global Constraints. The checkbox appears only when `info.owns_data`.
  - `host.removePlugin(pluginId)` in `slots.js`: drops every slot whose `pluginId` matches, then triggers the existing nav re-render. If the current route belongs to that plugin, it navigates to `#/`.
  - On success, the client closes the overlay, removes the card, calls `removePlugin`, refreshes the Available list (`GET /api/v1/plugins/catalog`) and shows the toast.
  - On `finished=false`, the card stays and shows the failure copy.

- [ ] **Step 1: Failing tests**
  - The section is hidden for a built-in and for a plugin_dirs plugin.
  - The dialog has the checkbox only when `owns_data`.
  - The dialog copy is exact.
  - `removePlugin` drops the slots and reports whether the current route was affected.
- [ ] **Step 2:** `npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): uninstall from the plugin overlay`.

### Task 11: Catalog and install by guid; remove the author `id`; SDK 2.0

**Files:**
- Modify:
  - `src/netview/application/plugins/manifest.py` (drop `id`, `SDK_VERSION = "2.0"`)
  - `validation.py` (drop `PLUGIN_ID_RE`/`RESERVED_PLUGIN_IDS` use for manifests; keep a path-segment regex)
  - `plugin_json.py` (`PLUGIN_JSON_SCHEMA = "netview.plugin/2"`, `INDEX_SCHEMA = "netview.plugin-index/2"`, no `id`)
  - `src/netview/application/usecases/plugin_catalog.py`, `install_plugin.py`
  - `src/netview/infrastructure/plugins/installer.py`, `host.py` (`_pending_info`), `catalog_http.py`
  - `scripts/build_plugin_index.py`
  - all nine plugins, the four `plugin.json` files and the sample plugins (`sdk_version ">=2.0,<3"`)
  - `plugins/index.json`, `catalog.json` (regenerate)
  - `src/netview/sdk/__init__.py`
  - `settings/available.js`, `installer.js` (install by guid)
- Test: the existing catalog, installer, plugin_json, index-fresh and SDK-export tests, updated

**Interfaces:**
- Produces:
  - `AvailablePlugin` and the API carry `guid`. `InstallIn{guid: str}`. `InstallJob.plugin_id` → `guid`. `CatalogService.entry(guid)`. Known/installed matching uses the set of guids from `admin.list()` plus every guid found in a `plugin.json` under `<data dir>/plugins`.
  - Index entry `path`:
    - must match `^plugins/[a-z0-9][a-z0-9_-]*$`;
    - its last segment is the install folder name;
    - duplicate guids are refused.
  - `ZipPluginInstaller.install`:
    - target folder = last path segment, then `-2`, `-3`… while one exists;
    - refuses with `ConflictError("<name> is already installed")` when the guid is known;
    - checks that the staged `plugin.json` guid equals the entry's guid.
  - The SDK version is `2.0`, and every plugin declares `">=2.0,<3"`.

- [ ] **Step 1: Failing tests**
  - `test_available_hides_installed_by_guid`.
  - `test_install_suffixes_existing_folder_name`.
  - `test_install_refuses_known_guid`.
  - `test_index_rejects_bad_path`.
  - `test_index_rejects_duplicate_guid`.
  - `test_plugin_json_v2_has_no_id`: an `id` key raises "unknown field id".
  - `test_sdk_version_is_2`.
  - The existing tests are updated for the new schema ids.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. `grep -rn "manifest.id\|\.plugin\.id\|pj\.id" src plugins tests scripts` must return nothing at the end.
- [ ] **Step 4:** Gates. Expected: PASS.
- [ ] **Step 5:** Commit `feat(plugins)!: guid replaces the author id everywhere; SDK 2.0`.

### Task 12: Docs, memory and the browser check (controller)

- [ ] **Step 1:** Update the SDK and plugin-author docs, plus `docs/superpowers/deferred.md`:
  - the new fields;
  - the `plugin_type` list;
  - the data file;
  - no table prefix;
  - uninstall.

  Commit `docs: plugin identity and uninstall`.
- [ ] **Step 2: Browser check (Claude, not the user)**
  1. Make a copy of `network/netview-dev`, using SQLite backup for `netview.db`, in a session scratchpad. Add a HomeLab launch config `netview-identity` (port 8773) running this worktree against the copy with `--plugin-dir` this worktree's `plugins`.
  2. Check that the dev data survived the move: the Roku TV list (2 TVs), the GSM7248 settings and the Starlink history chart are all present.
  3. Check that the nav tabs read GSM7248, GS105E, Roku and Starlink, and that each card shows its type chip.
  4. Start `scripts/serve_fake_plugin_repo.py --execute` with `NETVIEW_PLUGIN_CATALOG_URL`. Install Starlink into the copy's data dir and restart. Uninstall it, with and without "delete data", and check:
     - the card is gone;
     - the nav tab is gone without a reload;
     - Starlink is back in Available;
     - its API returns 404.
  5. Copy `roku` into the data dir as `aaa_roku` and restart. The original Roku is active, and the copy has a red card with Uninstall. Uninstall the copy.
  6. Screenshots of steps 3–5.
- [ ] **Step 3:** Run all gates one final time, then a whole-branch review (Opus).
