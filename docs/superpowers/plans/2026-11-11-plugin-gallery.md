# Plugin Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-plugin Settings entries with a collapsible Plugins group holding an Installed gallery (cards + settings overlay) and an Available gallery (install from the GitHub `plugins/` folder), and add animated status dots used across the core UI.

**Architecture:** Each folder plugin gains a static `plugin.json`; a generated `plugins/index.json` (also bundled in the package) is the catalog, cached in one core table and refreshed from GitHub on demand. Installs download the repo archive, extract one plugin folder into `<data dir>/plugins/<id>` through a staging folder, and the plugin loads at the next start; until then the host reports it as `pending`. The UI is plain JS: new gallery, overlay and dot modules, with pure helpers covered by `node --test`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 + Alembic, stdlib `urllib`/`zipfile`, plain ES modules, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-11-plugin-gallery-design.md` (mockup: `docs/superpowers/specs/2026-11-11-plugin-gallery-mockup.html`). Read both before any task.

## Global Constraints

- Work in worktree `R:\source\claude projects\HomeLab\netview-plugin-gallery`, branch `feature/plugin-gallery`. Never commit with the work email; the repo's `user.email` is the GitHub no-reply address. Never push.
- No new runtime dependencies. HTTP with `urllib.request`, archives with `zipfile`.
- Clean Architecture: `domain` and `application` never import `infrastructure` or `presentation` (`lint-imports` enforces it). `application` is mypy-strict.
- `app.css` has no hex or `rgb()` literals; colours come from theme tokens, glows via `color-mix(in srgb, var(--x) 30%, transparent)`.
- Catalog URL default: `https://raw.githubusercontent.com/Cadtastic/NetView/main/plugins/index.json`. Catalog fetch: timeout 10 s, response cap 1 MB (1_000_000 bytes), header `User-Agent: netview/<package version>`, no other identifying data.
- Archive download: cap 50 MB (50_000_000 bytes), per-read timeout 30 s. Unpacked cap 20 MB (20_000_000 bytes). Skip `tests/` and `__pycache__/` inside the plugin folder.
- Catalog cache max age before the UI asks for a refresh: 1 hour (3_600_000 ms).
- Plugin id pattern stays `^[a-z][a-z0-9_]*$`. Reserved ids (would collide with core routes): `catalog`, `install`.
- `plugin.json` schema id `netview.plugin/1`; index schema id `netview.plugin-index/1`.
- Status dot: 16 px (cards, overlay header, watches), 10 px `sm` (rail, nav, tables). Glow ring 4 px at ~30 %. Motion: ok = outward ring pulse ~2 s loop; warn = opacity fade ~3 s loop; bad/restart = on/off flash 1 s (`steps(1,end)`); off/idle = none. Only the `::before` disc animates; the tooltip never animates and is fully opaque. No `cursor: help`. `@media (prefers-reduced-motion: reduce)` sets `animation: none` on the disc explicitly.
- Exact UI copy (verbatim): "Installed", "Available", "Plugins", "Available plugins", "Installed plugins", "Refresh", "Install", "Queued", "Downloading… N%", "Installing…", "Awaiting restart", "Active", "Off", "Needs configuring", "Failed: <first line of error>", "Built in", "Folder", "Just installed", "Loads the next time netview starts", "This plugin loads the next time netview starts. Its settings appear after that.", "<name> installed. Restart netview to load it.", "Needs a newer netview", "Needs <package>, which this netview does not have", "Every available plugin is installed.", "No plugins found.", "Couldn't reach GitHub. Check the connection and press Refresh.", "Couldn't reach GitHub", "Couldn't read the plugin list (<code>)", "From github.com/Cadtastic/NetView · checked <age>", "· showing the list from <date>".
- Gates after every task: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src plugins`, `uv run lint-imports`, `npm test`. All must pass before the commit.

## Review Focus

1. **A plugin id equal to a core route segment** (`catalog`, `install`): a reasonable person expects the plugin to be refused, not to shadow `/api/v1/plugins/catalog`. Pinned in Task 3 (`test_reserved_plugin_ids_are_refused`) and Task 2 (`test_index_rejects_reserved_id`).
2. **Archive entries with Windows-style escapes** (`..\\x`, `C:/x`, `\\\\server\\x`, names with a drive letter) on this Windows host: expected to be refused like `../`. Pinned in Task 5 (`test_extract_refuses_windows_paths`).
3. **Target folder already exists without `plugin.json`** (a manual copy that never loaded, so it is neither loaded nor pending): expected 409 and the staged copy removed, never a merge. Pinned in Task 5 (`test_install_refuses_existing_folder`).
4. **A catalog response that is JSON but wrong** (a list, wrong schema id, entry path not `plugins/<id>`, duplicate ids, over 1 MB): expected the old cache kept and the error shown. Pinned in Task 4 (`test_refresh_keeps_old_index_on_bad_payload`).
5. **Overlay open while its plugin is toggled or saved**, and `openSettings("plugin:<unknown>")`: expected the overlay to redraw in place (never jump to Appearance), and an unknown id to land on Installed with no overlay. Pinned in Task 7 (`resolveTab` tests) and Task 8 (`ctx.redraw` test).

---

## File Map

| File | Responsibility |
|---|---|
| `src/netview/application/plugins/plugin_json.py` (new) | `PluginJson`, `CatalogEntry`, `PluginIndex`; parse/validate/serialize; `build_index`; `installable` |
| `src/netview/application/ports/plugin_catalog.py` (new) | `CatalogFetcher`, `CatalogStore`, `CatalogSnapshot`, `PluginInstaller` protocols |
| `src/netview/application/usecases/plugin_catalog.py` (new) | `PluginCatalogService`, `CatalogView`, `AvailablePlugin` |
| `src/netview/application/usecases/install_plugin.py` (new) | `InstallJobs`, `InstallJob` |
| `src/netview/domain/errors.py` | add `ConflictError`, `CatalogUnavailableError`, `InstallError` |
| `src/netview/application/ports/plugin_admin.py` | `PluginInfo.source`, `state` gains `"pending"` |
| `src/netview/application/plugins/validation.py` | `RESERVED_PLUGIN_IDS` |
| `src/netview/infrastructure/plugins/discovery.py` | `DiscoveredPlugin.folder`; skip dot folders |
| `src/netview/infrastructure/plugins/folders.py` (new) | read `plugin.json`, find pending folders, clear staging |
| `src/netview/infrastructure/plugins/host.py` | source, failed-folder records, pending entries, 409 on pending |
| `src/netview/infrastructure/plugins/catalog_http.py` (new) | `HttpCatalogFetcher`, `bundled_index` |
| `src/netview/infrastructure/plugins/catalog.json` (new, generated) | bundled index |
| `src/netview/infrastructure/plugins/installer.py` (new) | `extract_plugin`, `ZipPluginInstaller` |
| `src/netview/infrastructure/db/models.py`, `core_versions/0003_plugin_catalog.py` (new), `catalog_store.py` (new) | cache table and `SqlCatalogStore` |
| `src/netview/infrastructure/settings.py` | `plugin_catalog_url` |
| `src/netview/bootstrap.py`, `application/services.py` | wiring |
| `src/netview/presentation/api/routers/plugins.py`, `schemas.py`, `errors.py` | catalog and install endpoints, 409 mapping |
| `plugins/gsm7248/plugin.json`, `plugins/starlink/plugin.json`, `plugins/index.json` (new) | plugin metadata and index |
| `scripts/build_plugin_index.py`, `scripts/serve_fake_plugin_repo.py` (new) | index builder; fake GitHub for the browser pass |
| `static/js/dot.js` (new) | `dotHtml` |
| `static/js/settings/gallery.js` (new) | pure gallery helpers |
| `static/js/settings/installed.js`, `overlay.js`, `available.js` (new) | the two galleries and the overlay |
| `static/js/settings/dialog.js`, `plugins-tab.js` | grouped rail, tab ids, `ctx.redraw` |
| `static/js/cards/watches.js`, `nav.js`, `pages/devices.js` | dots elsewhere |
| `static/css/app.css`, `themes/daylight.css`, `themes/contrast.css`, `themes/README.md` | dot, solid chip, gallery, overlay styles; chip tokens |
| `README.md`, `docs/superpowers/deferred.md` | plugin.json authoring note; deferred items |

---

### Task 1: plugin.json model, files and agreement test

**Files:**
- Create: `src/netview/application/plugins/plugin_json.py`, `plugins/gsm7248/plugin.json`, `plugins/starlink/plugin.json`
- Modify: `src/netview/domain/errors.py`, `README.md` (plugin authoring section: a folder plugin ships `plugin.json`; fields as in the spec; needed to be listed in Available)
- Test: `tests/unit/application/test_plugin_json.py`, `tests/integration/plugins/test_plugin_json_agreement.py`

**Interfaces:**
- Produces:
  - `domain/errors.py`: `class ConflictError(NetviewError)`, `class CatalogUnavailableError(NetviewError)`, `class InstallError(NetviewError)`.
  - `PLUGIN_JSON_SCHEMA = "netview.plugin/1"`, `INDEX_SCHEMA = "netview.plugin-index/1"`.
  - `@dataclass(frozen=True) class PluginJson: id: str; name: str; version: str; description: str; sdk_version: str; capabilities: tuple[str, ...]; permissions: tuple[str, ...]; author: str | None = None; homepage: str | None = None; license: str | None = None; requires: tuple[str, ...] = ()` (capabilities/permissions sorted).
  - `parse_plugin_json(data: object) -> PluginJson` — raises `ValidationError` naming the first bad field. Rules: object; `schema == PLUGIN_JSON_SCHEMA`; required strings non-empty; `id` matches `PLUGIN_ID_RE`; `sdk_version` parses as `SpecifierSet`; capabilities are `Capability` values; permissions are `Permission` values; optional strings are strings; `requires` list of non-empty strings.
  - `plugin_json_to_dict(pj: PluginJson) -> dict[str, object]` (includes `schema`, omits `None` optionals, lists sorted).

- [ ] **Step 1: Write failing unit tests** in `tests/unit/application/test_plugin_json.py`:
  - `test_parse_minimal_plugin_json` — the spec example (with the 7 gsm7248 permissions, no `license`) parses; `pj.capabilities == ("api", "jobs", "storage", "web_ui")`.
  - `test_parse_rejects_wrong_schema`, `test_parse_rejects_bad_id` (`"Bad-Id"`), `test_parse_rejects_unknown_capability` (`"teleport"`), `test_parse_rejects_bad_sdk_spec` (`">>1"`), `test_parse_rejects_non_object` (`[]`) — each `pytest.raises(ValidationError)`.
  - `test_round_trip` — `parse_plugin_json(plugin_json_to_dict(pj)) == pj`.
- [ ] **Step 2:** Run `uv run pytest tests/unit/application/test_plugin_json.py -q` — FAIL (module missing).
- [ ] **Step 3:** Add the errors and implement `plugin_json.py` as above.
- [ ] **Step 4:** Write `plugins/gsm7248/plugin.json` and `plugins/starlink/plugin.json` from each plugin's Python manifest (id, name, version, description, sdk_version, capabilities, permissions), `author: "Cadtastic"`, `homepage: "https://github.com/Cadtastic/NetView/tree/main/plugins/<id>"`, no `license` (repo has no LICENSE), `requires: []`.
- [ ] **Step 5: Write agreement test** `tests/integration/plugins/test_plugin_json_agreement.py::test_plugin_json_matches_manifest` — for every `plugins/*/plugin.json` (repo root), import the folder via `discover_plugin_classes(extra_dirs=[<repo>/plugins])`, find the class with the same id, and assert id, name, version, description, sdk_version, sorted capabilities, sorted permissions all equal. Also `test_every_loadable_folder_plugin_has_plugin_json` — every folder under `plugins/` with `__init__.py` has a `plugin.json`.
- [ ] **Step 6:** Run all gates — PASS.
- [ ] **Step 7: Commit** `feat(plugins): plugin.json metadata for folder plugins`.

### Task 2: Index builder, plugins/index.json and the bundled copy

**Files:**
- Modify: `src/netview/application/plugins/plugin_json.py`, `src/netview/application/plugins/validation.py`
- Create: `scripts/build_plugin_index.py`, `plugins/index.json`, `src/netview/infrastructure/plugins/catalog.json`
- Test: `tests/unit/application/test_plugin_index.py`, `tests/integration/test_plugin_index_fresh.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces (in `plugin_json.py`):
  - `@dataclass(frozen=True) class CatalogEntry: plugin: PluginJson; path: str`
  - `@dataclass(frozen=True) class PluginIndex: ref: str; archive_url: str; plugins: tuple[CatalogEntry, ...]` (sorted by id)
  - `DEFAULT_ARCHIVE_URL = "https://codeload.github.com/Cadtastic/NetView/zip/refs/heads/main"`
  - `build_index(plugins: Iterable[PluginJson], ref: str, archive_url: str) -> PluginIndex`
  - `index_to_dict(index: PluginIndex) -> dict[str, object]` → `{"schema": INDEX_SCHEMA, "ref", "archive_url", "plugins": [plugin_json_to_dict(p) + {"path": "plugins/<id>"}]}`. No timestamp (keeps the file deterministic; the spec's `generated` field is dropped for that reason).
  - `parse_index(data: object) -> PluginIndex` — raises `ValidationError`. Rules: object; schema; `ref` and `archive_url` non-empty strings, `archive_url` starts with `https://` or `http://127.0.0.1` / `http://localhost` (the fake); each entry parses with `parse_plugin_json` (entries carry `schema`), `path == f"plugins/{id}"`, ids unique, id not in `RESERVED_PLUGIN_IDS` (this task adds `RESERVED_PLUGIN_IDS = frozenset({"catalog", "install"})` to `application/plugins/validation.py`; Task 3 makes `validate_manifest` use it).

- [ ] **Step 1: Failing tests** `tests/unit/application/test_plugin_index.py`: `test_index_round_trip`, `test_index_sorted_by_id`, `test_index_rejects_path_mismatch`, `test_index_rejects_duplicate_ids`, `test_index_rejects_reserved_id`, `test_index_rejects_wrong_schema`, `test_index_rejects_plain_http_archive` (`http://example.com/x.zip`).
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement the functions.
- [ ] **Step 4:** Write `scripts/build_plugin_index.py`: module docstring (purpose, usage, outputs, schema id), `sys.dont_write_bytecode = True`, args `--plugins-dir` (default `plugins`), `--ref` (default `main`), `--archive-url` (default `DEFAULT_ARCHIVE_URL`), `--out` (default `plugins/index.json`), `--bundle` (default `src/netview/infrastructure/plugins/catalog.json`), `--execute` (write both files; otherwise print what would change), `--check` (exit 1 if either file differs). Reads every `<plugins-dir>/*/plugin.json` (UTF-8, BOM accepted), folder name must equal id. Writes JSON with `indent=2`, `sort_keys=False`, trailing newline, UTF-8. One-line summary.
- [ ] **Step 5:** Run `uv run python scripts/build_plugin_index.py --execute`; commit the two generated files.
- [ ] **Step 6: Freshness test** `tests/integration/test_plugin_index_fresh.py::test_committed_index_is_fresh` — runs the script with `--check` via `subprocess` (cwd repo root) and asserts exit 0; `test_bundled_index_parses` — `parse_index(json.loads(catalog.json))` succeeds and lists `gsm7248` and `starlink`.
- [ ] **Step 7:** Gates — PASS. **Commit** `feat(plugins): plugin index builder, index.json and bundled catalog`.

### Task 3: Host — sources, failed folders, pending plugins, reserved ids

**Files:**
- Modify: `src/netview/application/ports/plugin_admin.py`, `src/netview/application/plugins/validation.py`, `src/netview/infrastructure/plugins/discovery.py`, `src/netview/infrastructure/plugins/host.py`, `src/netview/presentation/api/schemas.py`, `src/netview/presentation/api/errors.py`, `src/netview/bootstrap.py` (pass `folders=plugin_folders(settings)` to `PluginHost`)
- Create: `src/netview/infrastructure/plugins/folders.py`
- Test: `tests/integration/plugins/test_host_gallery.py`, `tests/integration/api/test_plugins_api.py` (extend), `tests/integration/plugins/test_validation.py` (extend)

**Interfaces:**
- Consumes: `read` side of Task 1 (`parse_plugin_json`).
- Produces:
  - `PluginInfo.state: Literal["active", "disabled", "failed", "pending"]`; `PluginInfo.source: Literal["builtin", "folder"] = "builtin"`. `PluginOut` mirrors both.
  - `validate_manifest` uses `RESERVED_PLUGIN_IDS` (from Task 2) and adds `f"plugin id {m.id!r} is reserved"`.
  - `DiscoveredPlugin.folder: Path | None = None` (set for folder sources); `_from_dirs` skips folders whose name starts with `.`.
  - `folders.py`: `STAGING = ".staging"`; `read_plugin_json(folder: Path) -> PluginJson | None` (missing or invalid → `None`, invalid logs a warning); `folder_plugins(bases: Sequence[Path]) -> list[tuple[Path, PluginJson]]` (subfolders not starting with `.`, with `__init__.py` and a valid `plugin.json`, sorted by id); `clear_staging(base: Path) -> None`.
  - `PluginHost(..., folders: Sequence[Path] = ())`. Behaviour:
    - loaded from a folder → `info.source = "folder"`; from an entry point → `"builtin"`.
    - a failed folder discovery whose folder has a valid `plugin.json` → record keyed by that id (unless taken) with its name, version, description, capabilities, permissions, `state="failed"`, `source="folder"`, the import error.
    - `list()` = records plus, for each `folder_plugins(folders)` id not in records, `PluginInfo(state="pending", source="folder", enabled=True, ...)` from `plugin.json`. Scanned on every call.
    - `get(id)` finds pending too. `update_settings` / `set_enabled` on a pending id raise `ConflictError(f"{name} loads the next time netview starts")`.
  - `errors.py`: `ConflictError` → 409; `InstallError` → 422; `CatalogUnavailableError` → 503.

- [ ] **Step 1: Failing tests** in `tests/integration/plugins/test_host_gallery.py` (use `tmp_path` folders and the existing `sample_plugins` fixtures / helpers in `tests/integration/plugins/conftest.py`):
  - `test_folder_plugin_reports_source_folder` and `test_entry_point_plugin_reports_builtin`.
  - `test_failed_folder_with_plugin_json_shows_once_as_failed` — folder whose `__init__.py` raises `ImportError`; `list()` has exactly one entry with the `plugin.json` id, `state == "failed"`, error mentions `ImportError`, and no `pending` entry.
  - `test_failed_folder_without_plugin_json_keeps_path_record` — id starts with `folder:`.
  - `test_folder_added_after_start_is_pending` — after `load_all()`, copy a folder with `plugin.json` into a base; `list()` gains `state == "pending"`, `source == "folder"`; `get(id)` returns it.
  - `test_pending_patch_is_conflict` — `set_enabled` and `update_settings` raise `ConflictError`.
  - `test_dot_folders_are_skipped` — `.staging/x/__init__.py` is neither loaded nor pending.
  - `test_reserved_plugin_ids_are_refused` (in `test_validation.py`) — manifest id `catalog` → error contains `"is reserved"`.
  - API: `test_pending_plugin_listed_with_state` and `test_patch_pending_is_409` in `test_plugins_api.py` (fake admin returns a pending info / raises `ConflictError`).
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement. Keep `_load_one(cls, seen_ids)` and pass the source in via a new keyword `source: Literal["builtin","folder"]`.
- [ ] **Step 4:** Gates — PASS. Also `grep` the JS for consumers of `/api/v1/plugins` (`main.js`, `nav.js`, `slots.js`/host loader) and confirm `pending` entries are harmless (no `ui_module`, `needsSetup` false since state is not `active`); add a JS test `pending plugins never disable or add nav items` in `tests/js/nav.test.mjs`.
- [ ] **Step 5: Commit** `feat(plugins): pending and failed folder plugins, plugin sources, reserved ids`.

### Task 4: Catalog cache, fetcher and service; catalog endpoints

**Files:**
- Create: `src/netview/application/ports/plugin_catalog.py`, `src/netview/application/usecases/plugin_catalog.py`, `src/netview/infrastructure/plugins/catalog_http.py`, `src/netview/infrastructure/db/catalog_store.py`, `src/netview/infrastructure/db/core_versions/0003_plugin_catalog.py`
- Modify: `src/netview/infrastructure/db/models.py`, `src/netview/infrastructure/settings.py`, `src/netview/application/services.py`, `src/netview/bootstrap.py`, `src/netview/presentation/api/routers/plugins.py`, `src/netview/presentation/api/schemas.py`, `tests/integration/api/api_helpers.py`
- Test: `tests/unit/application/test_plugin_catalog.py`, `tests/integration/db/test_catalog_store.py`, `tests/integration/plugins/test_catalog_http.py`, `tests/integration/api/test_catalog_api.py`

**Interfaces:**
- Consumes: `PluginIndex`, `parse_index`, `index_to_dict`, `installable` (define here), `PluginAdmin.list()`.
- Produces:
  - `plugin_json.py`: `installable(pj: PluginJson, sdk_version: str, has_package: Callable[[str], bool]) -> str | None` → `"Needs a newer netview"` when `Version(sdk_version) not in SpecifierSet(pj.sdk_version)`; else first missing `requires` → `f"Needs {pkg}, which this netview does not have"`; else `None`.
  - `ports/plugin_catalog.py`:
    - `@dataclass class CatalogSnapshot: index: PluginIndex | None; source: str; fetched_at_ms: int | None; error: str | None`
    - `class CatalogFetcher(Protocol): source: str; def fetch(self) -> PluginIndex: ...` (raises `CatalogUnavailableError(user_message)`)
    - `class CatalogStore(Protocol): def load(self) -> CatalogSnapshot | None: ...; def save(self, snapshot: CatalogSnapshot) -> None: ...`
  - `usecases/plugin_catalog.py`:
    - `@dataclass(frozen=True) class AvailablePlugin: entry: CatalogEntry; reason: str | None` (`installable` = `reason is None`)
    - `@dataclass(frozen=True) class CatalogView: source: str; fetched_at_ms: int | None; error: str | None; stale: bool; plugins: list[AvailablePlugin]`
    - `class PluginCatalogService(store: CatalogStore, fetcher: CatalogFetcher, bundled: Callable[[], PluginIndex], admin: PluginAdmin, clock: Clock, sdk_version: str, has_package: Callable[[str], bool], max_age_ms: int = 3_600_000)`; methods `view() -> CatalogView` (never touches the network; seeds the store from `bundled()` with `fetched_at_ms=None`, `source="bundled"` when empty; `stale` = never fetched or older than `max_age_ms`), `refresh() -> CatalogView` (fetch; success saves index, time, `error=None`; failure keeps the old index and saves the error), `entry(plugin_id: str) -> CatalogEntry` (raises `NotFoundError`), `index() -> PluginIndex | None`.
    - `plugins` excludes every id in `admin.list()` (any state, pending included); sorted by name.
  - `catalog_http.py`: `class HttpCatalogFetcher(url: str, timeout_s: float = 10.0, max_bytes: int = 1_000_000, opener: Callable[..., Any] = urllib.request.urlopen)`; `source = url`. HTTP status error → `CatalogUnavailableError(f"Couldn't read the plugin list ({code})")`; network error/timeout → `CatalogUnavailableError("Couldn't reach GitHub")`; body over cap, bad JSON or `parse_index` failure → `CatalogUnavailableError(f"Couldn't read the plugin list ({reason})")`. `bundled_index() -> PluginIndex` loads `catalog.json` via `importlib.resources`.
  - DB: table `plugin_catalog_cache` (`id` int PK always 1, `source` text, `fetched_at_ms` bigint null, `payload` text null = `json.dumps(index_to_dict(...))`, `error` text null). Migration `0003`, `down_revision = "0002"`. `SqlCatalogStore(sessions: sessionmaker[Session])`.
  - `AppSettings.plugin_catalog_url: str = "https://raw.githubusercontent.com/Cadtastic/NetView/main/plugins/index.json"` (env `NETVIEW_PLUGIN_CATALOG_URL`).
  - `AppServices.catalog: PluginCatalogService`.
  - API (declare these routes **above** `/plugins/{plugin_id}` in `routers/plugins.py`): `GET /plugins/catalog` → `CatalogOut`; `POST /plugins/catalog/refresh` → `CatalogOut`. `CatalogOut = {source, fetched_at_ms, error, stale, plugins: [AvailableOut]}`, `AvailableOut = plugin_json fields + path + installable: bool + reason: str | None`.

- [ ] **Step 1: Failing unit tests** `tests/unit/application/test_plugin_catalog.py` with in-memory fakes:
  - `test_view_seeds_from_bundled_when_empty` (source `"bundled"`, `stale is True`).
  - `test_view_excludes_installed_and_pending_ids`.
  - `test_refresh_success_saves_and_clears_error`.
  - `test_refresh_keeps_old_index_on_bad_payload` — fetcher raises `CatalogUnavailableError("Couldn't read the plugin list (wrong schema)")`; view still lists the old plugins and `error` equals that text.
  - `test_installable_reasons` — sdk `">=9"` → `"Needs a newer netview"`; requires `["nopkg"]` with `has_package=lambda n: False` → `"Needs nopkg, which this netview does not have"`.
  - `test_stale_after_one_hour` (clock advanced 3_600_001 ms).
- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement ports and service.
- [ ] **Step 4: Failing infra tests:** `test_catalog_store.py::test_save_load_round_trip` and `::test_load_empty_is_none` (sqlite in `tmp_path`, `upgrade_core`); `test_catalog_http.py` with a fake `opener`: `test_http_404_message`, `test_unreachable_message`, `test_oversize_refused` (1_000_001 bytes), `test_valid_index_parses`, `test_list_payload_refused`.
- [ ] **Step 5:** Implement store, migration, fetcher, settings field; wire in `bootstrap.build_container` (`has_package` = `importlib.metadata.distribution` succeeds; `sdk_version=SDK_VERSION`); add the catalog service to the world builder in `api_helpers.py` (the real service over in-memory fakes).
- [ ] **Step 6: API tests** `test_catalog_api.py`: `test_get_catalog_lists_available`, `test_refresh_returns_error_text`, `test_catalog_route_not_shadowed_by_plugin_id` (GET `/api/v1/plugins/catalog` returns the catalog shape, not a 404 for plugin `catalog`). Implement routes.
- [ ] **Step 7:** Gates — PASS. **Commit** `feat(plugins): cached plugin catalog from GitHub with bundled fallback`.

### Task 5: Installer and install jobs; install endpoints

**Files:**
- Create: `src/netview/infrastructure/plugins/installer.py`, `src/netview/application/usecases/install_plugin.py`
- Modify: `src/netview/application/ports/plugin_catalog.py` (add `PluginInstaller`), `src/netview/application/services.py`, `src/netview/bootstrap.py` (call `clear_staging(settings.data_dir / "plugins")` before discovery; build installer and jobs), `src/netview/presentation/api/routers/plugins.py`, `schemas.py`, `tests/integration/api/api_helpers.py`
- Test: `tests/integration/plugins/test_installer.py`, `tests/unit/application/test_install_jobs.py`, `tests/integration/api/test_install_api.py`

**Interfaces:**
- Consumes: `PluginCatalogService.entry/index`, `PluginAdmin.list`, `CatalogEntry`, `read_plugin_json`, `STAGING`.
- Produces:
  - `ports/plugin_catalog.py`: `Progress = Callable[[str, int | None], None]` (phase `"downloading"`/`"installing"`, percent or `None`); `class PluginInstaller(Protocol): def install(self, entry: CatalogEntry, archive_url: str, progress: Progress) -> None: ...` (raises `InstallError` / `ConflictError`).
  - `installer.py`:
    - `extract_plugin(archive: Path, plugin_path: str, dest: Path, max_unpacked: int = 20_000_000) -> None` — the archive has exactly one top folder; copies entries under `<top>/<plugin_path>/` into `dest`, skipping `tests/` and `__pycache__/`. Refuses (raises `InstallError`) any entry name containing `..` segments, a leading `/` or `\`, a backslash, a drive letter (`^[A-Za-z]:`), or a symlink (`external_attr >> 16` is `S_IFLNK`), and stops when the running total of `file_size` exceeds `max_unpacked`. Every target is checked with `resolved.is_relative_to(dest.resolve())`.
    - `class ZipPluginInstaller(target: Path, opener: Callable[..., Any] = urllib.request.urlopen, max_download: int = 50_000_000, read_timeout_s: float = 30.0)`; `install(...)`: refuse with `ConflictError` if `target/<id>` exists; download to `target/.staging/<id>.zip` in 64 KiB chunks reporting `("downloading", pct or None)` from `Content-Length`; over cap → `InstallError`; `progress("installing", None)`; `extract_plugin` into `target/.staging/<id>/`; require `__init__.py` and a `plugin.json` whose id equals `entry.plugin.id`; `os.replace` staged folder to `target/<id>` (if `target/<id>` appeared meanwhile → `ConflictError`); always remove the zip and staged folder in `finally`.
  - `install_plugin.py`:
    - `@dataclass class InstallJob: id: str; plugin_id: str; state: Literal["queued","downloading","installing","done","failed"]; percent: int | None; error: str | None`
    - `class InstallJobs(catalog: PluginCatalogService, installer: PluginInstaller, admin: PluginAdmin, submit: Callable[[Callable[[], None]], None], sdk_version: str, has_package: Callable[[str], bool])` — `start(plugin_id: str) -> InstallJob` (NotFoundError if not in catalog; ConflictError if id in `admin.list()` or a queued/running job has it; `ValidationError(reason)` if `installable` gives a reason), `get(job_id: str) -> InstallJob` (NotFoundError). `submit` runs work on a single worker thread so one install runs at a time (bootstrap passes a `ThreadPoolExecutor(max_workers=1).submit`; tests pass an inline runner). Job ids are `uuid4().hex`.
  - `AppServices.installs: InstallJobs`.
  - API: `POST /plugins/install` body `{"id": str}` → 202 `InstallJobOut {job, plugin_id, state, percent, error}`; `GET /plugins/install/{job}` → `InstallJobOut`. Both above `/plugins/{plugin_id}`.

- [ ] **Step 1: Failing installer tests** `tests/integration/plugins/test_installer.py` (build zips in `tmp_path` with `zipfile`; serve via a fake `opener` returning a file-like with `headers`):
  - `test_install_happy_path` — `target/demo/__init__.py` and `plugin.json` exist; `tests/` and `__pycache__/` were not copied; `.staging` is empty afterwards; progress saw `downloading` with percents ending at 100, then `installing`.
  - `test_extract_refuses_parent_escape` (`top/plugins/demo/../../evil.py`), `test_extract_refuses_absolute` (`/etc/x`), `test_extract_refuses_windows_paths` (`top/plugins/demo/..\\x.py`, `C:/x.py`, `top/plugins/demo/C:x.py`), `test_extract_refuses_symlink`, `test_extract_stops_over_unpacked_cap` (`max_unpacked=10`).
  - `test_install_refuses_wrong_id` (plugin.json id `other`), `test_install_refuses_missing_init`, `test_install_refuses_existing_folder` (pre-made `target/demo/` without plugin.json → `ConflictError`, staging cleaned), `test_download_over_cap_refused` (`max_download=10`), `test_failure_leaves_no_folder` (any failure → `target/demo` absent, `.staging` empty).
- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement `extract_plugin` and `ZipPluginInstaller`.
- [ ] **Step 4: Failing job tests** `tests/unit/application/test_install_jobs.py`: `test_start_unknown_is_not_found`, `test_start_installed_is_conflict`, `test_start_pending_is_conflict`, `test_start_not_installable_is_validation_error`, `test_second_start_same_id_is_conflict` (submit queues without running), `test_job_states_flow_to_done`, `test_job_failure_records_error`.
- [ ] **Step 5:** Implement `InstallJobs`; wire into bootstrap and `api_helpers`.
- [ ] **Step 6: API tests** `test_install_api.py`: `test_install_returns_202_and_job`, `test_install_conflict_409`, `test_install_unknown_404`, `test_job_status`, `test_post_needs_the_header_check` (mirror the existing CSRF/header test for POSTs). Implement routes.
- [ ] **Step 7:** Gates — PASS. **Commit** `feat(plugins): install a plugin from the catalog into the data folder`.

### Task 6: Status dot and solid chip styles

**Files:**
- Create: `src/netview/presentation/web/static/js/dot.js`
- Modify: `src/netview/presentation/web/static/css/app.css`, `themes/daylight.css`, `themes/contrast.css`, `themes/README.md`
- Test: `tests/js/dot.test.mjs`, `tests/integration/test_css_balance.py` (already runs over app.css; keep it passing)

**Interfaces:**
- Produces:
  - `dotHtml(kind: "ok"|"warn"|"bad"|"restart"|"off"|"idle", tip: string, { size = "md", still = false } = {}) -> string` → `<span class="sdot <kind>[ sm][ still]" role="img" aria-label="<tip>" data-tip="<tip>"></span>` (tip escaped with `esc`).
  - CSS classes: `.sdot`, `.sdot.sm`, `.sdot.still`, kinds as above; `.sdot` is a still container (`position: relative; display: inline-block`), the disc is `::before`, the tooltip is `::after` (`content: attr(data-tip)`, shown on `.sdot:hover::after` and on `:focus-visible` / `:focus-within` of an ancestor `.pcard`), never animated. Keyframes `sdot-pulse` (ok), `sdot-fade` (warn), `sdot-flash` (bad, restart). `.sdot.still::before { animation: none }`. Reduced-motion block sets `animation: none` on `.sdot::before`.
  - `.chip.solid`: `display: inline-flex; align-items: center; justify-content: center; height: 20px; padding: 0 12px; font-weight: 700; white-space: nowrap; border: 0; background: var(--chip-bg, var(--border-strong)); color: var(--chip-fg, var(--text));`
  - Theme tokens `--chip-bg` / `--chip-fg` set in `daylight.css` and `contrast.css` so the pair reaches ≥ 4.5:1 (e.g. Daylight `#4d5663` on `#ffffff` text; Contrast `#3a3a3a` with `#ffffff`). README token table gains both as optional.
- [ ] **Step 1: Failing test** `tests/js/dot.test.mjs`: `dot markup has role, label and tip`, `sm and still modifiers`, `tip is escaped` (`<b>` → `&lt;b&gt;`).
- [ ] **Step 2:** `npm test` — FAIL. **Step 3:** Implement `dot.js` and the CSS.
- [ ] **Step 4:** Add a Python test `tests/integration/test_css_tokens.py::test_chip_contrast` computing WCAG contrast for each built-in theme's effective chip pair (token or fallback) ≥ 4.5, and `::test_app_css_has_no_colour_literals` (no `#[0-9a-f]{3,8}\b` or `rgb(` in `app.css`).
- [ ] **Step 5:** Gates — PASS. **Commit** `feat(ui): status dots and solid chips`.

### Task 7: Settings rail — Plugins group, Installed and Available

**Files:**
- Modify: `src/netview/presentation/web/static/js/settings/dialog.js`, `src/netview/presentation/web/static/js/main.js` (only if callers change), `static/css/app.css`
- Create: `src/netview/presentation/web/static/js/settings/gallery.js` (pure helpers start here)
- Test: `tests/js/nav.test.mjs` (update `tabsFor` tests), `tests/js/gallery.test.mjs`

**Interfaces:**
- Consumes: `dotHtml` (Task 6), `needsSetup` (nav.js).
- Produces:
  - `gallery.js`: `pluginStatus(info) -> {kind, tip}` with precedence failed (`bad`, `Failed: <first line>`) → pending or `restart_required` (`restart`, `Awaiting restart`) → not enabled / `disabled` (`off`, `Off`) → `needsSetup` (`warn`, `Needs configuring`) → active (`ok`, `Active`). `attention(list) -> "bad" | "warn" | null` (bad if any failed/pending/restart_required; else warn if any needs setup).
  - `dialog.js`: `tabsFor(plugins, availableCount)` → `[{id:"appearance",label:"Appearance"}, {id:"plugins",label:"Plugins",group:true}, {id:"plugins:installed",label:"Installed",parent:"plugins",count:plugins.length,dot:attention(plugins)}, {id:"plugins:available",label:"Available",parent:"plugins",count:availableCount}]`. `resolveTab(tabId) -> {tab, overlay}`: `"plugins"` → `{tab:"plugins:installed", overlay:null}`; `"plugin:<id>"` → `{tab:"plugins:installed", overlay:"<id>"}`; known ids → themselves; anything else → `{tab:"appearance", overlay:null}`.
  - The group header is a `button` with `aria-expanded`; Enter/Space/click toggle; child tabs are hidden when collapsed; arrow keys skip hidden tabs. Open state key `netview.settings.pluginsOpen` in `localStorage`, read/write wrapped in `try/catch`, default open. Installed shows its count and, when `dot` is set, `dotHtml(dot, dot === "bad" ? "A plugin needs a restart or failed" : "A plugin needs configuring", {size:"sm", still:true})`.
  - `openSettings(tabId)` fetches `/api/v1/plugins` and `/api/v1/plugins/catalog` (catalog failure → count 0), then applies `resolveTab`; the overlay is opened by Task 8's `openPluginOverlay` (until Task 8 lands, `overlay` is ignored).
  - Per-plugin rail entries and their `Failed`/`Set up` badges are removed.
- [ ] **Step 1: Failing tests:** in `nav.test.mjs` replace the old `tabsFor` assertions with `tabsFor groups Installed and Available under Plugins` (ids and parents exact, no `plugin:` ids); `resolveTab maps plugins, plugin:<id> and unknown ids` (covers `plugin:nope` → installed with overlay `"nope"`; overlay of an id not in the list is ignored by Task 8) . In `gallery.test.mjs`: `pluginStatus precedence` (a failed + restart_required plugin is `bad`; pending is `restart`; disabled + needs setup is `off`; `Failed: first line only` from a two-line error) and `attention picks bad over warn`.
- [ ] **Step 2:** `npm test` — FAIL. **Step 3:** Implement. Installed and Available panes render a placeholder until Tasks 8–9.
- [ ] **Step 4:** Gates — PASS. **Commit** `feat(settings): Plugins group with Installed and Available`.

### Task 8: Installed gallery and settings overlay

**Files:**
- Create: `static/js/settings/installed.js`, `static/js/settings/overlay.js`
- Modify: `static/js/settings/gallery.js`, `static/js/settings/plugins-tab.js`, `static/js/settings/dialog.js`, `static/css/app.css`
- Test: `tests/js/gallery.test.mjs`, `tests/js/plugin-ui.test.mjs` (if it covers `renderPlugin`)

**Interfaces:**
- Consumes: `pluginStatus`, `dotHtml`, `CAPABILITY_LABELS`, `renderPlugin(pane, ctx, id)`.
- Produces:
  - `gallery.js`: `sortInstalled(list)` (attention first: bad, restart, warn; then by name, case-insensitive), `matchesFilter(p, text)` (case-insensitive substring of name or description; empty text matches), `sourceText(p)` (`pending` → `Just installed`, `folder` → `Folder`, else `Built in`), `monogram(name)` (first letter, upper case), `installedCardHtml(p)` (button-like `div.pcard[role=button][tabindex=0][data-id]`, monogram tile, name, `version · sourceText`, `dotHtml(kind, tip)` positioned top-right, description, `chip solid` capability chips via `CAPABILITY_LABELS`, footer: on/off switch with `data-enable` (disabled when failed) or `Loads the next time netview starts` when pending). Accessible name of the card includes the status tip.
  - `installed.js`: `renderInstalled(pane, ctx, { overlayId = null } = {})` — heading `Installed plugins`, filter input, grid; click/Enter/Space on a card (not on the switch) calls `openPluginOverlay(ctx, id, cardEl)`; switch toggles via the existing PATCH and redraws that card; keeps scroll position across redraws.
  - `overlay.js`: `openPluginOverlay(ctx, id, returnFocus)` — a `dialog.pov` shown with `showModal()` inside `document.body`; header: monogram, name, version, `dotHtml`, close button; body: `renderPlugin(body, overlayCtx, id)` where `overlayCtx = {...ctx, redraw: () => rerender()}`; pending plugins show their `plugin.json` info and `This plugin loads the next time netview starts. Its settings appear after that.` instead of calling `renderPlugin`. Esc / close / backdrop click close it and return focus to `returnFocus`; on close the gallery redraws.
  - `plugins-tab.js`: every `ctx.select(\`plugin:${id}\`)` becomes `ctx.redraw()`; `renderOverview` is deleted (no callers left).
- [ ] **Step 1: Failing tests** in `gallery.test.mjs`: `sortInstalled puts attention first then by name`, `matchesFilter on name and description`, `installed card shows dot top-right, chips and switch`, `pending card has no switch and says it loads next start`, `failed card switch is disabled`, `card markup escapes names`. Add `renderPlugin redraws through ctx.redraw` if `plugin-ui.test.mjs` can drive it with a fake pane; otherwise assert by source check that `plugins-tab.js` no longer contains `ctx.select(`.
- [ ] **Step 2:** `npm test` — FAIL. **Step 3:** Implement; hook `resolveTab`'s `overlay` (open it after the Installed pane renders, ignored when the id is not in the list).
- [ ] **Step 4:** Gates — PASS. **Commit** `feat(settings): Installed gallery with plugin settings overlay`.

### Task 9: Available gallery and install progress

**Files:**
- Create: `static/js/settings/available.js`
- Modify: `static/js/settings/gallery.js`, `static/css/app.css`
- Test: `tests/js/gallery.test.mjs`

**Interfaces:**
- Consumes: `GET /api/v1/plugins/catalog`, `POST /api/v1/plugins/catalog/refresh`, `POST /api/v1/plugins/install`, `GET /api/v1/plugins/install/{job}` (Tasks 4, 5), `toast`, `apiGet`, `apiSend`.
- Produces:
  - `gallery.js`: `catalogLine(cat, now)` → `From github.com/Cadtastic/NetView · checked <age>` when no error, else `<error> · showing the list from <date>` (or the error alone when never fetched); `<age>` like `4 min ago`, `just now`, `2 h ago`; source `bundled` with no fetch → `Built-in list`. `availableFooter(entry, job)` → html: progress (`Downloading… N%` with a determinate bar, indeterminate when `percent` is null; `Installing…`; `Queued`), the job error in `.err` plus an enabled Install, or a disabled Install with `reason`, or an enabled Install. `availableCardHtml(entry, job)` (monogram, name, `version · by <author>`, description, `chip solid` chips, footer). `emptyAvailableText(cat)` → `Every available plugin is installed.` when cat has an index and nothing left; `No plugins found.` when the index is empty; `Couldn't reach GitHub. Check the connection and press Refresh.` when error and no index.
  - `available.js`: `renderAvailable(pane, ctx)` — heading, catalog line, filter, Refresh; renders from `GET catalog` at once and, when `stale`, POSTs refresh in the background and re-renders; Install POSTs, then polls the job every 300 ms; one job polled at a time, further Install clicks show `Queued` (the server queues them); on `done` remove the card, toast `<name> installed. Restart netview to load it.`, refresh the plugin list in the dialog (Installed count and attention dot update); on `failed` show the error and re-enable Install. Polling stops when the dialog closes.
- [ ] **Step 1: Failing tests** in `gallery.test.mjs`: `catalogLine fresh, stale-with-error and bundled`, `availableFooter for each job state and for a reason`, `empty states`, `available card escapes author and description`.
- [ ] **Step 2:** `npm test` — FAIL. **Step 3:** Implement.
- [ ] **Step 4:** Gates — PASS. **Commit** `feat(settings): Available gallery with install progress`.

### Task 10: Dots elsewhere in the core app

**Files:**
- Modify: `static/js/cards/watches.js`, `static/js/nav.js`, `static/js/pages/devices.js`, `static/css/app.css`
- Test: `tests/js/cards.test.mjs`, `tests/js/nav.test.mjs`

**Interfaces:**
- Consumes: `dotHtml`.
- Produces:
  - `watches.js`: `statusChip(state)` returns `dotHtml(kind, label)` (16 px, animated) with `up→ok`, `degraded|present→warn`, `down|absent→bad`, `pending→off`; labels unchanged (`Up`, `Partly up`, `On the network only`, `Not on the network`, `No reply`, `Checking`). The dot sits at the top right of `.watch .wh`.
  - `nav.js`: a disabled (needs-setup) item appends `dotHtml("warn", "Needs configuring", {size:"sm"})` after its label; title unchanged.
  - `devices.js` Status cell: `dotHtml(kind, text, {size:"sm", still:true})` + the text; `online→ok`, `quiet→warn`, `offline→bad`, else `idle`. `.dot-s` CSS is removed if nothing else uses it (grep core JS first; external plugins are not changed — if a plugin uses `.dot-s`, keep the rule).
- [ ] **Step 1: Failing tests:** replace `status chips carry an icon and the plan labels` with `status dots carry the plan labels and kinds` (each state's `aria-label` equals its label and class has the mapped kind); add `needs-setup nav item carries an amber dot`; add `device status cell has a still small dot and the word` (via `CORE_COLUMNS` status `td`).
- [ ] **Step 2:** `npm test` — FAIL. **Step 3:** Implement.
- [ ] **Step 4:** Gates — PASS. **Commit** `feat(ui): status dots on watches, nav and the devices table`.

### Task 11: Fake GitHub, docs, deferred items, browser pass

**Files:**
- Create: `scripts/serve_fake_plugin_repo.py`
- Modify: `docs/superpowers/deferred.md`, `README.md`, the spec (one line: `generated` field dropped from the index, per Task 2)
- No new tests beyond the script's `--help` smoke check.

**Interfaces:**
- `serve_fake_plugin_repo.py` (docstring, `--help`, stdlib, `sys.dont_write_bytecode = True`): args `--plugins-dir` (default `plugins`), `--port` (default `8799`), `--execute` (without it, print what it would serve and exit). Builds in a temp dir `NetView-main/plugins/<id>/…` zipped as `netview.zip`, writes `plugins/index.json` via `build_index(..., archive_url=f"http://127.0.0.1:{port}/netview.zip")`, serves that temp dir with `http.server` on 127.0.0.1 until Ctrl+C, and prints the catalog URL to pass as `NETVIEW_PLUGIN_CATALOG_URL`.

- [ ] **Step 1:** Write the script; `uv run python scripts/serve_fake_plugin_repo.py --help` exits 0.
- [ ] **Step 2:** `deferred.md`: new section "From the plugin gallery (2026-11-11)" with uninstall, update-available, plugin icons, restart button, pin the catalog ref to a release tag, the real-GitHub install check after merge+push. README: how to list a plugin (add `plugin.json`, run `scripts/build_plugin_index.py --execute`, commit both).
- [ ] **Step 3: Browser pass** (the orchestrating agent does this itself, not a mechanical gate): start the fake repo (`--execute`), then a netview from this worktree with a throwaway data dir under the session scratchpad, **no** `--plugin-dir`, `NETVIEW_PLUGIN_CATALOG_URL` pointing at the fake, on a free port (add a `netview-gallery` entry to `R:\source\claude projects\HomeLab\.claude\launch.json`). Check, with screenshots: rail group collapse/expand and keyboard; Installed cards (dots, tooltips solid during fade/flash, normal cursor, chips), overlay open/save/toggle/Esc/focus return; Available lists gsm7248 and starlink; install one → progress → card moves to Installed with flashing red dot; restart the server → plugin loads (Needs configuring amber, or Active); refresh-error line when the fake is stopped; all four themes; reduced motion (emulate) stops every dot; Watches card, nav needs-setup dot, Devices table. Never point anything at the real `netview-dev` data dir.
- [ ] **Step 4:** Fix what the pass finds (each fix gated and committed). **Commit** `docs(plugin-gallery): fake repo script, deferred items, authoring note`.

---

## Execution notes

- Order: 1 → 11 in sequence. Tasks 1–5 are server side and 6–10 UI; Task 7 onward needs the endpoints from Tasks 4–5. Run sequentially so each review sees a stable base.
- After the user merges and pushes: one real install from `github.com/Cadtastic/NetView` `main` into a throwaway data dir (listed in `deferred.md` until done).
