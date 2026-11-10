# netview: design

*2026-11-10. Status: draft for approval. Reviewed once by a builder; the answers to its questions are marked "my call, after review".*

## 1. Intent

netview turns the single-file LAN monitor (`R:\source\scripts\network-tools\scripts\lan_monitor.py` plus `templates\lan_dashboard.html`) into a proper Python web application. Over time it becomes a "god's eye view" of the home network: which devices exist, what they are, how healthy they are, how much they send and receive, and, once OPNsense is the router, who they talk to.

The first release adds **no new monitoring features**. Its job is to put today's features on a foundation that can grow:

- **Clean Architecture**: the domain sits in the middle, and dependencies point inward only.
- **SOLID**: small, single-purpose interfaces; new behaviour arrives by adding plugins, not by editing the core.
- **Common Python patterns and tooling**: `src/` layout, `pyproject.toml`, type hints, Protocols and ABCs, pytest, ruff, mypy.
- **A plugin interface** through which a plugin can add data sources, database tables, API endpoints and pieces of the web UI.

## 2. Goals, non-goals, anti-goals

**Goals (first release)**

1. Feature parity with today's monitor (section 10), running on this Windows laptop.
2. Every existing feature reimplemented as a **built-in plugin** on the same plugin interface a later plugin would use, so the interface is proven from day one.
3. A plugin can:
   - implement one or more capability interfaces (section 6);
   - define and migrate its own database tables;
   - add API endpoints;
   - add UI: dashboard tiles, device-table columns, report-dialog sections, whole pages;
   - declare settings and be switched on or off.
4. The user's nicknames and their history are carried over from `HomeLab/network/lan_store.json` exactly, and the old file is left untouched.
5. Architecture rules are enforced by tests, not just by convention.

**Non-goals (later, but the design leaves room)**

- The OPNsense plugin (DHCP leases, ARP, Unbound DNS logs and flows read through OPNsense's REST API with a read-only key). It comes next, after cutover.
- Plugin sandboxing and third-party plugins. Plugins are the user's own and trusted for now (section 7.7).
- Authentication, multiple users, exposing the app beyond localhost.
- Long-term time-series history (weeks of latency or traffic). The first release keeps recent samples in memory like today; the storage port allows a persistent version later (section 8.3).
- Running as a Windows service or on an always-on VM, and packaging as an OPNsense package. The app stays off the router by decision (section 3).

**Anti-goals (it fails if it does these, even if it "works")**

- Overwriting or inventing the user's nicknames. Only the user sets a nickname, through the UI or API, and no plugin can.
- A core that has to be edited to add a data source or a UI panel.
- Plugins reaching into core tables or other plugins' tables directly.
- One plugin's crash or hang taking down the app or the other plugins.
- Writing to network devices. Every probe stays read-only, as today (the Starlink call is a read-only gRPC request).

## 3. Decided by the user

- Clean Architecture and SOLID, with standard Python patterns.
- Plugin interfaces organised around the domain (what a plugin provides: discovery, identity, traffic and so on).
- Plugins can save data to the database in their own tables.
- Plugins are trusted for now; sandboxing comes later.
- Runs on this laptop for now.
- Future OPNsense integration is a netview plugin that reads OPNsense's REST API. netview does **not** run on the router.
- The project is a new git repository at `R:\source\claude projects\HomeLab\netview`, with "netview" as a working name.
- `lan_monitor.py` stays in the scripts library unchanged.

## 4. Constraints

- **Platform:** Windows 11 now. Operating-system commands (ping, ARP table, netstat, `netsh wlan`, interface byte counters) go behind interfaces with per-platform adapters.
  - **Windows:** adapters are built and tested in the first release.
  - **Linux:** *(my call, after review)* the first release ports only the Linux code paths the old monitor already has (ping flags, `/proc/net/dev` counters, ARP/neighbour table, the netstat own-process filter). They are tested with recorded sample output, not on a real Linux machine. No new Linux-only work in the first release; Wi-Fi details on Linux may show "not available". Full Linux support comes with the move to an always-on VM.
  - **FreeBSD:** stays possible by design, with nothing built for it.
- **Python:** 3.11 or newer *(my call: OPNsense ships 3.11, and the laptop has 3.14)*.
- **Privileges:** runs as a normal user with no raw sockets, as today (ping via the system `ping` command, everything else over ordinary sockets).
- **Network safety:** bind to `127.0.0.1` by default. Keep today's protections for state-changing requests: a custom request header, a Host check, and a strict Content Security Policy.
- **Privacy:** no telemetry or outside calls except the probes the user turned on (internet ping target, DNS timing).
- **Dependencies:** third-party packages are fine (this is not a library script) but kept to well-known, maintained ones.

## 5. Architecture

### 5.1 Layers and the dependency rule

```
presentation  ──►  application  ──►  domain
      │                 ▲
      ▼                 │
infrastructure ─────────┘   (implements application ports)

plugins ──► netview.sdk (public facade over domain + application contracts)
```

| Package | Contains | May import |
|---|---|---|
| `netview.domain` | Entities, value objects, domain services (name ranking, nickname protection), domain events. Pure Python, no I/O. | stdlib only |
| `netview.application` | Use cases (commands and queries), **ports** (repository, unit of work, clock, event bus, network tools, metrics store), the plugin capability contracts, the scheduler contract. | domain |
| `netview.infrastructure` | SQLAlchemy models and repositories, unit of work, Alembic migrations, OS adapters per platform, OUI lookup, plugin loader, scheduler, event bus, metrics store. | application, domain, third-party |
| `netview.presentation` | FastAPI app, routers, request/response schemas, live-update stream, static web UI, CLI. | application, domain (read-only types) |
| `netview.sdk` | The **only** package plugins import: re-exports the capability contracts, the plugin base class, the context type, domain value types and UI slot names. Versioned. | application, domain |
| `netview.plugins.builtin.*` | Today's features as plugins. | sdk only (plus third-party and stdlib) |
| `netview.bootstrap` | Composition root: reads settings, builds adapters, loads plugins, wires use cases, creates the FastAPI app. | everything |

The rules are enforced with **import-linter** contracts in CI and test runs:

- the domain imports nothing from netview;
- application does not import infrastructure or presentation;
- built-in plugins import only `netview.sdk`.

### 5.2 Patterns *(my calls, standard in Python)*

- **Ports as `typing.Protocol`** for things the core calls out to (repositories, network tools). **ABC base class** for `Plugin`, so a plugin gets a clear error when it misses something.
- **Repository + Unit of Work** over SQLAlchemy 2.0 sessions. One unit of work per API request or scheduled job, which commits or rolls back as a whole.
- **Command/query split** in the application layer. Commands change state (`SetNickname`, `RecordSightings`, `ClaimName`, `AddWatch`, `RunInspection`); queries read it (`GetNetworkState`, `GetDevice`, `GetInspection`). Queries return read models (dataclasses), not ORM objects.
- **In-process event bus** for domain events: `DeviceDiscovered`, `DeviceWentOnline`, `DeviceWentOffline`, `NameChanged`, `NicknameChanged`, `TypeChanged`, `WatchStateChanged`. It feeds the Events list and the live-update stream, and plugins can subscribe.
- **Dependency injection by hand in the composition root.** FastAPI `Depends` is used for request-scoped things. No DI framework.
- **Settings with pydantic-settings:** a `netview.toml` file plus `NETVIEW_*` environment variables. Each plugin has its own Pydantic settings model.
- **Logging** with stdlib `logging` and per-plugin logger names (`netview.plugin.<id>`).

### 5.3 Concurrency

- FastAPI and uvicorn on asyncio.
- Today's probes are blocking (subprocess ping, sockets). They run in a bounded thread pool from async jobs.
- One scheduler owns all periodic work: each job has an interval, a timeout, and failure backoff. Today's "3 failures then back off" rule for the Starlink reader becomes a general scheduler feature. The scheduler can be in-house, a small class on asyncio *(my call; a library is fine if the builder prefers)*.
- Jobs of different plugins run independently. A slow or failing job never blocks others.

## 6. Domain and plugin capability interfaces

### 6.1 Core domain concepts

- **Device**, identified by a **DeviceKey**: the MAC address when known, otherwise the IP. This matches today's `key`.
  - It records IP, MAC, vendor, first seen, last seen, status (online/offline), and whether it is this device.
- **Nickname**: set only by the user. Every change is appended to a nickname history (time, old, new, who).
- **NameClaim** (name, source, rank, checked at): many sources may claim a name, and the domain picks the best by rank. Today's ranks are hostname 9, UPnP 6, AirPlay 5, NetBIOS 4, DHCP 3.5, mDNS 3, RDP certificate 2, DNS 1. Ranks become plugin-declared per source, and the domain keeps the ordering rule.
- **TypeClaim** (type, reason) and **Hint** (text), with the same multi-source approach.
- **Display name**, a domain rule: nickname, then best device name, then watch label.
- **Watch**: a host with optional ports and label. **WatchResult**: per layer (ARP, ping, TCP ports), today's chips.
- **LatencySample**, **TrafficSample** (down/up bytes per second, plus totals, signal and link rates where known), **Event**, **InspectionReport** (made of sections contributed by plugins).

### 6.2 Capability interfaces (what a plugin can provide)

Each is a small, separate interface, following SOLID's interface-segregation rule. A plugin implements any number of them.

| Capability | Contract (shape, not final signatures) | Built-in implementer |
|---|---|---|
| **Discovery** | `discover() -> Iterable[Sighting]` (ip, mac?, seen at) | `lan_discovery` (ping sweep and ARP) |
| **Identity** | `identify(device) -> Iterable[NameClaim \| TypeClaim \| Hint]`, with a recheck interval | `identity` (UPnP/SSDP, NetBIOS, mDNS, reverse DNS, vendor-based type) |
| **Health** | `probe(targets) -> Iterable[LatencySample]` for devices, gateway, internet, DNS servers, watches | `health` |
| **Traffic** | `read() -> Iterable[TrafficReading]` per device | `starlink` |
| **Destinations** | `read() -> Iterable[Flow \| DnsLookup]` per device. Defined now, no built-in implementer; the OPNsense plugin fills it later. | — |
| **Inspection** | `inspect(ip, options) -> Iterable[ReportSection]` | `inspection` (ports, HTTP/TLS, certificates, gRPC detection, mDNS, UPnP, NetBIOS) |
| **Local host** | this device's throughput, Wi-Fi details, open connections | `local_host` |
| **API** | `router() -> fastapi.APIRouter`, mounted at `/api/v1/plugins/<id>/` | any |
| **Web UI** | static folder plus slot registrations (section 7.5) | any |
| **Storage** | SQLAlchemy `MetaData` plus an Alembic migrations folder | `starlink` (counter baselines) |
| **Jobs** | `jobs() -> list[JobSpec]` (name, interval, timeout, callable) | most |

**Core features vs plugins** *(my call, after review)*:

- Scan, probe, watches and inspection are **core features**. Their endpoints and use cases are core, and they **fan out** to every enabled plugin with the matching capability.
- **Inspection:** `RunInspection` calls every Inspection plugin and merges their report sections into one `InspectionReport`, stored in a **core** table. A later plugin can add a section to the same report.
- **Watches:** a watch is a core record, and Health plugins check it.
- **No provider enabled:** when no enabled plugin provides a capability, the endpoint returns `409` with "no enabled plugin provides <capability>", and the UI hides or disables the matching button.

The core turns capability output into domain changes through use cases. For example, a `Sighting` passes through `RecordSightings`, which updates the device, sets online/offline status, and emits `DeviceDiscovered`. That way the rules live in one place.

## 7. Plugin system

### 7.1 Packaging and discovery

- A plugin is a Python package with one entry class that subclasses `netview.sdk.Plugin`.
- Plugins are found through **entry points** in the group `netview.plugins`. That is the standard Python mechanism, and the same one pytest and Flask use.
- Built-in plugins register through netview's own `pyproject.toml`, so they are loaded exactly like external ones.
- Local development plugins can also be loaded from a configured folder *(my call; handy for the user's own plugins)*.

### 7.2 Manifest

Each plugin declares the following as class attributes, validated with Pydantic:

- id (lowercase, `[a-z][a-z0-9_]*`), name, version, description;
- `sdk_version`, a compatible range checked at load time;
- capabilities provided;
- **permissions requested**: `devices:read`, `names:write`, `types:write`, `traffic:write`, `storage:own`, `api`, `ui`, `network:probe`. These are **recorded and shown in the UI now, and not enforced**, so enforcement can be switched on when sandboxing arrives without rewriting plugins.

### 7.3 Lifecycle

1. Discover.
2. Validate the manifest and SDK version.
3. Skip it if disabled in settings.
4. Run its storage migrations.
5. Call `setup(ctx)`.
6. Register its capabilities, router and UI.
7. Start its jobs.

On shutdown, jobs stop and then `shutdown()` is called. A plugin that fails any step is marked **failed** with the error, shown on the Plugins page, and skipped. The app keeps running.

### 7.4 Plugin context (what the core gives a plugin)

`ctx` provides:

- **Plugin details:** its settings and a logger.
- **Shared services:**
  - a clock;
  - network tools: ping, ARP table, TCP probe, DNS query, TLS fetch, HTTP fetch, mDNS/NetBIOS/SSDP helpers — the shared OS-specific adapters, so plugins don't each reimplement them;
  - the OUI vendor lookup.
- **Core queries** (read devices, names, nicknames, watches) and **core commands** (record sightings, claim names/types/hints, record traffic, add events). There is deliberately **no command to set a nickname**.
- **Database access:** a unit of work for the plugin's own tables.
- **Events:** subscribe to domain events.

### 7.5 Database access

- A plugin's tables must be named `<plugin_id>_<table>`. The loader rejects anything else.
- Each plugin has its own Alembic version branch. It is upgraded when the plugin is first enabled or its version changes, and never downgraded automatically.
- A plugin reads and writes its own tables through SQLAlchemy sessions from `ctx` within the job's or request's unit of work, so its own rows and the core changes it triggers commit together.
- Plugins never query core tables or other plugins' tables directly.

### 7.6 Web UI extension

- **No build step, as today.** The UI is plain JavaScript ES modules served by FastAPI. Plugin static files are served at `/plugins/<id>/static/`.
- **Core shell.** The core page is a shell with navigation and these named **slots**:
  - `dashboard.tile`
  - `dashboard.card` (charts and panels)
  - `devices.column` (a column definition: header, sort key, cell renderer). It must work with grouping, show/hide and sort, like today's columns.
  - `report.live-section` (redrawn on each update) and `report.section` (static)
  - `page` (a whole new page, with a nav entry)
  - `settings.section`
- **Registration.** A plugin's module default-exports `register(ui)`, and calls `ui.slot(name, spec)`. The core passes it the current state, the plugin's API base URL, and shared helpers: chart, sparkline, byte/rate formatting, theme tokens, escaping.
- **Isolation.** A plugin module that throws is caught, logged in the browser console and shown as a small error in its slot. The page keeps working.
- **Settings and Plugins page (core).** It lists every plugin with status, version, capabilities and requested permissions, an on/off switch, and a settings form generated from the plugin's settings model's JSON schema.

### 7.7 Settings and when changes apply *(my call, after review)*

- **Core settings** (bind address, port, data directory, subnet, intervals) come from `netview.toml` and `NETVIEW_*` environment variables. Environment variables beat the file. They are not edited in the UI in the first release.
- **Plugin on/off and plugin settings** live in the database (`plugin_state`) and are edited on the Plugins page or with `PATCH /api/v1/plugins/{id}`. A `[plugins.<id>]` section in `netview.toml` only seeds the first-run defaults; after that, the database wins.
- **Settings changes apply live.** The plugin's settings object is replaced and its jobs restart with the new values. Example: changing the Starlink router address.
- **Turning a plugin on or off applies at the next restart.** The UI says "restart to apply". This keeps the loader a one-time startup step (mounting and removing FastAPI routers at runtime is awkward). Live on/off can come later.

### 7.8 Trust

Plugins run in the same process with full access. That is acceptable because the user writes them. When third-party plugins arrive, the manifest permissions become enforced. Out-of-process plugins are a likely route, but not designed here.

## 8. Data

### 8.1 Database

- SQLite file in the data directory. WAL mode, SQLAlchemy 2.0, Alembic.
- PostgreSQL later should be a connection-string change: no SQLite-only SQL in repositories.

### 8.2 Core tables (indicative)

`devices`, `device_names` (claims), `device_types`, `device_hints`, `nicknames`, `nickname_history`, `watches`, `events`, `inspection_reports`, `plugin_state` (enabled, settings JSON, installed version).

In `nickname_history`, "who" is **free text**. The old store has values like "claude: cleared auto-written nickname"; new UI changes record "user".

### 8.3 Live samples

- Latency, DNS timing, traffic rates and this-device throughput are kept in memory behind a **MetricsStore** port, with about 120 samples per series as today.
- A persistent MetricsStore is a later swap-in.

### 8.4 Data directory

- Configurable with `--data-dir` / `NETVIEW_DATA_DIR`. The default is the platform's user data folder (via `platformdirs`) *(my call)*.
- The HomeLab launch configuration points it at `R:\source\claude projects\HomeLab\network\netview\`.

### 8.5 Import from the old monitor

`netview import-lanmon <lan_store.json>` copies, in one transaction:

- nicknames, with their history;
- watches;
- known devices (first seen, name, name source, type).

It is idempotent (safe to run twice) and never changes the source file. A nickname already set in netview is never overwritten by the import; it reports the conflict instead.

**Running both tools** *(my call, after review)*:

- The old monitor may keep running during the side-by-side check. Both sweeping the subnet and polling the Starlink router every 5 seconds is light, read-only load.
- The import can be **re-run** to pick up nicknames changed in the old tool:
  - new nicknames and new history entries are added;
  - a nickname that differs on both sides is listed as a conflict and left alone, unless the user passes `--prefer-source` for that run.

## 9. API and presentation

- **REST, versioned, JSON.** Core endpoints:
  - `GET /api/v1/state` (dashboard snapshot)
  - `GET /api/v1/devices`, `GET /api/v1/devices/{key}`
  - `PUT /api/v1/devices/{key}/nickname`
  - `GET|POST|DELETE /api/v1/watches`
  - `POST /api/v1/scan`
  - `POST /api/v1/devices/{ip}/probe`
  - `POST /api/v1/inspections`, `GET /api/v1/inspections/{ip}`
  - `GET /api/v1/events`
  - `GET /api/v1/plugins`, `PATCH /api/v1/plugins/{id}`
- **Plugin endpoints** live under `/api/v1/plugins/<id>/…`.
- **OpenAPI docs** at `/docs`, served from local assets with no CDN *(my call; matches the strict CSP)*.
- **Live updates** are pushed with **Server-Sent Events** at `/api/v1/stream`: state deltas and domain events. The page falls back to polling if the stream drops *(my call: simpler than WebSockets, and enough for one-way updates)*.
- **CLI (Typer):**
  - `netview serve` (options as today: subnet, interval, fast, port, bind, open)
  - `netview scan --once [--list] [--out]`
  - `netview inspect IP [--ports] [--out]`
  - `netview import-lanmon PATH`
  - `netview plugins list`
  - `netview db upgrade`

## 10. Feature parity checklist (first release)

Everything below exists today and must work in netview, delivered by the plugin in brackets.

- **Discovery** [`lan_discovery`]:
  - subnet sweep (ping plus ARP) on an interval;
  - vendor lookup (built-in OUI table, optional IEEE/Wireshark file; "Random or local MAC" for locally administered MACs);
  - first and last seen, online/offline;
  - new-device events;
  - manual "Scan now".
- **Health** [`health`]:
  - gateway and internet ping;
  - DNS timing for up to two servers;
  - live ping of every online device (up to 64), with latency history and last/loss/avg/min/max/jitter;
  - watched hosts with ARP/ping/TCP layer chips;
  - add and remove watches.
- **Identity** [`identity`]:
  - names from UPnP/SSDP (multicast on the right interface), NetBIOS, mDNS, reverse DNS, and DHCP names from Starlink;
  - ranking as today;
  - recheck after 30 minutes;
  - device type and hints, including the fixed rules (a self-identification hint first; an AirPlay receiver from a non-Apple maker is not "Apple").
- **This device** [`local_host`]:
  - download/upload throughput;
  - Wi-Fi details;
  - established, trying and listening connections with process names, leaving out netview's own sockets.
- **Inspection** [`inspection`]:
  - port scan (top, all, ranges) with open/closed/filtered;
  - HTTP and TLS probing with clickable web interfaces and certificate details;
  - HTTP/2 / gRPC detection;
  - mDNS, UPnP and NetBIOS details;
  - stored reports; "Inspect any IP".
- **Router traffic** [`starlink`]:
  - per-device download/upload rates, totals since connecting, signal, link rates, mesh role;
  - network totals; top uploader over 10 minutes;
  - "uploaded while idle";
  - ACR guidance for TVs;
  - failure backoff;
  - on/off via plugin settings (replacing `--router-api off`).
- **Core UI**:
  - tiles and the latency, DNS and throughput charts, following today's chart rules (validated palette, line breaks across sampling gaps, hover tooltips, table view, direct labels);
  - device table with filter, status buttons, sorting, **grouping** (status, type, vendor, IP regex) and **show/hide columns** (Status, IP and Actions fixed; never both Nickname and Device name hidden; "Show all");
  - nickname editing;
  - connections card with tabs;
  - Events list;
  - report dialog with live section;
  - light/dark theme;
  - view preferences remembered in the browser.
- **Wording**: "This device", not "This PC".

## 11. Quality

- **Tooling:** `uv` for environments and the lockfile (installed on this laptop), `hatchling` build backend, ruff (lint and format), mypy (strict on `domain`, `application` and `sdk`), pytest with coverage.
- **Tests:**
  - Domain and application unit tests with in-memory fakes for every port.
  - Repository and migration tests on a temporary SQLite database.
  - API tests with FastAPI's test client.
  - A **plugin contract test kit** in `netview.sdk.testing` that any plugin can run against itself.
  - Parser tests for each OS adapter using recorded command output (Windows now; Linux samples where available).
  - import-linter architecture contracts.
- **Manual check:** run against the real network and compare with today's dashboard side by side before calling parity done.

## 12. Left to the builder

- Exact class and function signatures, module split inside each layer, and table columns.
- Whether the scheduler is in-house or a library.
- How state deltas are shaped on the live stream.
- Visual layout of the new navigation and Plugins page, as long as today's dashboard look and chart rules carry over.
- Order of work, as long as the plugin interface is in place before features are ported, so they are ported *as* plugins.

## 13. Addendum (2026-11-10): settings dialog, themes and visual design

Requested by the user after the first build: a more professional look, settings in their own dialog with a tab per plugin, and a theme picker driven by stylesheets in a theme folder, so anyone can add a theme.

### 13.1 Settings dialog (user's request)

- A **settings icon** (gear, inline SVG) in the top bar opens a modal **Settings** dialog. It replaces the Plugins page; the old `#/plugins` link opens the dialog on its Plugins tab.
- The dialog has a left tab rail and a content pane:
  - **Appearance:** theme choice (13.2).
  - **Plugins:** an overview of every plugin with name, status (active, disabled, failed with its error), version and on/off switch, plus the "Restart to apply" notice when needed.
  - **One tab per plugin**, named after the plugin:
    - status and version, on/off switch, description;
    - "What it can do" (capabilities) and "Access it asks for" (permissions) as labelled chips with plain-language names;
    - the settings form generated from its schema (titles, help text, min/max), with a **Save settings** button that confirms "Settings saved" or shows the validation error inline;
    - anything the plugin registers in the `settings.section` slot.

    Failed plugins get a tab too, showing the error.
- Keyboard: Escape closes; tabs work with arrow keys; focus returns to the gear on close.

### 13.2 Themes (user's request)

- **Folders:**
  - Themes are plain CSS files in a theme folder. Built-in themes ship in `presentation/web/static/themes/`.
  - **User themes** go in `<data_dir>/themes/`, served at `/themes/user/`. Adding one is dropping in a `.css` file; no code change and no restart (the list is read on each request).
- **Theme file format:**
  - The file's first comment is its header: `/* netview-theme name="Graphite" scheme="dark" preview="#1b1f24,#242a31,#4fb3c8" */`. `scheme` is `light` or `dark`; `preview` gives three swatch colours for the picker.
  - The id is the file name without `.css`, and must match `^[a-z0-9][a-z0-9-]{0,40}$`; other files are ignored. User theme ids are prefixed `user-`, so they never shadow a built-in.
  - A file without a valid header is listed as a broken theme with the reason, never applied.
- **Token contract:**
  - A theme sets only CSS custom properties (the contract) on `:root`, plus `color-scheme`. All component styling lives in `app.css`, which uses only those tokens.
  - The token list and a copy-me starter live in `themes/README.md`.
- **API:** `GET /api/v1/themes` returns `{id, name, scheme, preview, source: "built-in"|"user", url, error}` for each theme, plus the user theme folder path.
- **Choosing a theme:**
  - The choice is per browser (`localStorage` key `netview-theme`).
  - "Match system" is the default, using the built-in light and dark defaults through `media`-scoped `<link>` tags, so there is no flash on load.
  - Picking a theme swaps one `<link id="theme">`.
- **Built-in themes:**

  | Theme | Scheme | Notes |
  |---|---|---|
  | Daylight | light | default light |
  | Graphite | dark | default dark |
  | Harbor | dark | deep navy-teal, the distinctive one |
  | Contrast | dark | high contrast for accessibility (WCAG AAA text) |

  Each theme's series colours pass the dataviz palette validator against its own surface.

### 13.3 Visual design *(my call; the user asked for "more professionally styled")*

- **Character:** a calm instrument panel for one technical owner. Dense but quiet. Colour is used only for status and one accent per theme. Numbers use tabular figures; IPs and MACs use a monospace face so the addresses line up.
- **Type:**
  - System stacks only, since the CSP forbids remote fonts: `"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif` for text, and `"Cascadia Mono", Consolas, ui-monospace, monospace` for addresses.
  - Scale 12 / 13 / 14 / 16 / 20 / 28 px.
  - Sentence case everywhere: no all-caps labels, no middle-dot meta strings.
- **Layout:**
  - A 56 px top bar: wordmark and "This device …" on the left, nav tabs (Dashboard, Devices, plugin pages), then the live indicator and the settings icon on the right.
  - Content is fluid and left-aligned, up to 1440 px.
  - The Devices toolbar is one wrapping row: search grows, then the status segmented control, Group by, Columns, and the device count on the right.
  - The table sits directly on the page surface (not in a card), with a sticky header, 36 px rows and a subtle row hover.
- **The one memorable thing:** the live indicator. Each data update draws a single radar-style ring from the dot, so motion answers a real event. It is skipped under `prefers-reduced-motion`.
- **Quality floor:** visible keyboard focus, usable at 360 px wide, and contrast checked in every theme.

### 13.4 Amendment to §7.5 (after review)

A plugin's own tables commit in the plugin's own unit of work (`ctx.unit_of_work()`). Core changes made through `CoreFacade` commit separately. A plugin that needs both writes its own rows first and then calls the core command; core commands are idempotent, so a retry is safe. Writes from a plugin's session to tables outside its `<plugin_id>_` prefix are refused at the database level.
