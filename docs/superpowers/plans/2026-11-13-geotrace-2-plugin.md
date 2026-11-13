# GeoTrace part 2: the plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The GeoTrace folder plugin: saved targets traced on a schedule, every trace kept, hops placed on a CesiumJS globe served from NetView's own origin, with compare, trends, route-change events, a server-side tile cache and DB-IP geolocation.

**Architecture:** `plugins/geotrace/` follows the Roku plugin's shape. Small pure modules (addresses, placement, signature/events, trends) sit under a `GeoTraceService`. The service owns the stores (plugin SQLite tables), the trace queue and its worker thread, the DB-IP updater, the tile cache and the Cesium bundle manager. A FastAPI router exposes them, and jobs drive the schedule, retention and monthly updates. The UI is plain ES modules in `static/`: a `page` slot with an icon rail and a blade stack over the globe, and a `settings.section` slot for the parts of Settings a form can't do.

**Tech Stack:** Python 3.11, FastAPI, pydantic, SQLAlchemy + Alembic, stdlib `urllib`/`threading`/`gzip`/`zipfile`/`ipaddress`/`math`, `maxminddb`; plain JS ES modules, CesiumJS 1.144 (downloaded bundle), NetView's `chart.js`; pytest, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-12-geotrace-plugin-design.md`. Approved mockup: `docs/superpowers/specs/2026-11-12-geotrace-mockup.html`. Spike findings: `docs/superpowers/spikes/2026-11-13-geotrace/README.md` (from Part 1). **Part 1 (`2026-11-13-geotrace-1-spikes-and-core.md`) must be merged into this branch first; do not start if a spike stop rule fired.**

## Global Constraints

- Folder plugin at `plugins/geotrace/` (never built in). Runtime package `netview_local_plugins.geotrace`; `__init__.py` sets `plugin_class = GeoTracePlugin`. Modules import each other relatively and the core only through `netview.sdk`. Allowed libraries: stdlib, `fastapi`, `pydantic`, `sqlalchemy`, `alembic` (migrations), `maxminddb`. An AST test enforces this (copy `plugins/roku/tests/unit/test_roku_imports.py`). `maxminddb` is imported directly, the way plugins already import `pydantic` and `fastapi`; this replaces the SDK reader port in spec §5.4, which would wrap one call for no gain.
- Tests in `plugins/geotrace/tests/{unit,integration,fixtures,js}/`, Python files named `test_geotrace_*.py`, JS files `geotrace-*.test.mjs`.
- Gate for every task: `uv run pytest -q && npm test && uv run ruff check src tests plugins && uv run mypy src plugins && uv run lint-imports`.
- Manifest: name `GeoTrace`, display name `GeoTrace`, version `0.1.0`, guid `f64f43b1-9ff2-47b9-badf-390b2fef25db`, `plugin_type` `software`, `sdk_version=">=2.1,<3"`, author `Cadtastic`, homepage `https://github.com/Cadtastic/NetView/tree/main/plugins/geotrace`. Capabilities `STORAGE`, `API`, `WEB_UI`, `JOBS`. Permissions `storage:own`, `api`, `ui`, `network:probe`, `network:internet`. `plugin.json` matches the manifest field for field.
- Tables `geotrace_target`, `geotrace_trace`, `geotrace_hop`; Alembic revision ids prefixed `geotrace_`.
- Targets: at most 50; intervals exactly 5, 15, 30, 60 minutes (default 15); family `ipv4` or `ipv6` (default `ipv4`); an IP literal's own family wins over the field.
- One run: resolve for the target's family only; traceroute max 30 hops, 1000 ms per probe; ping burst 10 pings, 200 ms apart, 800 ms timeout each; jitter = mean absolute difference of consecutive RTTs.
- Retention: traces older than `retention_days` (default 90, range 7-3650) are deleted daily; one-off traces (`target_id IS NULL`) after 7 days.
- Speed-of-light check: implausible when `distance_from_home_km > min_rtt_ms * 100 + 200`.
- Route change: signature differs from the previous saved trace's **and** the next trace agrees. Slowdown: last-hour median RTT > 1.4 × previous-24 h median **and** at least 10 ms more; at most one per target per 6 h. Unreachable after 3 failures in a row; "back" on the next success.
- Event text prefix exactly `GeoTrace · `. Examples: `GeoTrace · netflix.com: route changed at hop 4 (Salt Lake City → Dallas), +14 ms`; `GeoTrace · netflix.com: slower, 58 ms (usually 41 ms)`; `GeoTrace · work VPN: unreachable (3 traces in a row)`; `GeoTrace · work VPN: reachable again`.
- Outbound User-Agent for every request (tiles, DB-IP, Cesium bundle, Nominatim): `NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)`.
- Tile sources: `osm` = `https://tile.openstreetmap.org/{z}/{x}/{y}.png` (max zoom 19); `eox-s2` = `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg` (max zoom 14); `custom` = admin template with `{z}`,`{x}`,`{y}`, https only. Cache cap default 500 MB (range 50-20000). Minimum freshness 7 days for `osm`. 2 upstream requests in flight per source. A tile must be PNG or JPEG by magic bytes and under 1 048 576 bytes. Never prefetch.
- DB-IP: `https://download.db-ip.com/free/dbip-city-lite-{YYYY}-{MM}.mmdb.gz` and `…/dbip-asn-lite-{YYYY}-{MM}.mmdb.gz`. Attribution link text exactly `IP geolocation by DB-IP`, href `https://db-ip.com`.
- Nominatim: `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&q=…`, at most 1 request a second, results cached in memory for 1 hour.
- Starlink ASN: 14593. Satellite marker altitude 550 000 m.
- UI: no inline `<script>`; theme tokens only; every CSS class `gt-` prefixed; every `localStorage` access in try/catch, keys `netview.geotrace.target` and `netview.geotrace.blades`. Polling: a running trace every 1 s; the target list every 30 s while the page is visible; nothing while hidden.
- Copy, exactly: empty state `No targets yet. Add one to start tracing.`; home hint `Set your home location in GeoTrace settings so the first hops start at your house.`; bundle state `Preparing the globe (one-time download, about 8 MB)…`; no-geo state `Location data is still downloading. Hops are listed but not placed yet.`; Linux missing tool `traceroute is not installed on the NetView server.`

## Review Focus

1. **A web address whose answer changes between runs** (CDN round robin, or an IPv6 target where the site has no AAAA record): each trace stores the IP it actually reached; "has no IPv6 address" is a failed trace with that reason, not an exception. A changed IP alone is not a route change. Tests in Tasks 3 and 7.
2. **Two runs of the same target racing** (schedule tick and "Trace now" together, or a double click): only one is queued; the second request returns the queued trace's id. Test in Task 8.
3. **A trace where every hop after the gateway is silent or private** (home router blocks ICMP): no arcs to nowhere, no division by zero in stats, signature empty, so no change event. Tests in Tasks 5 and 6.
4. **Tile requests with out-of-range or crafted coordinates** (`z=99`, `x=-1`, `y=2**z`, `source=../../etc`): 404 without any upstream request. Test in Task 10.
5. **The DB-IP download returns an HTML error page, a truncated gzip, or last month's file is all there is** (early in the month before the new file appears): the previous database stays in use, and the error is shown in Settings. Test in Task 4.

---

### Task 1: Plugin skeleton, manifest, settings

**Files:**
- Create: `plugins/geotrace/__init__.py`, `plugin.py`, `plugin.json`, `settings.py`
- Create: `plugins/geotrace/tests/conftest.py` (copy of the Roku pattern), `tests/unit/test_geotrace_imports.py`, `tests/unit/test_geotrace_settings.py`, `tests/integration/test_geotrace_loads.py`

**Interfaces:**
- Produces: `GeoTracePlugin` (manifest above; `settings_model = GeoTraceSettings`; `setup`, `storage`, `ui`, `router`, `jobs` filled in by later tasks); `GeoTraceSettings` (pydantic) with fields and tabs:
  - tab `General`: `home_label: str = ""`, `home_lat: float | None = None` (-90..90), `home_lon: float | None = None` (-180..180), `retention_days: int = 90` (7..3650), `default_interval_min: Literal[5, 15, 30, 60] = 15`, `default_family: Literal["ipv4", "ipv6"] = "ipv4"`
  - tab `Map`: `tile_source: Literal["osm", "custom"] = "osm"`, `custom_tile_url: str = ""` (required when `custom`; must start `https://` and contain `{z}`,`{x}`,`{y}`), `base_imagery: Literal["natural_earth", "eox_s2"] = "natural_earth"`, `tile_cache_mb: int = 500` (50..20000)
  - tab `Location data`: `geo_auto_update: bool = True`
  - `json_schema_extra=settings_tabs(["General", "Map", "Location data"])`; `enum_labels` for the literals (`osm` → "OpenStreetMap", `custom` → "Custom tile server", `natural_earth` → "Natural Earth (built in)", `eox_s2` → "Sentinel-2 cloudless (EOX, non-commercial)")

- [ ] **Step 1: Write the failing tests:** the import rule; settings defaults, bounds and the custom-URL rule (`"http://x/{z}/{x}/{y}"` rejected, `"https://x/{z}/{x}"` rejected); the schema's tab names in order; `plugin.json` equals the manifest; the plugin loads Active from `--plugin-dir` in a test app (Roku's `test_plugin_test_seeds.py` pattern) with `ctx.files_dir` available.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement** the skeleton (empty router, no jobs yet, a `ui()` pointing at `static/` with a placeholder `ui.js` that registers nothing).
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): plugin skeleton, manifest and settings"`

---

### Task 2: Storage

**Files:**
- Create: `plugins/geotrace/storage.py`, `plugins/geotrace/model.py`, `plugins/geotrace/migrations/versions/0001_initial.py`
- Test: `plugins/geotrace/tests/integration/test_geotrace_storage.py`

**Interfaces:**
- Produces (in `model.py`, frozen dataclasses):
  - `Target(id: int, name: str, address: str, family: str, interval_min: int, enabled: bool, created_ms: int, updated_ms: int)`
  - `Hop(n: int, ip: str | None, rtts_ms: tuple[float | None, ...], city: str, region: str, country: str, lat: float | None, lon: float | None, asn: int | None, as_org: str, placement: str, plausible: bool)`; `placement` ∈ `located|home|assumed|none`
  - `Trace(id: int, target_id: int | None, trigger: str, mode: str, status: str, error: str | None, started_ms: int, finished_ms: int | None, resolved_ip: str | None, family: str, reached: bool, hop_count: int, rtt_ms: float | None, loss_pct: float | None, jitter_ms: float | None, ping_min_ms: float | None, ping_max_ms: float | None, signature: str, hops: tuple[Hop, ...])`; `trigger` ∈ `scheduled|manual|once`, `mode` ∈ `trace|ping`, `status` ∈ `queued|running|done|failed`
- Produces (in `storage.py`): `storage_spec() -> StorageSpec`; `TargetStore(uow_factory)` with `list() -> list[Target]`, `get(id) -> Target | None`, `add(name, address, family, interval_min, enabled, now_ms) -> Target`, `update(id, **fields) -> Target | None`, `delete(id) -> bool` (deletes its traces and hops too), `count() -> int`; `TraceStore(uow_factory)` with `save(trace: Trace) -> int` (insert trace + hops in one transaction, returns id), `get(id) -> Trace | None`, `latest(target_id, n=1, status="done") -> list[Trace]` (newest first), `page(target_id, before_ms: int | None, limit: int) -> list[Trace]` (no hops), `between(target_id, since_ms, until_ms) -> list[Trace]` (no hops), `delete_older(target_cutoff_ms, once_cutoff_ms) -> int`.
- `signature` is stored as a JSON string of `[[asn, city], …]`.

- [ ] **Step 1: Write the failing tests:** round-trip of a trace with three hops including a silent one; `latest` order; `delete(target)` cascades; `delete_older` respects the two cutoffs; `page` paging with `before_ms`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement** (index `geotrace_trace(target_id, started_ms)`).
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): storage for targets, traces and hops"`

---

### Task 3: Addresses

**Files:**
- Create: `plugins/geotrace/addresses.py`
- Test: `plugins/geotrace/tests/unit/test_geotrace_addresses.py`

**Interfaces:**
- Produces: `class ResolveError(Exception)`; `resolve(address: str, family: str, getaddrinfo=socket.getaddrinfo) -> str` (an IP literal returns itself and its own family wins; otherwise the first `AF_INET`/`AF_INET6` result; raises `ResolveError("<address> has no IPv6 address")`, `ResolveError("<address> has no IPv4 address")` or `ResolveError("cannot find <address>")`); `classify(ip: str) -> Literal["public", "private", "cgnat", "none"]` (`private` = RFC 1918, loopback, link-local, `fc00::/7`, `fe80::/10`; `cgnat` = `100.64.0.0/10`; `none` = unparseable); `family_of(ip: str) -> Literal["ipv4", "ipv6"]`; `valid_address(text: str) -> bool` (an IP literal, or a host name of 1-253 chars made of letters, digits, `-` and `.`, no scheme, no path).

- [ ] **Step 1: Write the failing tests** (fake `getaddrinfo`; include Review Focus 1's no-AAAA case and `"https://netflix.com/"` rejected by `valid_address`).
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): address resolving and classification"`

---

### Task 4: Location data (DB-IP)

**Files:**
- Create: `plugins/geotrace/geo.py` (locator), `plugins/geotrace/geodata.py` (download and swap)
- Test: `plugins/geotrace/tests/unit/test_geotrace_geo.py`, `test_geotrace_geodata.py`

**Interfaces:**
- Produces (`geo.py`): `Location(city: str, region: str, country: str, lat: float, lon: float, asn: int | None, as_org: str)`; `class HopLocator(Protocol): def locate(self, ip: str) -> Location | None`; `DbipLocator(city_path: Path | None, asn_path: Path | None, open_reader=maxminddb.open_database)` with `locate` and `close()`. City fields come from the mmdb's `city.names.en`, `subdivisions[0].names.en`, `country.iso_code`, `location.latitude/longitude`; the ASN from `autonomous_system_number` / `autonomous_system_organization`. A record without coordinates gives `None`.
- Produces (`geodata.py`): `GeoData(folder: Path, clock, opener=urllib.request.urlopen)` with `status() -> dict` (`{"city": {"month": "2026-11", "path": …} | None, "asn": …, "last_error": str | None, "checked_ms": int | None}`), `ensure() -> None` (downloads both files if missing), `update(force: bool = False) -> None` (tries this month, then last month if this month's file 404s; skips when the current month is already present unless `force`), `locator() -> DbipLocator` (newest good files). A download is streamed to `<name>.part`, gunzipped, opened once with the reader and checked for at least 1000 records via `reader.metadata().node_count`, then renamed into place. Older months are deleted only after the new one opens. Every failure sets `last_error` in plain words and keeps the current files.

- [ ] **Step 1: Write the failing tests:** locator with a fake reader (city + asn, missing coordinates → None, missing ASN db → asn None); `update` with a fake opener: good gzip → new month in place; HTML body → error kept, old file kept; truncated gzip → same; this month 404 → last month used (Review Focus 5); request carries the User-Agent.
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): DB-IP location data with safe monthly updates"`

---

### Task 5: Placing hops

**Files:**
- Create: `plugins/geotrace/placement.py`
- Test: `plugins/geotrace/tests/unit/test_geotrace_placement.py`

**Interfaces:**
- Consumes: `TraceHop` (SDK), `HopLocator`, `classify`, `Hop`.
- Produces: `Home(lat: float, lon: float, label: str)`; `haversine_km(a_lat, a_lon, b_lat, b_lon) -> float`; `place_hops(hops: Sequence[TraceHop], home: Home | None, locator: HopLocator | None) -> tuple[Hop, ...]` with the rules of spec §8.2-8.3: private → home coordinates (`placement="home"`; with no home they take the first located hop's coordinates); cgnat → next located hop's coordinates (`assumed`, city text from that hop); silent → `none`; public → locator (`located`, or `none` when not found); `plausible=False` when the Global Constraints rule fails (only for `located`, and only when home is set).

- [ ] **Step 1: Write the failing tests:** the mockup route (home, CGNAT gateway, Denver, Dallas, Phoenix, LA, silent, San Jose) placed as expected; a 2 ms hop located in London from Colorado → `plausible=False`; no home → private hops sit at the first located hop; everything silent after the gateway (Review Focus 3) → no `located` hops, no exception.
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): place hops with home, CGNAT and plausibility rules"`

---

### Task 6: Signatures, changes and events

**Files:**
- Create: `plugins/geotrace/changes.py`
- Test: `plugins/geotrace/tests/unit/test_geotrace_changes.py`

**Interfaces:**
- Produces: `signature(hops: Sequence[Hop]) -> list[tuple[int | None, str]]` (located hops only, consecutive duplicates collapsed); `first_difference(a, b) -> int | None` (index into the signatures); `ChangeTracker` (pure, fed one finished trace at a time per target, holding the small per-target state in memory and rebuilt from `TraceStore.latest(target_id, 3)` on startup) with `observe(target: Target, trace: Trace, recent_rtts: Sequence[tuple[int, float]]) -> list[str]`, returning event texts per the Global Constraints (route change with the two-in-a-row rule, slowdown with its thresholds and 6 h quiet period, unreachable after 3 failures, reachable again). Hop numbers in the route-change text are the trace's hop `n` of the first differing located hop.

- [ ] **Step 1: Write the failing tests:** identical signatures → no events; one different trace then back → no event (flap); two in a row → one event with the exact example text; slowdown fires once and not again within 6 h; 9 ms worse → no slowdown; 3 failures → unreachable, 4th → nothing, success → reachable again; empty signature (Review Focus 3) never fires a change.
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): route signatures and change events"`

---

### Task 7: Running one trace

**Files:**
- Create: `plugins/geotrace/runner.py`
- Test: `plugins/geotrace/tests/unit/test_geotrace_runner.py`

**Interfaces:**
- Consumes: `ctx.net.traceroute`, `ctx.net.ping`, `resolve`, `place_hops`, `signature`, `TraceStore`, `ChangeTracker`, `ctx.core.add_event(EventKind.PLUGIN, text, ip=resolved_ip)`.
- Produces: `LiveTrace` (mutable, thread-safe snapshot: `id`, `status`, `hops: list[Hop]`, `error`, `started_ms`) and `TraceRunner(ctx, traces, tracker, home_fn, locator_fn)` with `run(job: Job, live: LiveTrace) -> Trace`. `Job(target_id: int | None, address: str, family: str, trigger: str, mode: str, name: str)`. Steps per spec §6.2. Hops are placed as they arrive (so `live.hops` fills progressively) and saved once at the end. The ping burst computes `loss_pct`, `rtt_ms` (avg), min, max and jitter; with no replies, `rtt_ms`/`jitter_ms` are `None` and `loss_pct` is 100. A resolve or traceroute error gives a saved `failed` trace with the error text. Events come only from scheduled or manual traces of saved targets, never from `once`.

- [ ] **Step 1: Write the failing tests** with `FakePluginContext` + `FakeNetworkTools(traces=…, replies=…)`: a done trace saved with the resolved IP; hops appear in `live.hops` during `on_hop`; "has no IPv6 address" → failed trace (Review Focus 1); ping-only mode skips traceroute; a `once` trace raises no events; all pings lost → loss 100, jitter None.
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): run a trace end to end"`

---

### Task 8: Queue, worker and jobs

**Files:**
- Create: `plugins/geotrace/queue.py`, `plugins/geotrace/service.py`
- Modify: `plugins/geotrace/plugin.py` (`setup` builds the service and starts the worker; `shutdown` stops it within 5 s; `jobs()`)
- Test: `plugins/geotrace/tests/unit/test_geotrace_queue.py`, `test_geotrace_service.py`

**Interfaces:**
- Produces (`queue.py`): `due_targets(targets: Sequence[Target], last_started: Mapping[int, int], now_ms: int) -> list[int]` (a target with no history is due at `created_ms + offset`, where `offset = int(sha256(str(id)).hexdigest(), 16) % (interval_ms)`; afterwards every interval since its last start; an overdue target appears once); `TraceQueue` with `put(job, front: bool = False) -> int | None` (returns `None` if a job for that `target_id` is already queued or running), `get(timeout_s) -> tuple[int, Job] | None`, `live(trace_id) -> LiveTrace | None`, `running_for(target_id) -> int | None`.
- Produces (`service.py`): `GeoTraceService(ctx, settings)` with `start()`, `stop()`, `tick()` (enqueue due targets), `trace_now(target_id) -> int`, `trace_once(address, family, mode) -> int` (both return the existing trace id when one is queued or running for that target, Review Focus 2), `cleanup()`, `update_geo()`, `settings_changed(settings)`, plus accessors used by routes. The worker thread is named `geotrace-worker` and runs one job at a time.
- Jobs: `JobSpec("tick", 30, service.tick, timeout_s=10, initial_delay_s=15)`, `JobSpec("cleanup", 86400, service.cleanup, timeout_s=120, initial_delay_s=600)`, `JobSpec("geodata", 86400, service.update_geo, timeout_s=600, initial_delay_s=60)` (the last only when `geo_auto_update`).

- [ ] **Step 1: Write the failing tests:** hash offsets spread ten 15-minute targets across the interval; an overdue target after a restart is due once; `put` for an already queued target returns `None` and `trace_now` returns the existing id; `front=True` jumps the queue; `stop()` joins the worker; `tick` never enqueues disabled targets; 51st target refused by the service with `"at most 50 targets"`.
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): scheduled queue, worker thread and jobs"`

---

### Task 9: API

**Files:**
- Create: `plugins/geotrace/routes.py`, `plugins/geotrace/trends.py`
- Modify: `plugins/geotrace/plugin.py` (`router()`)
- Test: `plugins/geotrace/tests/unit/test_geotrace_trends.py`, `plugins/geotrace/tests/integration/test_geotrace_api.py`

**Interfaces:**
- Consumes: `GeoTraceService`, the stores, `ctx.audit`.
- Produces (paths under `/api/v1/plugins/<plugin id>`; GET needs *view*, others *use*, by the core's default guard):
  - `GET /targets` → `[{id, name, address, family, interval_min, enabled, last: {trace_id, started_ms, status, rtt_ms, loss_pct, hop_count} | null, note}]` (`note` like `route changed 3 h ago` / `steady 2 days`)
  - `POST /targets` `{name, address, family?, interval_min?, enabled?}` → 201 target; `PUT /targets/{id}`; `DELETE /targets/{id}` → 204
  - `POST /targets/{id}/trace` → 202 `{trace_id}`; `POST /trace-once` `{address, family, mode}` → 202 `{trace_id}`
  - `GET /traces/{id}` → full trace with hops (from `live` while running)
  - `GET /targets/{id}/traces?before_ms=&limit=50` → summaries, newest first
  - `GET /targets/{id}/compare?a=&b=` → `{a, b, rows: [{n, a: hop|null, b: hop|null, differs: bool}], split_after: int|null}`; defaults: `a` = newest, `b` = newest with a different signature (or the previous one)
  - `GET /targets/{id}/trends?range=24h|7d|30d|90d` → `{rtt: [[t_ms, ms|null]…], hops: […], loss: […], changes: [t_ms…]}` built by `trends.bucket(traces, since_ms, until_ms, buckets=96)` (median per bucket)
  - `GET /status` → `{geo: GeoData.status(), home_set: bool, traceroute_ok: bool}` (Task 11 adds `bundle`)
  - `GET /geocode?q=` → Nominatim results `[{label, lat, lon}]` (rate limit and cache per Global Constraints)
  - Validation errors are 422 with a plain message; unknown ids are 404.
  - `ctx.audit` on target add, edit and delete and on trace-once (`action` = `geotrace.target.add` / `.edit` / `.delete` / `geotrace.trace_once`; `target` = the address).

- [ ] **Step 1: Write the failing tests:** CRUD round trip; 50-target limit → 422; `valid_address` rule → 422 for `https://netflix.com/`; trace start then poll to done (fake net); compare alignment and `split_after`; trends medians and buckets with gaps as `null`; geocode uses a fake opener and is rate-limited (two calls in the same second → the second waits or is served from cache); audit entries recorded.
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): API for targets, traces, compare, trends and status"`

---

### Task 10: Tile proxy and cache

**Files:**
- Create: `plugins/geotrace/tiles.py`
- Modify: `plugins/geotrace/routes.py` (`GET /tiles/{source}/{z}/{x}/{y}`)
- Test: `plugins/geotrace/tests/unit/test_geotrace_tiles.py`, add to `test_geotrace_api.py`

**Interfaces:**
- Produces: `TileSource(name: str, url: str, max_zoom: int, min_fresh_s: int, ext: str, credit: str)`; `sources(settings) -> dict[str, TileSource]` (`osm`, `eox-s2`, and `custom` when configured); `TileCache(folder: Path, cap_bytes: int, clock, opener=urllib.request.urlopen)` with `get(source: TileSource, z: int, x: int, y: int) -> tuple[bytes, str] | None` (bytes and content type; `None` → 502). Stored as `tiles/<source>/<z>/<x>/<y>.<ext>`, with a small SQLite or JSON index file in the folder for `expires_ms`, `etag`, `last_modified`, `size` and `last_used_ms`. Behaviour per spec §11: freshness from `Cache-Control: max-age` / `Expires`, at least `min_fresh_s`; revalidation with `If-None-Match` / `If-Modified-Since` (a 304 refreshes expiry); LRU eviction down to 90% of the cap after each write; at most 2 in-flight upstream requests per source; identical requests share one fetch; magic-byte and size checks; the blocked-tile rule from spike S1 (if S1 found a recognisable blocked tile, treat it as a failure and do not cache it).
- Route: `source` must be a key of `sources(settings)`; `0 <= z <= max_zoom`, `0 <= x, y < 2**z`, else 404 with no upstream request (Review Focus 4). Response headers `Cache-Control: private, max-age=86400` and `X-Content-Type-Options: nosniff`.

- [ ] **Step 1: Write the failing tests:** fresh hit served from disk without the opener; expired → revalidated with the stored ETag, 304 keeps bytes; HTML body → 502 and nothing cached; 1.5 MB body → 502; cap exceeded → oldest-used evicted; 5 concurrent identical requests → one upstream call; Review Focus 4 coordinates → 404 and the opener never called; User-Agent header present.
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): server-side tile proxy with disk cache"`

---

### Task 11: Cesium bundle

**Files:**
- Create: `plugins/geotrace/tools/build_cesium_bundle.py` (`--help`; dry run by default; `--execute`; args `--release-zip PATH --out DIR`)
- Create: `plugins/geotrace/bundle.py`
- Modify: `plugins/geotrace/routes.py` (`GET /cesium/{path:path}`, `POST /bundle/download` *configure*-only via `ctx.require("configure")`)
- Test: `plugins/geotrace/tests/unit/test_geotrace_bundle.py`, `test_geotrace_bundle_tool.py`, add to `test_geotrace_api.py`

**Interfaces:**
- Produces (`bundle.py`): constants `CESIUM_VERSION = "1.144.0"`, `BUNDLE_URL`, `BUNDLE_SHA256`, `BUNDLE_BYTES` (placeholders `""`/`0` until the user publishes the asset; with an empty URL the status is `not_published` and the page says so); `BundleManager(folder: Path, opener=…)` with `status() -> {"state": "not_published"|"missing"|"downloading"|"ready"|"failed", "version", "error"}`, `ensure_async()` (one download at a time, on a background thread), `path_for(rel: str) -> Path | None` (resolves under `cesium/<version>/`, refuses `..`, absolute paths and anything outside the folder). The download is checked against the size and SHA-256, unzipped to `<version>.part/` and renamed into place.
- Tool: keeps `Build/Cesium/{Cesium.js, Workers/, ThirdParty/, Widgets/, Assets/}`, drops from `Assets/` everything except `Textures/NaturalEarthII/`, `Textures/SkyBox/`, `Textures/moonSmall.jpg`, `Images/` and `approximateTerrainHeights.json`; prints the output size and SHA-256. Its JSON report uses schema id `netview.geotrace/cesium-bundle@1`.
- `GET /status` gains `bundle: BundleManager.status()`, and the first GET of the page (`GET /status`) calls `ensure_async()` when the state is `missing`.
- Route: files are served with content types from `mimetypes` plus `.wasm` → `application/wasm`, `Cache-Control: public, max-age=31536000, immutable`; any directive spike S2 allowed for workers is added on `Workers/*.js` responses only.

- [ ] **Step 1: Write the failing tests:** traversal attempts (`../x`, `%2e%2e/x`, `C:/x`, `/etc/passwd`) → 404; a bad SHA → `failed` and nothing left behind; the tool's dry run lists but writes nothing, and `--execute` on a tiny fake release zip produces a zip with only the kept paths.
- [ ] **Step 2-4:** fail, implement, gate.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): downloaded Cesium bundle and its tool"`
- [ ] **Step 6 (user step, not a subagent's):** the user runs the tool against `Cesium-1.144.zip`, uploads the result as a release asset on Cadtastic/NetView, and the constants are filled in with a small follow-up commit `chore(geotrace): pin Cesium bundle`.

---

### Task 12: Page shell (rail and blades)

**Files:**
- Create: `plugins/geotrace/static/ui.js`, `page.js`, `blades.js`, `api.js`, `geotrace.css`
- Test: `plugins/geotrace/tests/js/geotrace-blades.test.mjs`

**Interfaces:**
- Produces: `createBladeStack()` (pure state; DOM done by `page.js`) with `open(key, opts: {level: number, wide?: boolean}) -> state`, `close(key) -> state` (closes it and every blade to its right), `minimise(key)`, `restore(key)`, and `state.blades: [{key, min: boolean, wide: boolean}]`. Opening a third blade minimises every blade except the last two (mockup behaviour). `api.js`: `gtGet(path)`, `gtSend(method, path, body)` built on `/static/js/api.js` with the plugin's base path. `page.js`: `createPage(ui, deps)` registering the page slot, rendering the top-level layout (globe host element, rail with Targets / Compare / Trends / Trace once / Settings, blade container, HUD) and the empty/hint/state banners with the exact copy from the Global Constraints. The settings rail button opens NetView's Settings on the GeoTrace section.

- [ ] **Step 1: Write the failing tests** for the blade stack rules (open, reopen same key replaces it and closes those to its right, third-blade minimising, close cascade) and for `localStorage` failures not throwing.
- [ ] **Step 2-4:** fail, implement, gate. Then a browser check: the page loads in NetView (launch config `netview-geotrace`, port 8776, scratch data dir), the rail and empty state show, and there are no console errors.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): page shell with rail and blades"`

---

### Task 13: Globe

**Files:**
- Create: `plugins/geotrace/static/globe.js`, `plugins/geotrace/static/geometry.js`, `plugins/geotrace/static/cesium-base.js`
- Test: `plugins/geotrace/tests/js/geotrace-geometry.test.mjs`

**Interfaces:**
- Produces: `geometry.js` (pure): `arcPoints(a, b, {liftM?, steps?}) -> [{lon, lat, h}]` (great-circle interpolation; default lift `min(distance_m * 0.12, 350000) + 2000`), `routePoints(hops, {starlink: boolean}) -> [{lon,lat,h}]` (skips hops without coordinates; when `starlink`, the first leg peaks at 550 000 m; callers pass `starlink = hops.some(h => h.asn === 14593)`), `blend(heightM) -> number` (0 at ≥ 4 000 000 m, 1 at ≤ 600 000 m, linear between, 0.92 max), `fitView(hops) -> {lon, lat, heightM}`. `globe.js`: `createGlobe(el, {baseUrl, tilesUrl, settings})` → `{showTrace(trace, {style: "solid"|"dashed", color}), clear(id), flyToHop(hop), fitRoute(), flyAlong(), setBase(kind), destroy()}`. `cesium-base.js` sets `window.CESIUM_BASE_URL` to `/api/v1/plugins/<id>/cesium/` before `Cesium.js` is added. Imagery: Natural Earth II from the bundle as the base; `eox-s2` and the street layer through `/tiles/...` with `UrlTemplateImageryProvider`; the street layer's alpha follows `blend()`. Colours are read from the theme's CSS variables at creation. The moving packet, labels and their fade distances follow the mockup. Credits show the active tile credit and the exact DB-IP link.

- [ ] **Step 1: Write the failing tests** for `arcPoints` (endpoints exact, peak at the middle), `routePoints` (silent hops skipped; Starlink first leg peak 550 000), `blend` (boundaries), `fitView` (single hop, empty list).
- [ ] **Step 2-4:** fail, implement, gate. Then a browser check with the real bundle (or the S2 spike copy) and a fake trace: the globe draws, zoom fades in the street map from the tile proxy, fly-to-hop lands near 9 km, and the console has no CSP errors.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): Cesium globe with routes, blend and camera moves"`

---

### Task 14: Targets, Route and Trace once blades

**Files:**
- Create: `plugins/geotrace/static/targets.js`, `route.js`, `once.js`, `poll.js`
- Test: `plugins/geotrace/tests/js/geotrace-poll.test.mjs`, `geotrace-targets.test.mjs`

**Interfaces:**
- Produces: `poll.js`: `createPoller(fetchFn, {intervalMs, isVisible}) -> {start(), stop(), now()}` (no overlapping requests; pauses while hidden). `targets.js`: renders the Targets blade (status dot = worst of reachability, loss > 0 and a slowdown note; add/edit form with name, address, IPv4/IPv6, interval, enabled; delete with confirm), selection stored in `netview.geotrace.target`. `route.js`: the Route blade per spec §10 (header line, Fit route / Fly along route / Compare… / Trends buttons, hop rows clickable to fly, a trace picker through history, live hops while running). `once.js`: address, IPv4/IPv6, Trace / Ping only / Save as target.

- [ ] **Step 1: Write the failing tests:** poller does not overlap and stops while hidden; the status-dot rule; the target form's client-side checks mirror `valid_address` (same three examples as Task 3).
- [ ] **Step 2-4:** fail, implement, gate. Browser check: add a target, Trace now, hops appear live, click a hop to fly, Trace once with Ping only.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): targets, route and trace-once blades"`

---

### Task 15: Compare and Trends blades

**Files:**
- Create: `plugins/geotrace/static/compare.js`, `trends.js`
- Test: `plugins/geotrace/tests/js/geotrace-compare.test.mjs`

**Interfaces:**
- Consumes: `GET /targets/{id}/compare`, `GET /targets/{id}/trends`, `lineChart` from `/static/js/chart.js`, `globe.showTrace(..., {style: "dashed"})`.
- Produces: `compare.js` renders two pickers (defaults from the API), the legend with show/hide for the older route, the aligned table with differing rows highlighted and "They split after hop N". `trends.js` renders the 24 h / 7 d / 30 d / 90 d chips and three `lineChart`s (time to destination, hop count, packet loss) with route-change markers. Closing Compare removes the dashed route.

- [ ] **Step 1: Write the failing tests** for the table model (`compareRows(apiRows)` → display rows with `differs` classes and the split sentence).
- [ ] **Step 2-4:** fail, implement, gate. Browser check against seeded traces with a route change.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): compare and trends blades"`

---

### Task 16: Settings section

**Files:**
- Create: `plugins/geotrace/static/settings.js`
- Modify: `plugins/geotrace/static/ui.js` (register `settings.section`)
- Test: `plugins/geotrace/tests/js/geotrace-settings.test.mjs`

**Interfaces:**
- Produces: a section under the GeoTrace settings form with: *Home location* (address search through `/geocode`, a small "Pick on the globe" button that opens the GeoTrace page in pick mode and writes `home_lat`/`home_lon`/`home_label` through the normal settings save); *Location data* (DB-IP month, last check, last error, "Update now", the attribution link, and greyed MaxMind / RIPE IPmap rows marked "coming later"); *Globe* (bundle state with "Download now" for *configure* holders). The form fields themselves come from the settings model (Task 1).

- [ ] **Step 1: Write the failing tests** for the status-to-text mapping (`geoStatusText(status)`, `bundleStatusText(status)`), including the `not_published` state.
- [ ] **Step 2-4:** fail, implement, gate. Browser check of the three tabs and the section.
- [ ] **Step 5: Commit** — `git commit -m "feat(geotrace): settings section for home, location data and globe"`

---

### Task 17: Catalog and finish

**Files:**
- Modify: `plugins/index.json` and the catalog JSON (regenerated by `uv run python scripts/build_plugin_index.py --execute`)
- Modify: `docs/superpowers/deferred.md`
- Create: `plugins/geotrace/README.md` (what it does, the outbound connections it makes, attribution, the bundle step)

- [ ] **Step 1:** Regenerate the index and check that `--check` passes.
- [ ] **Step 2:** Full gate.
- [ ] **Step 3:** Whole-feature browser pass on the scratch data dir: add three targets (one IPv6), wait for scheduled runs, compare, trends, uninstall and reinstall from the fake plugin repo (`scripts/serve_fake_plugin_repo.py`), and confirm the files folder is removed on uninstall.
- [ ] **Step 4: Commit** — `git commit -m "feat(geotrace): catalog entry, README and deferred notes"`
