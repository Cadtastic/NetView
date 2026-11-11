# NetView UI: settings dialog, themes and visual design (plan 1b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Plugins page with a Settings dialog (Appearance, Plugins overview, one tab per plugin), add a folder-driven theme system with four built-in themes, and restyle the whole shell to the §13.3 design.

**Architecture:**
- **Themes** are CSS files that only set the token contract. `app.css` holds all component styling and reads only tokens.
- **Theme listing:** the server lists themes from the built-in folder and the user folder `<data_dir>/themes/` through `GET /api/v1/themes`.
- **Settings dialog:** a JS module that reuses the existing `PluginAdmin` API and the `settings.section` slot.

**Tech stack:** as in plan 1. The UI is plain ES modules with no build step and no inline scripts (CSP).

**Spec:** `docs/superpowers/specs/2026-11-10-netview-design.md`, especially §13. The base plan is `2026-11-10-netview-core.md`; its Global Constraints still apply.

## Global constraints (in addition to plan 1)

- **Theme files:**
  - The id is the file stem and must match `^[a-z0-9][a-z0-9-]{0,40}$`; user theme ids get the prefix `user-`.
  - The header is the first comment: `/* netview-theme name="…" scheme="light|dark" preview="#rrggbb,#rrggbb,#rrggbb" */`.
- **Token contract** (every theme defines all of them on `:root`, plus `color-scheme`):
  - Surfaces and borders: `--bg`, `--surface`, `--surface-2`, `--surface-hover`, `--border`, `--border-strong`.
  - Text: `--text`, `--text-muted`, `--text-faint`.
  - Accent and focus: `--accent`, `--accent-contrast`, `--focus`.
  - Status: `--ok`, `--warn`, `--bad`, `--idle`.
  - Series: `--series-1`, `--series-2`, `--series-3`, `--series-4`.
  - Shape: `--shadow`, `--radius-s`, `--radius-m`.
- **Built-in themes:** `daylight` (light, default light), `graphite` (dark, default dark), `harbor` (dark), `contrast` (dark, high contrast).
- **Theme choice:**
  - `localStorage` key `netview-theme`: `"system"` (default) or a theme id. Always wrapped in `try/catch`.
  - "Match system" uses two `<link>` tags with `media="(prefers-color-scheme: light|dark)"` that point at daylight and graphite.
  - An explicit choice uses `<link id="theme">` without `media`.
- **Fonts:**
  - Text: `"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif`.
  - Addresses: `"Cascadia Mono", Consolas, ui-monospace, monospace`.
  - `font-variant-numeric: tabular-nums` in tables and tiles.
- **Copy:** sentence case, no all-caps labels, no middle-dot meta strings. The save button reads "Save settings", and the confirmation reads "Settings saved".
- **Accessibility:**
  - Visible `:focus-visible` ring using `--focus`.
  - The dialog is a real `<dialog>` opened with `showModal()`. Escape closes it and focus returns to the gear.
  - Tab rail has `role="tablist"` with arrow-key navigation.
  - Motion respects `prefers-reduced-motion`.
  - Layout works at 360 px wide.
- **Escaping:** every server or user string goes through `esc()` or `textContent`. Plugin-provided HTML is only allowed from `render()` callbacks, as before.

---

### Task R1: Sweep and scan correctness (review C1, I3, I4, I7, M11 server side, M13–M16, M18)

The item ids refer to `.superpowers/sdd/2026-11-10-netview-core/final-review.md`, which has the file:line references. Read it.

**Files:** `bootstrap.py`, `application/usecases/{sightings,scan}.py`, `application/queries/{state,read_models}.py` (and `_display.py`), `infrastructure/db/{engine,repositories,uow}.py`, `infrastructure/lanmon_import.py`, `plugins/builtin/lan_discovery/plugin.py`, the API devices router, and their tests.

**Requirements:**
- **C1, network changes:**
  - When `settings.subnet` is unset, the subnet callable re-derives `f"{local_ip}/24"` on every call, and `HostInfo` re-reads `local_ip` and the gateway every time, cached for at most 30 s.
  - If `local_ip` is loopback (127/8), link-local (169.254/16) or unspecified, `RunScan` raises `NoNetworkError(NetviewError)` before calling any provider. It records nothing and marks nothing offline.
  - The API maps `NoNetworkError` to 503 `{"error": "no network: this device has no LAN address"}`. The scheduled job logs it at most once per state change.
  - **Test:** a fake whose `local_ip` is `127.0.0.1` and which answers every ping. The scan raises `NoNetworkError`, and the repository stays empty.
- **C1, forget a device:**
  - New command `ForgetDevice(uow, bus, clock)`, called as `__call__(key) -> None`. It deletes the device, its claims, types and hints, and **keeps** its nickname and nickname history, so a returning device gets its nickname back.
  - It emits a new event kind, `EventKind.FORGOTTEN = "forgotten"`.
  - API: `DELETE /api/v1/devices/{key}` returns 204, and 404 when unknown.
  - It is not on `CoreFacade`.
- **I3:** `discover()` keeps only ARP IPs inside `subnet`. Fix `test_lan_discovery.py` so `.74` is inside the /29 (use `.4`), and add an outside entry (`172.21.0.5`) that must be excluded.
- **I4:** a conflict is only when the previous owner of the IP is a *different* key whose status is online or quiet. Emit it once per ownership change. **Test:** two sweeps with the same conflicting state give exactly one CONFLICT event.
- **I7, scans one at a time:**
  - `RunScan` holds a `threading.Lock` acquired non-blocking. If it's busy, it raises `ScanInProgressError(NetviewError)`, and the API returns 409 `{"error": "scan already running"}`.
  - The scheduled job skips silently when busy.
- **I7, SQLite isolation:** apply SQLAlchemy's documented pysqlite fix in `make_engine`: `isolation_level=None` on connect, and `BEGIN` emitted from a `begin` event, so transactions start at session begin. **Test:** two threads record the same new device concurrently; no IntegrityError, and exactly one NEW event.
- **M11:** `DeviceView.vendor` is computed at read time through an injected `VendorLookup` whenever the stored vendor is empty.
- **M13:** `is_new` is cleared for all devices at startup (bootstrap calls a repository `clear_new()`).
- **M14:** "is back" (ONLINE) events are gated by the first-sweep flag. The flag flips only on a *complete* sweep.
- **M15:** merging keeps `min(first_seen)`. If the MAC key already has a nickname and the IP key has a different one, append a `NicknameChange(key=mac, old=mac_nick, new=mac_nick, by="merge: dropped ip-key nickname '<ip nick>'")`. That is a history row only; the value is unchanged.
- **M16:** the import skips a name claim when a claim from the same source already exists for that key.
- **M18:** `GetNetworkState` and `_display` load claims, nicknames and watches once per call (bulk repository methods `all_claims()`, `all()`, `list()`), not per device.

Steps: write the failing tests for each bullet, run them and see them fail, implement, then run `uv run pytest -q`, `uv run ruff check .`, `uv run lint-imports` and mypy on domain, application and sdk until everything passes. Commit.

### Task R2: Plugin host, events, infrastructure hardening (review I5 server side, I8, I9, M12, M17, M19–M21, the validation move)

**Files:** `infrastructure/{event_bus,scheduler}.py`, `infrastructure/plugins/{host,context,validation}.py`, moving validation to `application/plugins/validation.py`; `infrastructure/net/{common,windows,linux,tools}.py`; `infrastructure/db/engine.py` (authorizer); `presentation/api/routers/{stream,scan}.py` and `schemas.py`; `presentation/cli.py`; `pyproject.toml`; `sdk/__init__.py`; and tests.

**Requirements:**
- **I5, the `state` frame:**
  - After every scheduled job run (success or failure) and every `POST /scan`, the server publishes a lightweight "state changed" signal.
  - `/api/v1/stream` sends it as `event: state` with `data: {"t_ms": <now>}`.
  - Signals are coalesced to at most one per second per stream.
  - Add an `on_job_finished` hook to the scheduler (owner, name, ok) that bootstrap wires to that signal. The application layer gets a small `StateNotifier` port.
  - **Test:** the stream receives `event: state` after a job runs.
- **I8:** `update_settings` also replaces `record.ctx.settings`. **Test:** after a PATCH, `ctx.settings.level` is the new value.
- **I9, isolate plugin handlers and setup:**
  - Handlers subscribed through a plugin context run on a per-plugin single-thread worker queue (maxsize 1000, drop oldest, log). Core subscribers stay synchronous.
  - `setup()` runs with a 10 s timeout in a worker thread; on timeout the plugin is marked failed with "setup timed out after 10 s".
  - **Tests:** a handler sleeping 5 s does not delay `publish()` by more than 100 ms; a setup that sleeps 30 s gives a failed state within about 11 s (use a 0.2 s timeout override in the test).
- **M12:** `dns_query` uses an overall deadline from `time.monotonic()`, `sock.connect((server, 53))`, and the remaining time as the timeout on each `recv`. **Test:** a local UDP server that sends 50 junk datagrams and never answers; the call returns `None` within `timeout_s + 0.3`.
- **M17:** `update_settings` merges the PATCH values over the current settings before validating. **Test:** patch one field and the other is kept.
- **M19, argument hardening:**
  - Every `NetworkTools` method validates IPv4 with `ipaddress.IPv4Address`. Invalid input gives `None` / `{}` and never runs a subprocess.
  - On Windows, run `os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")`, and the same for `ARP.EXE` and `ROUTE.EXE`.
  - `InspectionIn.ip` and `/devices/{ip}/probe` validate IPv4 (422).
- **M20, plugin write fence:**
  - Plugin unit-of-work connections install `sqlite3.Connection.set_authorizer`, which denies `SQLITE_INSERT`, `SQLITE_UPDATE` and `SQLITE_DELETE` on tables not starting with `<plugin_id>_` (allow `sqlite_*` and `alembic_version_<id>`).
  - Do it through a dedicated engine or connection pool per plugin so the core connections are unaffected.
  - **Test:** a plugin session INSERT into `nicknames` raises; an INSERT into `<id>_items` works.
- **M21:**
  - `netview serve` gains `--subnet`, `--interval` and `--fast`, mapping to the settings `subnet`, `scan_interval_s` and `fast_interval_s`.
  - uvicorn is run with `timeout_graceful_shutdown=3`.
  - `SDK_VERSION` moves to `netview.application.plugins.manifest`, and `netview.sdk` re-exports it.
- **Validation move:** `infrastructure/plugins/validation.py` moves to `application/plugins/validation.py`. Update the imports and remove the `ignore_imports` entry for `sdk.testing` from `pyproject.toml`; import-linter must still report 0 broken.

Steps: tests first, run them and see them fail, implement, then the full checks as in R1. Commit.

---

### Task U1: Theme listing API and user theme folder

**Files:**
- Create:
  - `src/netview/application/ports/themes.py`: `ThemeInfo` dataclass `(id: str, name: str, scheme: str, preview: list[str], source: Literal["built-in", "user"], url: str, error: str | None)` and the `ThemeCatalog` Protocol (`list() -> list[ThemeInfo]`, `user_dir() -> str`)
  - `src/netview/infrastructure/themes.py`: `FolderThemeCatalog(builtin_dir: Path, user_dir: Path)` and `parse_theme_header(text: str) -> tuple[str, str, list[str]]`, which raises `ValueError` with a reason
  - `src/netview/presentation/api/routers/themes.py`
- Modify:
  - `src/netview/application/services.py`: add `themes: ThemeCatalog` to `AppServices`
  - `src/netview/bootstrap.py`: build the catalog with `user_dir = settings.data_dir / "themes"` and create that folder
  - `src/netview/presentation/api/app.py`: mount the user folder at `/themes/user` with `StaticFiles(check_dir=False)`, and include the themes router
- Test: `tests/unit/infrastructure/test_themes.py`, `tests/integration/api/test_themes_api.py`

**Interfaces (produces):**
- `GET /api/v1/themes` → `{"themes": [ThemeInfo…], "user_dir": str}`.
  - Ordering: built-in themes in the order daylight, graphite, harbor, contrast, then any other built-ins alphabetically, then user themes alphabetically.
  - Each `url` is `/static/themes/<stem>.css` or `/themes/user/<stem>.css`.
- **Header parsing:** only the first 1024 bytes are read.
  - Bad or missing header: the theme is listed with its `error` and `name` set to the stem.
  - Bad stem: the file is skipped entirely.
  - Files that are not `.css`: ignored.
  - The folder is read on every request (no caching), so dropping in a file shows up without a restart.

- [ ] **Step 1: Write the failing tests**
  - `parse_theme_header('/* netview-theme name="Harbor" scheme="dark" preview="#0f1e2a,#142838,#6fd1c4" */')` returns `("Harbor", "dark", ["#0f1e2a", "#142838", "#6fd1c4"])`.
  - `scheme="blue"` raises `ValueError`.
  - A missing header raises `ValueError`.
  - A preview that isn't three `#rrggbb` values raises `ValueError`.
  - The catalog lists built-ins first, in the fixed order; a user file `mine.css` gets id `user-mine` and source `user`; `Bad Name.css` is skipped; a user file with no header is listed with an `error`.
  - API: `GET /api/v1/themes` → 200 with `user_dir`. A user theme file is served at `/themes/user/mine.css` with `text/css`. `/themes/user/../netview.db` is 404 (no path traversal).

- [ ] **Step 2: Run the tests and check they fail**

  Run `uv run pytest tests/unit/infrastructure/test_themes.py tests/integration/api/test_themes_api.py -q`.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest -q
  ```
  ```bash
  uv run ruff check .
  ```
  ```bash
  uv run lint-imports
  ```
  ```bash
  uv run mypy src/netview/domain src/netview/application src/netview/sdk
  ```

- [ ] **Step 5: Commit**

---

### Task U2: Theme files, token contract and the restyled `app.css`

**Files:**
- Create: `src/netview/presentation/web/static/themes/{daylight,graphite,harbor,contrast}.css` and `themes/README.md`
- Replace: `src/netview/presentation/web/static/css/app.css`
- Modify: `index.html` (theme links)

**Values to use** (the base palettes; derive the remaining tokens, keeping contrast at or above the stated floor):

| Theme | `--bg` | `--surface` | `--surface-2` | `--border` | `--text` | `--text-muted` | `--accent` | Text contrast floor |
|---|---|---|---|---|---|---|---|---|
| daylight | `#f4f6f9` | `#ffffff` | `#eef1f5` | `#d8dee6` | `#1c2430` | `#566273` | `#0b7285` | 4.5:1 |
| graphite | `#1b1f24` | `#22272e` | `#2a3038` | `#363d47` | `#e4e8ec` | `#9aa4b0` | `#4fb3c8` | 4.5:1 |
| harbor | `#0f1e2a` | `#142838` | `#1a3246` | `#244056` | `#dde8f0` | `#8fa8bc` | `#6fd1c4` | 4.5:1 |
| contrast | `#000000` | `#0a0a0a` | `#141414` | `#8a8a8a` | `#ffffff` | `#d0d0d0` | `#66b3ff` | 7:1 |

- **Status colours:** online `--ok` green, quiet `--warn` amber, offline `--bad` muted red, unknown `--idle` grey. Each must be distinguishable from the theme's accent.
- **Series colours:** pick four per theme and validate them with the dataviz validator against that theme's `--surface`. Every theme must PASS in the matching mode:
  ```bash
  node "C:/Users/ADDAMB~1/AppData/Local/Temp/claude/bundled-skills/2.1.321/28d25edf7ae99b29468fdd1a6a2c6bcd/dataviz/scripts/validate_palette.js" "<s1>,<s2>,<s3>,<s4>" --mode <light|dark>
  ```
  Record each run's output in the task report. If the validator needs a surface flag, check its `--help` and pass the theme's `--surface`.
- **`themes/README.md`:** the header format, the full token list with one line on what each token colours, the user folder location (`<data_dir>/themes`), and "copy graphite.css and edit it" as the starting point.
- **`app.css`:** implements §13.3 using tokens only (no hex literals outside the theme files; check with `grep -E "#[0-9a-fA-F]{3,6}" css/app.css`, which must return nothing). It covers:
  - the top bar, nav tabs (an underline on the active tab), and buttons (primary, quiet, icon);
  - inputs, selects, the segmented control and switches;
  - tiles;
  - the table: sticky header, 36 px rows, hover, monospace for `.addr` cells;
  - chips and status dots;
  - the dialog: rail and pane, a 880 × 600 maximum, full-screen under 640 px;
  - toast;
  - focus ring;
  - the live-ring keyframe (one ring per `.live.pulse` class toggle, none under reduced motion).
- **CSS brace-balance test (review I2):** add `tests/integration/test_css_balance.py`, which strips comments and strings from `app.css` and every theme file and asserts that `{` and `}` counts match, with depth never negative.
- **`index.html`:** two `<link rel="stylesheet" media="(prefers-color-scheme: light)">` and `media="(prefers-color-scheme: dark)"` tags for daylight and graphite (ids `theme-light` and `theme-dark`), plus `app.css`.

- [ ] **Step 1: Write the four theme files and run the validator for each**

- [ ] **Step 2: Write `themes/README.md`**

- [ ] **Step 3: Replace `app.css`**

  Run the token-only grep check above; expect no output.

- [ ] **Step 4: Update `index.html`**

- [ ] **Step 5: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest -q
  ```
  ```bash
  npm test
  ```
  Then commit.

---

### Task U3: Settings dialog, theme picker and top bar

**Files:**
- Create:
  - `src/netview/presentation/web/static/js/settings/dialog.js`
  - `js/settings/appearance.js`, `js/settings/plugins-tab.js`
  - `js/settings/schema-form.js` (pure)
  - `js/theme.js` (pure plus DOM apply)
  - `js/icons.js`: inline SVG strings for gear, close, check, alert, live
- Modify: `js/main.js` (top bar, nav; remove the Plugins page; route `#/plugins` → open settings on the Plugins tab), `index.html`
- Delete: `js/pages/plugins.js`, moving its logic into `settings/`
- Test: `tests/js/schema-form.test.mjs`, `tests/js/theme.test.mjs`

**Interfaces (produces):**
- **`schema-form.js`:**
  - `fieldsFromSchema(schema) -> Field[]`, where `Field = {name, label, kind: 'integer'|'number'|'string'|'boolean'|'enum'|'string-list', help, min, max, options, default}`.
  - The label comes from `title`, or else the property name turned into sentence case (`ping_timeout_ms` → "Ping timeout (ms)": a trailing `_ms`/`_s` becomes a unit in brackets).
  - `collectValues(fields, formData) -> object`, which converts numbers and booleans.
- **`theme.js`:**
  - `resolveTheme(pref, themes) -> {mode: 'system'} | {mode: 'fixed', theme}`. An unknown id falls back to system.
  - `applyTheme(resolved, doc)`.
  - `loadThemePref()` / `saveThemePref(id)`.
- **`dialog.js`:** `openSettings(tabId = 'appearance')`. The tabs are:
  - `appearance`
  - `plugins`
  - `plugin:<id>` for every plugin, including failed ones
- **Plain-language capability labels:**
  - discovery → "Finds devices"
  - identity → "Names devices"
  - health → "Checks reachability"
  - traffic → "Measures traffic"
  - destinations → "Sees destinations"
  - inspection → "Inspects devices"
  - local_host → "Reads this device"
  - api → "Adds API endpoints"
  - web_ui → "Adds to the web page"
  - storage → "Keeps its own data"
  - jobs → "Runs in the background"
- **Plain-language permission labels:**
  - devices:read → "Read devices"
  - names:write → "Suggest device names"
  - types:write → "Suggest device types"
  - traffic:write → "Record traffic"
  - storage:own → "Its own tables"
  - api → "API endpoints"
  - ui → "Web page additions"
  - network:probe → "Probe the network"
- **Appearance tab:**
  - A radio grid of theme cards. Each card shows three preview swatches and the name, with "Match system" first.
  - Broken themes are shown disabled with their error.
  - A help line gives the user theme folder path from the API, and says to start from `graphite.css`.
- **Plugin tab:**
  - **Header:** name, version, state badge, and an on/off switch. Toggling it PATCHes `enabled`, and a `restart_required` response shows "Restart NetView to apply".
  - **Body:** description; the capabilities and permissions chip groups under the headings "What it can do" and "Access it asks for"; the form; **Save settings** (PATCH, then toast "Settings saved", or the 422 message inline beside the form); then the `settings.section` slot specs for that plugin, rendered with `spec.render(el, {pluginId, apiBase, apiGet, apiSend, util})`.
- **Form field ids (review M21):** every input id is prefixed with the plugin id (`f-<pluginId>-<name>`), so ids never collide.
- **Top bar:**
  - The gear button has `aria-label="Settings"`.
  - The live dot gets class `pulse`, re-triggered on each stream event or poll result.

- [ ] **Step 1: Write the failing JS tests**
  - **`fieldsFromSchema`** on the `LanDiscoverySettings` JSON schema (copy it from `uv run python -c "from netview.plugins.builtin.lan_discovery.settings import LanDiscoverySettings as S; import json; print(json.dumps(S.model_json_schema()))"`) yields:
    - `[{name: 'ping_timeout_ms', label: 'Ping timeout (ms)', kind: 'integer', min: 100, max: 5000, default: 800}, {name: 'workers', label: 'Workers', kind: 'integer', min: 1, max: 256, default: 64}]`
  - **`collectValues`** converts `"900"` to `900`.
  - **`resolveTheme`:**
    - `resolveTheme('graphite', list)` → fixed graphite.
    - `resolveTheme('nope', list)` → system.
    - `resolveTheme('system', list)` → system.
    - A broken theme id → system.

- [ ] **Step 2: Run the tests and check they fail**

  Run `npm test`.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  npm test
  ```
  ```bash
  uv run pytest -q
  ```
  Then commit.

---

### Task U4: Restyle Dashboard and Devices; fix the UI findings

**Files:**
- Modify: `js/pages/dashboard.js`, `js/pages/devices.js`, `src/netview/plugins/builtin/lan_discovery/static/ui.js`, `src/netview/plugins/builtin/lan_discovery/plugin.py` and `routes.py` if needed

**Requirements:**
- **Devices toolbar:** one wrapping row, as described in §13.3. The device count moves into the toolbar on the right as separate stat chips ("14 online", "6 quiet", "2 offline"), not a middle-dot string.
- **Devices table:** sits on the page surface with a sticky header. IP and MAC use `.addr`. Status is a dot plus a label. An empty vendor renders blank, not "unknown".
- **Dashboard:**
  - The core sweep tile becomes "Last sweep" (time ago).
  - The lan_discovery tile becomes "Sweep coverage" ("<replied> of <hosts> answered" and "took <s> s").
  - The plugin tile re-renders on every state update. It reads the plugin's `/summary`, which must reflect the scheduled core scan, because the scheduled scan calls the same provider instance. If it doesn't, fix the provider so it records its summary on every `discover()`.
- **Nav:** the visual style of the nav tabs comes from U2's CSS. This task only makes sure the markup uses the classes U2 defines.
- **Scan now (review I6):**
  - A primary "Scan now" button sits in the top bar, left of the live indicator. It POSTs `/api/v1/scan`.
  - While a scan is running it is disabled with the label "Scanning…".
  - It is disabled with the tooltip "No discovery plugin is turned on" when `state.capabilities` lacks `discovery`.
  - A 409 "scan already running" or a 503 "no network" is shown as a toast.
- **Live refresh (review I5):**
  - The client refetches `/api/v1/state` on `event: state` as well as `event: domain`.
  - Slots get `ui.requestRender()`. lan_discovery's tile calls it when its fetch resolves, so it never shows the previous value.
  - The core "Last sweep" tile uses the scan job's finish time, not `last_run_ms` (the start). If `JobStatus` lacks a finish time, add `last_finished_ms` to it in this task.
- **Forget device (review C1):** the row's Actions column gets "Forget". It asks for confirmation ("Forget <name>? Its nickname is kept and comes back if the device returns."), then sends `DELETE /api/v1/devices/{key}`.
- **Escaping:** a nickname of `Café <b>` renders literally in the table. Add or extend a JS unit test where the pure render helper allows it.

- [ ] **Step 1: Implement**

- [ ] **Step 2: Run the checks and confirm they pass**

  Run:
  ```bash
  npm test
  ```
  ```bash
  uv run pytest -q
  ```
  ```bash
  uv run ruff check .
  ```
  ```bash
  uv run lint-imports
  ```
  Then commit.

- [ ] **Step 3: Leave the screenshots to the controller**

  The controller takes screenshots in all four themes, at 1280 px and 375 px, after this task.
