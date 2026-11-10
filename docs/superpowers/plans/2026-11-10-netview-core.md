# netview core (plan 1 of 2): implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build netview's foundation (domain, use cases, SQLite storage, plugin system, REST API, web shell, CLI, lan_store import) and prove it end to end with the first built-in plugin, `lan_discovery`.

**Architecture:** Four layers, `domain` → `application` → `infrastructure` / `presentation`, plus a public `sdk` facade that plugins import. `bootstrap` is the composition root. Plugins are found through the `netview.plugins` entry-point group and contribute providers, jobs, an API router, UI modules and their own tables. import-linter enforces the dependency rule from task 1 on.

**Tech stack:**
- Python ≥ 3.11, uv, hatchling
- FastAPI, uvicorn, pydantic v2, pydantic-settings
- SQLAlchemy 2.0, Alembic
- Typer, platformdirs, packaging, swagger-ui-bundle
- Tests and checks: pytest, httpx, ruff, mypy, import-linter
- Web UI: plain JavaScript ES modules, with `node --test` for pure JS helpers (Node 24 is installed)

**Spec:** `docs/superpowers/specs/2026-11-10-netview-design.md`. Read it before starting. Section numbers below (§) refer to it.

**Porting source:** `R:\source\scripts\network-tools\scripts\lan_monitor.py` (abbreviated *LM* below) and `R:\source\scripts\network-tools\templates\lan_dashboard.html` (*LD*). Port behaviour from them where a step says so. They are read-only: never edit them.

**Plan 2 (separate, written after this one ships):**
- Built-in plugins `health`, `identity`, `local_host`, `inspection` and `starlink`.
- Dashboard charts, report dialog, watches UI, connections card and Events list.
- `netview inspect`.
- Side-by-side parity check (§10, §11).

## Global constraints

- `requires-python = ">=3.11"`. No syntax newer than 3.11. mypy runs with `python_version = "3.11"`.
- Package root is `src/netview/`. Times are integer epoch **milliseconds** (`*_ms`), as in LM.
- **Device keys:** `"self"` for this device, the normalised lower-case MAC (`aa:bb:cc:dd:ee:ff`) when known, otherwise `"ip:<ip>"`. These are identical to LM's keys, so the import maps 1:1.
- **Nicknames:**
  - Only `SetNickname` (the user, through the API) and the importer write nicknames.
  - The plugin-facing `CoreFacade` has **no** nickname writer.
  - Maximum 60 characters after trimming; longer values are rejected (HTTP 422), not truncated.
- **Plugins:**
  - Plugin ids match `^[a-z][a-z0-9_]*$`.
  - Plugin tables must be named `<plugin_id>_<name>`.
  - Plugin API is mounted at `/api/v1/plugins/<id>/`, static files at `/plugins/<id>/static/`.
- **SDK:** `netview.sdk.SDK_VERSION = "1.0"`. Manifests declare a PEP 440 specifier such as `">=1.0,<2"`.
- **Web security (§4):**
  - Default bind `127.0.0.1`, port `8765`.
  - Allowed `Host` names: `localhost`, `127.0.0.1`, `[::1]` and the configured bind address, with any port.
  - Every non-GET/HEAD request needs the header `X-Netview: 1`, or it gets 403.
  - Every response carries `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'`. That means no inline scripts, ever.
- **No CDNs.** Swagger UI is served from the `swagger-ui-bundle` package.
- **Read-only probing:** nothing sends configuration-changing requests to network devices.
- **Wording:** "This device", never "This PC".
- **Commits:** one commit per task, conventional-commit style. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review focus

These five input classes are implied by the spec but no feature test covers them naturally. Each has a pinned test in the task named.

1. **A device first seen without a MAC, then later with one.** Its nickname, name claims and first-seen time must move from `ip:<ip>` to the MAC key, with no duplicate row (task 4).
2. **Nicknames with apostrophes, Unicode or HTML** (`Jessi's Kindle`, `Café <b>`). They must be stored exactly as typed and shown escaped in the table, never as markup (tasks 4 and 11).
3. **A plugin job that hangs or raises every time.** It times out, is marked failed with backoff, and other jobs and the API keep working (task 6).
4. **Starting with no network** (no gateway, ARP empty, ping command failing). The app starts, the sweep finds 0 devices, and nothing crashes (tasks 7 and 12).
5. **A `lan_store.json` with missing or odd fields:** `label_history` entries without `by`, an empty-string nickname, `known` entries without `name`, unknown extra keys, and a UTF-8 BOM. The import still succeeds and never overwrites an existing nickname (task 13).

---

## File structure

```
netview/
  pyproject.toml  README.md  .gitignore
  src/netview/
    __init__.py                     __version__ = "0.1.0"
    bootstrap.py                    composition root (build_container, create_application)
    domain/
      keys.py  device.py  naming.py  nickname.py  watch.py
      samples.py  events.py  inspection.py  errors.py
    application/
      ports/  repositories.py  uow.py  clock.py  event_bus.py  metrics.py  network.py  vendor.py  plugin_admin.py
      capabilities.py
      plugins/  manifest.py  jobs.py  ui.py  context.py  base.py  registry.py  core_facade.py
      usecases/  sightings.py  identity.py  nicknames.py  watches.py  scan.py  inspection.py
      queries/  read_models.py  state.py
      services.py                   AppServices (what presentation sees)
    infrastructure/
      settings.py  clock.py  event_bus.py  metrics.py  scheduler.py  vendor.py
      net/  common.py  windows.py  linux.py  tools.py
      db/  engine.py  models.py  repositories.py  uow.py  migrate.py
           alembic_env/env.py  alembic_env/script.py.mako
           core_versions/0001_core.py
      plugins/  discovery.py  validation.py  context.py  host.py
      lanmon_import.py
    presentation/
      api/  app.py  security.py  deps.py  schemas.py  errors.py
            routers/  state.py  devices.py  watches.py  scan.py  inspections.py  events.py  plugins.py  stream.py
      web/static/  index.html  css/app.css
                   js/  main.js  api.js  slots.js  util.js  table-model.js
                        pages/  dashboard.js  devices.js  plugins.js
      cli.py
    sdk/  __init__.py  testing/  __init__.py  fakes.py  contract.py
    plugins/builtin/lan_discovery/  __init__.py  plugin.py  settings.py  routes.py  static/ui.js
  tests/
    unit/domain/  unit/application/  unit/infrastructure/
    integration/db/  integration/api/  integration/plugins/
    fixtures/net/  fixtures/lanmon/
    js/  table-model.test.mjs
```

---

### Task 1: Project scaffold, tooling and architecture contracts

**Files:**
- Create:
  - `pyproject.toml`, `.gitignore`, `README.md`
  - `src/netview/__init__.py`
  - empty `__init__.py` in every package listed in the file structure
  - `tests/test_smoke.py`
- Already present: `docs/superpowers/specs/2026-11-10-netview-design.md` (committed in this task).

**Interfaces:**
- Produces: `netview.__version__ == "0.1.0"`; console script `netview = "netview.presentation.cli:app"`; entry-point group `netview.plugins` with `lan_discovery = "netview.plugins.builtin.lan_discovery.plugin:LanDiscoveryPlugin"`. The target module is created in task 12; until then the entry point is simply not loadable, which the loader tolerates (task 8).

- [ ] **Step 1: Write `pyproject.toml`**

  Use hatchling with `packages = ["src/netview"]`.
  - **Dependencies:**
    - `fastapi>=0.115`, `uvicorn[standard]>=0.30`
    - `pydantic>=2.7`, `pydantic-settings>=2.4`
    - `sqlalchemy>=2.0.30`, `alembic>=1.13`
    - `typer>=0.12`, `platformdirs>=4`, `packaging>=24`, `swagger-ui-bundle>=1.1`
  - **Dev group:** `pytest>=8`, `pytest-cov`, `httpx>=0.27`, `ruff>=0.6`, `mypy>=1.11`, `import-linter>=2.1`.
  - **Tool settings:**
    - `[tool.ruff]` with `target-version = "py311"` and `line-length = 110`; lint `select = ["E","F","I","UP","B","SIM","RUF"]`.
    - `[tool.mypy]` with `python_version = "3.11"` and `strict = true` for `netview.domain.*`, `netview.application.*` and `netview.sdk.*`; `ignore_missing_imports = true`.
    - `[tool.pytest.ini_options]` with `testpaths = ["tests"]`.
  - Make sure hatch includes `src/netview/presentation/web/static/**`, `src/netview/plugins/builtin/*/static/**` and `src/netview/infrastructure/db/**/*.mako` in the wheel.

- [ ] **Step 2: Write the import-linter contracts in `pyproject.toml`**

  Set `[tool.importlinter]` with `root_package = "netview"` and `include_external_packages = true`. Contracts (all `type = "forbidden"` except the last):
  1. **Domain is pure:** `netview.domain` must not import `netview.application`, `netview.infrastructure`, `netview.presentation`, `netview.sdk`, `netview.plugins`, `netview.bootstrap`, `sqlalchemy`, `fastapi`, `pydantic`, `starlette` or `alembic`.
  2. **Application has no adapters:** `netview.application` must not import `netview.infrastructure`, `netview.presentation`, `netview.plugins`, `netview.bootstrap`, `sqlalchemy`, `fastapi`, `starlette` or `alembic`.
  3. **Infrastructure doesn't know the web layer:** `netview.infrastructure` must not import `netview.presentation`, `netview.plugins` or `netview.bootstrap`.
  4. **Presentation uses application only:** `netview.presentation` must not import `netview.infrastructure`, `netview.plugins` or `netview.bootstrap`. The one exception is `netview.presentation.cli`, which is the process entry point and may import `netview.bootstrap`; list it under `ignore_imports = ["netview.presentation.cli -> netview.bootstrap"]`.
  5. **The SDK is a facade:** `netview.sdk` must not import `netview.infrastructure`, `netview.presentation`, `netview.plugins` or `netview.bootstrap`.
  6. **Plugins use the SDK only:** `netview.plugins` must not import `netview.domain`, `netview.application`, `netview.infrastructure`, `netview.presentation` or `netview.bootstrap`, with `allow_indirect_imports = true` (indirect chains through `netview.sdk` are fine).
  An independence contract between built-in plugins is added in plan 2, once a second plugin exists. import-linter rejects an independence contract with a single module.

- [ ] **Step 3: Write `tests/test_smoke.py`**

  ```python
  def test_version():
      import netview

      assert netview.__version__ == "0.1.0"
  ```

- [ ] **Step 4: Create the environment and run every check**

  Run, from `netview/`:
  ```bash
  uv sync
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
  Expected: 1 passed, ruff clean, import-linter "Contracts: 6 kept, 0 broken".

- [ ] **Step 5: Commit** (scaffold plus the spec), then also add this plan file.

---

### Task 2: Domain model

**Files:**
- Create: `src/netview/domain/{keys,device,naming,nickname,watch,samples,events,inspection,errors}.py`
- Test: `tests/unit/domain/test_keys.py`, `test_device.py`, `test_naming.py`, `test_nickname.py`, `test_watch.py`

**Interfaces (produces):**
- **`keys.py`**
  - `SELF_KEY = "self"`.
  - `norm_mac(raw: str) -> str | None`: port of LM `norm_mac`, so broadcast, all-zero and `01:00:5e…` multicast addresses give `None`.
  - `key_for(ip: str, mac: str | None, is_self: bool) -> str`.
  - `is_private_mac(mac: str) -> bool`: tests the locally-administered bit.
- **`device.py`**
  - `class DeviceStatus(StrEnum)`: `ONLINE="online"`, `QUIET="quiet"`, `OFFLINE="offline"`.
  - `@dataclass class Device` with fields `key: str`, `ip: str`, `mac: str | None`, `vendor: str`, `first_seen_ms: int`, `last_seen_ms: int`, `status: DeviceStatus`, `rtt_ms: float | None = None`, `ttl: int | None = None`, `is_self: bool = False`, `missed: int = 0`, `is_new: bool = False`.
- **`naming.py`**
  - `@dataclass(frozen=True)` classes:
    - `NameClaim(key: str, name: str, source: str, rank: float, checked_ms: int)`
    - `TypeClaim(key: str, type: str, reason: str, source: str)`
    - `Hint(key: str, text: str, source: str)`
  - `NAME_RANKS: Mapping[str, float] = {"hostname": 9, "UPnP": 6, "AirPlay": 5, "NetBIOS": 4, "DHCP": 3.5, "mDNS": 3, "RDP certificate": 2, "DNS": 1}`.
  - `best_claim(claims: Iterable[NameClaim]) -> NameClaim | None`: highest `rank`; on a tie, the newest `checked_ms`; empty names are ignored.
  - `display_name(nickname: str | None, best: NameClaim | None, watch_label: str | None) -> str`.
- **`nickname.py`**
  - `MAX_NICKNAME_LEN = 60`.
  - `normalize_nickname(raw: str | None) -> str | None`: trims; `""` → `None`; longer than 60 raises `ValidationError`.
  - `@dataclass(frozen=True) NicknameChange(key: str, old: str, new: str, by: str, t_ms: int)`. `old` and `new` use `""` for "none"; `by` is free text.
- **`watch.py`**
  - `@dataclass(frozen=True) Watch(ip: str, ports: tuple[int, ...] = (), label: str = "")`.
  - `parse_watch_spec(spec: str) -> Watch`: format `IP[:P1,P2][=LABEL]`; port of LM `parse_watch`. Raises `ValidationError` on a bad IP or a port outside 1–65535.
  - `Watch.spec() -> str`: the exact inverse of the parser.
- **`samples.py`** (all `@dataclass(frozen=True)`):
  - `Sighting(ip: str, mac: str | None, rtt_ms: float | None, ttl: int | None, seen_ms: int)`
  - `LatencySample(series: str, t_ms: int, rtt_ms: float | None)`
  - `TrafficReading(ip: str, t_ms: int, down_bytes: int, up_bytes: int, extra: Mapping[str, Any])`
  - `Flow(device_ip: str, remote: str, port: int, proto: str, bytes: int, t_ms: int, dns_name: str | None)`
- **`events.py`**
  - `class EventKind(StrEnum)`: `NEW`, `MOVED`, `ONLINE`, `OFFLINE`, `CONFLICT`, `NAME`, `NICKNAME`, `TYPE`, `WATCH`, `PLUGIN` (values are the lower-case names).
  - `@dataclass(frozen=True) DomainEvent(kind: EventKind, text: str, t_ms: int, ip: str | None = None, key: str | None = None)`.
- **`inspection.py`**
  - `@dataclass(frozen=True) ReportSection(plugin_id: str, id: str, title: str, data: Mapping[str, Any], error: str | None = None)`.
  - `@dataclass InspectionReport(ip: str, ports_spec: str, started_ms: int, finished_ms: int, sections: list[ReportSection])`.
- **`errors.py`**
  - `class NetviewError(Exception)`, with subclasses `ValidationError`, `NotFoundError` and `CapabilityUnavailableError`.
  - `CapabilityUnavailableError(capability: str)` has a `.capability` attribute, and `str()` is `"no enabled plugin provides <capability>"`.

- [ ] **Step 1: Write the failing tests**

  These are the key assertions; write one test function per bullet.
  - **Keys:**
    - `norm_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"`
    - `norm_mac("a:b:c:d:e:f") == "0a:0b:0c:0d:0e:0f"`
    - `norm_mac("ff:ff:ff:ff:ff:ff") is None`
    - `norm_mac("01:00:5e:00:00:fb") is None`
    - `key_for("192.168.1.5", None, False) == "ip:192.168.1.5"`
    - `key_for("192.168.1.95", None, True) == "self"`
    - `is_private_mac("02:09:f4:2b:ab:36") is True`
    - `is_private_mac("34:5e:08:b2:ae:f4") is False`
  - **Naming:**
    - `best_claim` picks UPnP (6) over DHCP (3.5) whatever the order.
    - On equal rank it picks the newer `checked_ms`.
    - It ignores `name=""`.
    - `display_name("Roku TV (Bedroom)", claim, "x") == "Roku TV (Bedroom)"`
    - `display_name(None, None, "R720 iDRAC") == "R720 iDRAC"`
    - `display_name(None, None, None) == ""`
  - **Nickname:**
    - `normalize_nickname("  Jessi's Kindle ") == "Jessi's Kindle"`
    - `normalize_nickname("") is None`
    - `normalize_nickname("Café <b>") == "Café <b>"` (stored exactly; escaping is the UI's job)
    - `normalize_nickname("x"*61)` raises `ValidationError`
  - **Watch:**
    - `parse_watch_spec("192.168.1.128:443,22=R720 iDRAC") == Watch("192.168.1.128", (443, 22), "R720 iDRAC")`
    - `.spec()` round-trips.
    - `parse_watch_spec("10.0.0.1:70000")` raises `ValidationError`.

- [ ] **Step 2: Run the tests and check they fail**

  Run `uv run pytest tests/unit/domain -q`. Expected: errors on import.

- [ ] **Step 3: Implement the modules with the exact signatures above**

  The modules use stdlib only (`dataclasses`, `enum.StrEnum`, `ipaddress`, `re`).

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest tests/unit/domain -q
  ```
  ```bash
  uv run mypy src/netview/domain
  ```
  ```bash
  uv run lint-imports
  ```
  Expected: all pass, mypy clean.

- [ ] **Step 5: Commit**

---

### Task 3: Application ports, capability contracts, plugin contracts and in-memory fakes

**Files:**
- Create:
  - `src/netview/application/ports/*.py`
  - `src/netview/application/capabilities.py`
  - `src/netview/application/plugins/{manifest,jobs,ui,context,base,registry}.py`
  - `src/netview/sdk/testing/fakes.py`
- Test: `tests/unit/application/test_registry.py`, `tests/unit/application/test_fakes_uow.py`

**Interfaces (produces).** All ports are `typing.Protocol`.

- **`ports/repositories.py`**
  - **`DeviceRepository`:**
    - `get(key: str) -> Device | None`
    - `get_by_ip(ip: str) -> Device | None`
    - `list() -> list[Device]`
    - `add(device: Device) -> None`
    - `save(device: Device) -> None`
    - `remove(key: str) -> None`
  - **`IdentityRepository`:**
    - `claims(key: str) -> list[NameClaim]`
    - `all_claims() -> dict[str, list[NameClaim]]`
    - `upsert_claim(c: NameClaim) -> None`, unique on `(key, source)`
    - `types(key: str) -> list[TypeClaim]`
    - `upsert_type(t: TypeClaim) -> None`, unique on `(key, source)`
    - `hints(key: str) -> list[Hint]`
    - `replace_hints(key: str, source: str, hints: list[Hint]) -> None`
    - `rekey(old: str, new: str) -> None`
  - **`NicknameRepository`:**
    - `get(key: str) -> str | None`
    - `all() -> dict[str, str]`
    - `set(key: str, value: str | None) -> None`
    - `add_history(c: NicknameChange) -> None`
    - `history(key: str | None = None, limit: int = 500) -> list[NicknameChange]`
    - `has_history(c: NicknameChange) -> bool`
    - `rekey(old: str, new: str) -> None`
  - **`WatchRepository`:**
    - `list() -> list[Watch]`
    - `add(w: Watch) -> None`, which replaces on the same IP
    - `remove(ip: str) -> bool`
  - **`EventRepository`:**
    - `add(e: DomainEvent) -> None`
    - `recent(limit: int = 300) -> list[DomainEvent]`, newest first
  - **`InspectionRepository`:**
    - `save(r: InspectionReport) -> None`
    - `latest(ip: str) -> InspectionReport | None`
  - **`PluginStateRepository`:**
    - `get(plugin_id: str) -> PluginState | None`
    - `save(s: PluginState) -> None`
    - `PluginState` is a dataclass `(plugin_id: str, enabled: bool, settings: dict[str, Any], installed_version: str | None)` defined in this module.
- **`ports/uow.py`**
  - `UnitOfWork` Protocol with:
    - attributes `devices`, `identity`, `nicknames`, `watches`, `events`, `inspections`, `plugin_state`;
    - `commit() -> None`, `rollback() -> None`;
    - `__enter__ / __exit__`, where exit rolls back if nothing was committed.
  - `UnitOfWorkFactory = Callable[[], UnitOfWork]`.
- **`ports/clock.py`:** `Clock.now_ms() -> int`.
- **`ports/event_bus.py`:**
  - `EventBus.publish(e: DomainEvent) -> None`
  - `EventBus.subscribe(handler: Callable[[DomainEvent], None]) -> Callable[[], None]`, which returns an unsubscribe function
- **`ports/metrics.py`:**
  - `MetricsStore.append(series: str, t_ms: int, value: float | None) -> None`
  - `MetricsStore.series(name: str, limit: int = 120) -> list[tuple[int, float | None]]`
  - `MetricsStore.names(prefix: str = "") -> list[str]`
- **`ports/network.py`:**
  - Dataclasses `PingResult(rtt_ms: float, ttl: int)` and `TcpResult(state: Literal["open", "closed", "filtered"], ms: float | None)`.
  - `NetworkTools` methods:
    - `ping(ip: str, timeout_ms: int = 800) -> PingResult | None`
    - `arp_table() -> dict[str, str]`
    - `tcp_probe(ip: str, port: int, timeout_s: float = 1.0) -> TcpResult`
    - `dns_query(server: str, name: str, timeout_s: float = 2.0) -> float | None`
    - `local_ip() -> str`
    - `default_gateway(local_ip: str) -> str | None`
    - `hostname() -> str`
- **`ports/vendor.py`:** `VendorLookup.vendor(mac: str | None) -> str`, which returns `""` when unknown and `"Random or local MAC"` for private MACs.
- **`ports/plugin_admin.py`:**
  - `PluginInfo` dataclass with fields:
    - `id`, `name`, `version`, `description`
    - `state: Literal["active", "disabled", "failed"]`, `error: str | None`
    - `capabilities: list[str]`, `permissions: list[str]`
    - `enabled: bool`, `restart_required: bool`
    - `settings: dict[str, Any]`, `settings_schema: dict[str, Any] | None`
    - `ui_module: str | None`, which is the URL path of the module, for example `/plugins/lan_discovery/static/ui.js`
  - `PluginAdmin` methods:
    - `list() -> list[PluginInfo]`
    - `get(plugin_id: str) -> PluginInfo`
    - `update_settings(plugin_id: str, values: dict[str, Any]) -> PluginInfo`
    - `set_enabled(plugin_id: str, enabled: bool) -> PluginInfo`
- **`capabilities.py`**
  - `class Capability(StrEnum)`: `DISCOVERY`, `IDENTITY`, `HEALTH`, `TRAFFIC`, `DESTINATIONS`, `INSPECTION`, `LOCAL_HOST`, `API`, `WEB_UI`, `STORAGE`, `JOBS` (values are the lower-case names).
  - Provider Protocols:
    - `DiscoveryProvider.discover(subnet: IPv4Network) -> Iterable[Sighting]`
    - `IdentityProvider.identify(device: DeviceView) -> Iterable[NameClaim | TypeClaim | Hint]`, plus attribute `recheck_after_s: float`
    - `HealthProvider.probe() -> Iterable[LatencySample]`
    - `TrafficProvider.read() -> Iterable[TrafficReading]`
    - `DestinationsProvider.read() -> Iterable[Flow]`
    - `InspectionProvider.inspect(ip: str, ports_spec: str) -> Iterable[ReportSection]`
    - `LocalHostProvider.snapshot() -> Mapping[str, Any]`
  - `DeviceView` is the read model defined in task 5 (`queries/read_models.py`). Import it under `TYPE_CHECKING`.
- **`plugins/manifest.py`**
  - `class Permission(StrEnum)`: `DEVICES_READ="devices:read"`, `NAMES_WRITE="names:write"`, `TYPES_WRITE="types:write"`, `TRAFFIC_WRITE="traffic:write"`, `STORAGE_OWN="storage:own"`, `API="api"`, `UI="ui"`, `NETWORK_PROBE="network:probe"`.
  - `@dataclass(frozen=True) PluginManifest(id: str, name: str, version: str, description: str, sdk_version: str, capabilities: frozenset[Capability], permissions: frozenset[Permission])`.
- **`plugins/jobs.py`**
  - `@dataclass(frozen=True) JobSpec(name: str, interval_s: float, run: Callable[[], object], timeout_s: float = 60.0, initial_delay_s: float = 0.0)`. `run` may be sync or async.
  - `@dataclass JobStatus(owner: str, name: str, last_run_ms: int | None, last_ok: bool | None, last_error: str | None, consecutive_failures: int, next_run_ms: int | None, running: bool)`.
  - `Scheduler` Protocol:
    - `add(owner: str, spec: JobSpec) -> None`
    - `remove_owner(owner: str) -> None`
    - `run_now(owner: str, name: str) -> None`
    - `status() -> list[JobStatus]`
- **`plugins/ui.py`:**
  - `@dataclass(frozen=True) UiContribution(static_dir: Path, module: str = "ui.js")`.
  - `@dataclass(frozen=True) StorageSpec(metadata: Any, versions_dir: Path)`.
- **`plugins/context.py`**
  - `PluginUnitOfWork` Protocol:
    - `session: Any` (a SQLAlchemy `Session` at runtime)
    - `commit() -> None`
    - context-manager methods
  - `PluginContext` Protocol attributes:
    - `plugin_id: str`, `settings: Any`, `log: logging.Logger`
    - `clock: Clock`, `net: NetworkTools`, `vendors: VendorLookup`, `metrics: MetricsStore`
    - `core: CoreFacade`
  - `PluginContext` methods:
    - `unit_of_work() -> PluginUnitOfWork`
    - `subscribe(handler: Callable[[DomainEvent], None]) -> Callable[[], None]`
- **`plugins/base.py`**
  - `class Plugin(ABC)` with:
    - `manifest: ClassVar[PluginManifest]`
    - `settings_model: ClassVar[type[Any] | None] = None` (a pydantic `BaseModel` subclass)
  - Abstract method: `setup(self, ctx: PluginContext) -> None`.
  - Methods with defaults:
    - `shutdown() -> None`
    - `providers() -> Mapping[Capability, object]`, default `{}`
    - `jobs() -> list[JobSpec]`, default `[]`
    - `router() -> Any | None` (a FastAPI `APIRouter`)
    - `ui() -> UiContribution | None`
    - `storage() -> StorageSpec | None`
    - `on_settings_changed(settings: Any) -> None`, which by default stores the new settings in `self.settings`
- **`plugins/registry.py`:** `CapabilityRegistry` with:
  - `register(plugin_id: str, capability: Capability, provider: object) -> None`
  - `providers(capability: Capability) -> list[tuple[str, object]]`
  - `require(capability: Capability) -> list[tuple[str, object]]`, which raises `CapabilityUnavailableError` when the list is empty
  - `unregister_plugin(plugin_id: str) -> None`
- **`sdk/testing/fakes.py`** (in-memory implementations used by every unit test and by plugin authors):
  - `InMemoryUnitOfWork` and `InMemoryUnitOfWorkFactory`. The factory shares one store, and `commit` copies staged changes in, so uncommitted work is discarded.
  - `FakeClock(start_ms: int = 1_800_000_000_000)` with `advance(ms: int)`.
  - `RecordingEventBus`, which keeps `.published: list[DomainEvent]`.
  - `InMemoryMetrics`.
  - `FakeNetworkTools(replies: dict[str, PingResult], arp: dict[str, str], local: str = "192.168.1.95", gateway: str | None = "192.168.1.1", fail: bool = False)`. With `fail=True`, ping returns `None` and `arp_table()` returns `{}`.
  - `FakeVendors(table: dict[str, str] | None = None)`.

- [ ] **Step 1: Write the failing tests**
  - **Registry:**
    - `require(Capability.DISCOVERY)` on an empty registry raises `CapabilityUnavailableError`, and its `str()` is `"no enabled plugin provides discovery"`.
    - After `register`, providers come back in registration order.
    - `unregister_plugin` drops only that plugin's providers.
  - **Fakes:**
    - An add without `commit` is not visible in a fresh UoW from the same factory.
    - After `commit` it is.

- [ ] **Step 2: Run the tests and check they fail**

  Run `uv run pytest tests/unit/application -q`. Expected: import errors.

- [ ] **Step 3: Implement the ports, contracts, registry and fakes as specified**

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest tests/unit -q
  ```
  ```bash
  uv run mypy src/netview/application src/netview/sdk
  ```
  ```bash
  uv run lint-imports
  ```

- [ ] **Step 5: Commit**

---

### Task 4: Core use cases

**Files:**
- Create: `src/netview/application/usecases/{sightings,identity,nicknames,watches,scan,inspection}.py`
- Test: `tests/unit/application/test_sightings.py`, `test_identity.py`, `test_nicknames.py`, `test_watches.py`, `test_scan.py`, `test_inspection.py`

**Interfaces:**
- **Consumes:** task 2 domain types, task 3 ports, registry and fakes.
- **Produces.** Each use case is a class with the constructor shown and a `__call__`. Every use case publishes its events to the `EventBus` and adds them to `uow.events`, **after** `commit`.
  - **`RecordSightings(uow: UnitOfWorkFactory, clock: Clock, vendors: VendorLookup, bus: EventBus, self_ip: Callable[[], str])`**
    - Called as `__call__(sightings: Sequence[Sighting], complete_sweep: bool = True) -> SweepSummary`.
    - `SweepSummary(seen: int, replied: int, quiet: int, went_offline: int, new: int, duration_ms: int)` is a dataclass in the same module.
    - Port the LM `Monitor.sweep` rules, lines 1263–1326:
      - The sighting whose ip equals `self_ip()` gets key `self` and `mac=None`.
      - Status is `online` if `rtt_ms` is set, else `quiet`.
      - **MAC learned later:** if `ip:<ip>` exists and a MAC is now known, the old record merges into the MAC key. First-seen is kept; nicknames and identity are re-keyed **unless the MAC key already has its own** nickname.
      - **Conflict event:** an IP now answering from a different MAC than its previous owner.
      - **Moved event:** a known key at a new IP.
      - **Online event:** a key whose previous status was offline.
      - **New event:** an unknown key, but not on the first call after construction (`self._first = True`, the LM `first` rule), and never for `self`.
      - When `complete_sweep` is true, every stored device not seen becomes `offline` with `rtt_ms=None`, `missed += 1`, and one offline event when the status changes.
      - Event texts copy LM's wording, using `display_name` for the label.
  - **`ClaimIdentity(uow: UnitOfWorkFactory, bus: EventBus)`**
    - Called as `__call__(items: Sequence[NameClaim | TypeClaim | Hint]) -> None`.
    - Upserts claims and types. Hints are replaced per `(key, source)`.
    - Emits a `NAME` event only when `best_claim` for a key changes its name, and a `TYPE` event when the newest type changes.
  - **`SetNickname(uow: UnitOfWorkFactory, clock: Clock, bus: EventBus)`**
    - Called as `__call__(key: str, raw: str | None, by: str = "user") -> str | None`.
    - Raises `NotFoundError` if no device with that key exists.
    - Normalises the value. If unchanged, it does nothing and returns early (no history, no event).
    - Otherwise it sets the nickname, appends a `NicknameChange`, emits a `NICKNAME` event and returns the new value.
  - **`AddWatch(uow, bus)`** is called as `__call__(spec: str) -> Watch`. **`RemoveWatch(uow, bus)`** is called as `__call__(ip: str) -> bool`.
  - **`RunScan(registry: CapabilityRegistry, record: RecordSightings, subnet: Callable[[], IPv4Network], log: logging.Logger)`**
    - Called as `__call__() -> SweepSummary`.
    - Calls `registry.require(DISCOVERY)`, then every provider in turn.
    - A provider that raises is logged and skipped. If **all** providers raised, it doesn't mark devices offline (`complete_sweep=False`).
    - Sightings for the same IP are merged: any `rtt_ms` wins, and any non-`None` MAC wins.
  - **`RunInspection(registry, uow: UnitOfWorkFactory, clock: Clock)`**
    - Called as `__call__(ip: str, ports_spec: str = "top") -> InspectionReport`.
    - `require(INSPECTION)`, then the sections from every provider, saved through `uow.inspections`.
    - A provider exception becomes a `ReportSection(plugin_id, id="error", title=plugin_id, data={}, error=str(exc))`.

- [ ] **Step 1: Write the failing tests**

  Use the fakes. Key cases:
  - **`test_first_sweep_emits_no_new_events`**, then **`test_second_sweep_new_device_emits_new`**.
  - **`test_quiet_when_arp_only`:** `Sighting(rtt_ms=None, mac=...)` gives status `quiet`.
  - **`test_unseen_goes_offline_once`:** two complete sweeps without the device give exactly one `OFFLINE` event.
  - **`test_incomplete_sweep_does_not_mark_offline`.**
  - **`test_mac_learned_later_merges_ip_key`** (Review focus 1):
    - Sweep 1 sees `192.168.1.74` with no MAC.
    - `SetNickname("ip:192.168.1.74", "Jessi's Kindle")`.
    - Sweep 2 sees the same IP with MAC `90:39:5f:00:00:01`.
    - Then: `devices.get("ip:192.168.1.74") is None`, `nicknames.get("90:39:5f:00:00:01") == "Jessi's Kindle"`, `first_seen_ms` is unchanged, and there is exactly one device for that IP.
  - **`test_mac_merge_keeps_existing_mac_nickname`:** if the MAC key already has its own nickname, the IP-key nickname is not copied over it.
  - **`test_self_ip_gets_self_key`.**
  - **`test_set_nickname_unchanged_is_noop`:** no history, no event.
  - **`test_set_nickname_unknown_key_raises_not_found`.**
  - **`test_set_nickname_stores_exact_text`** (Review focus 2): `"Café <b>"` round-trips exactly.
  - **`test_claim_identity_name_event_only_on_change`.**
  - **`test_run_scan_without_providers_raises_capability_unavailable`.**
  - **`test_run_scan_merges_two_providers`.**
  - **`test_run_scan_all_providers_fail_keeps_status`.**
  - **`test_run_inspection_collects_sections_and_errors`.**

- [ ] **Step 2: Run the tests and check they fail**

  Run `uv run pytest tests/unit/application -q`.

- [ ] **Step 3: Implement the use cases with the signatures above**

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest tests/unit -q
  ```
  ```bash
  uv run mypy src/netview/application
  ```
  ```bash
  uv run lint-imports
  ```

- [ ] **Step 5: Commit**

---

### Task 5: Read models, state query, core facade and AppServices

**Files:**
- Create:
  - `src/netview/application/queries/{read_models,state}.py`
  - `src/netview/application/plugins/core_facade.py`
  - `src/netview/application/services.py`
- Test: `tests/unit/application/test_state.py`, `test_core_facade.py`

**Interfaces (produces):**
- **`DeviceView`:** a frozen dataclass with fields:
  - `key`, `ip`, `mac`, `vendor`
  - `nickname: str | None`, `device_name: str`, `name_source: str`
  - `type: str`, `hints: list[str]`
  - `status: str`, `rtt_ms`, `ttl`
  - `first_seen_ms`, `last_seen_ms`
  - `is_new`, `is_self`, `watched: bool`
  - `display_name: str`
- **`NetworkState`:** `(host: HostInfo, devices: list[DeviceView], events: list[DomainEvent], watches: list[Watch], capabilities: list[str], jobs: list[JobStatus])`.
- **`HostInfo`:** `(hostname: str, ip: str, gateway: str | None, subnet: str, platform: str)`.
- **`GetNetworkState(uow, registry, scheduler, host: Callable[[], HostInfo])`**, called as `__call__() -> NetworkState`.
  - `device_name` and `name_source` come from `best_claim`.
  - `type` is the most recent `TypeClaim`.
  - `display_name` uses the domain rule.
  - Devices are sorted by IP numerically.
  - `capabilities` lists those with at least one provider.
- **`GetDevice(uow)`**, called as `__call__(key: str) -> DeviceView`, raises `NotFoundError` when the key is unknown.
- **`CoreFacade`** has **exactly** these public methods, and no nickname writer:
  - `devices() -> list[DeviceView]`
  - `device(key: str) -> DeviceView`
  - `watches() -> list[Watch]`
  - `record_sightings(s: Sequence[Sighting], complete_sweep: bool = False) -> SweepSummary`
  - `claim(items: Sequence[NameClaim | TypeClaim | Hint]) -> None`
  - `add_event(kind: EventKind, text: str, ip: str | None = None) -> None`
  - `run_scan() -> SweepSummary`

  Its constructor takes the use cases and queries.
- **`AppServices`:** a dataclass holding:
  - `state: GetNetworkState`, `device: GetDevice`
  - `set_nickname`, `add_watch`, `remove_watch`, `run_scan`, `run_inspection`
  - `events: Callable[[int], list[DomainEvent]]`, `latest_inspection: Callable[[str], InspectionReport | None]`
  - `plugins: PluginAdmin`, `bus: EventBus`, `scheduler: Scheduler`

  This is everything presentation may touch.

- [ ] **Step 1: Write the failing tests**
  - **`test_state_display_name_prefers_nickname`.**
  - **`test_state_sorts_by_ip_numeric`:** `.2` comes before `.10`.
  - **`test_state_marks_watched`.**
  - **`test_core_facade_has_no_nickname_writer`:**
    ```python
    public = {n for n in dir(CoreFacade) if not n.startswith("_")}
    assert public == {"devices", "device", "watches", "record_sightings", "claim", "add_event", "run_scan"}
    ```

- [ ] **Step 2: Run the tests and check they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest tests/unit -q
  ```
  ```bash
  uv run mypy src/netview/application
  ```
  ```bash
  uv run lint-imports
  ```

- [ ] **Step 5: Commit**

---

### Task 6: Infrastructure services: clock, event bus, metrics, scheduler, settings

**Files:**
- Create: `src/netview/infrastructure/{clock,event_bus,metrics,scheduler,settings}.py`
- Test: `tests/unit/infrastructure/test_scheduler.py`, `test_event_bus.py`, `test_metrics.py`, `test_settings.py`

**Interfaces (produces):**
- **`SystemClock`:** implements `Clock`.
- **`InMemoryEventBus`:**
  - Thread-safe.
  - A handler that raises is logged and does not stop the other handlers.
  - Also offers `async def stream(self) -> AsyncIterator[DomainEvent]` for SSE, as a per-subscriber `asyncio.Queue(maxsize=1000)` fed through `loop.call_soon_threadsafe`; a full queue drops the oldest event.
- **`RingMetricsStore(maxlen: int = 120)`:** implements `MetricsStore`, thread-safe.
- **`AsyncScheduler(clock: Clock, max_workers: int = 32)`:** implements `Scheduler`, plus `async start() -> None` and `async stop() -> None`.
  - Sync `run` callables execute in a `ThreadPoolExecutor(max_workers)`; async ones are awaited.
  - Each run is wrapped in `asyncio.wait_for(timeout_s)`.
  - A run never overlaps the same job's previous run: if it is still running, that tick is skipped.
  - **Failure and backoff:** a failure (exception or timeout) increments `consecutive_failures`. The next delay is:
    ```python
    delay = interval_s if failures < 3 else min(interval_s * 2 ** (failures - 2), max(interval_s, 300.0))
    ```
  - Success resets the failure count to 0.
  - `run_now` schedules an immediate run.
- **`AppSettings(BaseSettings)`:**
  - Configuration: `env_prefix="NETVIEW_"`, `env_nested_delimiter="__"`. Sources in order: init args > environment variables > TOML file (`TomlConfigSettingsSource` reading `config_file`).
  - **Fields:**
    - `config_file: Path | None = None`
    - `data_dir: Path = Path(platformdirs.user_data_dir("netview", appauthor=False))`
    - `bind: str = "127.0.0.1"`, `port: int = 8765`
    - `subnet: str | None = None`
    - `scan_interval_s: float = 30.0`, `fast_interval_s: float = 5.0`
    - `internet_target: str = "1.1.1.1"`, `dns_servers: list[str] = []`
    - `oui_file: Path | None = None`
    - `plugin_dirs: list[Path] = []`
    - `plugins: dict[str, dict[str, Any]] = {}`: first-run seeds, each optionally holding `enabled`
    - `database_url: str | None = None`
  - **Property `db_url`:** `database_url` or `f"sqlite:///{data_dir / 'netview.db'}"`.
  - **`load_settings(config_file: Path | None = None, **overrides) -> AppSettings`:** if `config_file` is None and `<data_dir>/netview.toml` exists, use it.

- [ ] **Step 1: Write the failing tests**

  The scheduler tests use short intervals (about 0.05 s) inside `asyncio.run`.
  - **`test_job_runs_repeatedly`.**
  - **`test_hanging_job_times_out_and_others_continue`** (Review focus 3):
    - A sync job sleeps 2 s with `timeout_s=0.1`.
    - A second job counts its runs.
    - After 0.5 s: the counter is 3 or more, and the hanging job's status shows `last_ok is False`, a `last_error` containing "timeout", and `running` true or false but never overlapping.
  - **`test_backoff_after_three_failures`:** a job that always raises with `interval_s=1`. Check the computed `next_run_ms` deltas using a `FakeClock`, or the exposed helper `next_delay(interval_s, failures) -> float`. Delays should be 1, 1, 2, 4, 8 … capped at 300.
  - **`test_remove_owner_stops_jobs`.**
  - **`test_bus_handler_exception_isolated`.**
  - **`test_metrics_ring_keeps_last_120`.**
  - **`test_settings_env_beats_toml`:** write a TOML file with `port = 9000`, set `NETVIEW_PORT=9100`, and expect 9100.
  - **`test_settings_default_db_url_in_data_dir`.**

- [ ] **Step 2: Run the tests and check they fail**

- [ ] **Step 3: Implement**

  Expose `next_delay` as a module-level function so the backoff rule is testable without timing.

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest tests/unit -q
  ```
  ```bash
  uv run lint-imports
  ```

- [ ] **Step 5: Commit**

---

### Task 7: OS network adapters and vendor lookup

**Files:**
- Create:
  - `src/netview/infrastructure/net/common.py`: shared regexes, `run(cmd, timeout)`, `tcp_probe`, `dns_query`, `local_ip`
  - `src/netview/infrastructure/net/windows.py`, `src/netview/infrastructure/net/linux.py`
  - `src/netview/infrastructure/net/tools.py`
  - `src/netview/infrastructure/vendor.py`
- Fixtures:
  - `tests/fixtures/net/win_ping_ok.txt`, `win_ping_unreachable.txt`, `win_ping_lt1ms.txt`
  - `win_arp.txt`, `win_route.txt`
  - `linux_ping_ok.txt`, `linux_ip_neigh.txt`, `linux_route.txt`
  - Capture the Windows ones from this laptop: `ping -n 1 -w 800 192.168.1.1`, `ping -n 1 -w 800 192.168.1.250` (no host), `ping -n 1 127.0.0.1`, `arp -a` and `route print -4 0.0.0.0`. Write the Linux ones by hand from the formats in LM.
- Test: `tests/unit/infrastructure/test_net_parsers.py`, `test_vendor.py`

**Interfaces (produces):**
- **Pure parsers** in `windows.py` and `linux.py`. These are the units under test; port the logic from LM lines 144–270.
  - `parse_ping(output: str) -> PingResult | None`: a `<1ms` reply gives `rtt_ms = 0.5`, matching LM's halving rule.
  - `parse_arp(output: str) -> dict[str, str]`.
  - `parse_default_gateway(output: str, local_ip: str) -> str | None`.
  - `ping_command(ip: str, timeout_ms: int) -> list[str]`.
- **`SystemNetworkTools(platform: str = sys.platform)`:** implements `NetworkTools` by picking the matching parser module.
  - Subprocesses use `CREATE_NO_WINDOW` on Windows and `stdin=DEVNULL`.
  - Any `OSError` or timeout gives `None` or `{}`, never an exception.
- **`OuiVendorLookup(oui_file: Path | None = None)`:**
  - Implements `VendorLookup`.
  - The `BUILTIN_OUI` table is copied from LM lines 102–126 exactly.
  - The optional file is an IEEE `oui.csv` or a Wireshark `manuf` file, ported from LM `load_oui`.
  - Private MAC → `"Random or local MAC"`.

- [ ] **Step 1: Capture the Windows fixtures and write the Linux fixtures**

- [ ] **Step 2: Write the failing tests**
  - **Windows ping:** `parse_ping(win_ping_ok)` returns a `PingResult` with `ttl > 0`.
  - **Unreachable:** `parse_ping(win_ping_unreachable) is None`.
  - **Under 1 ms:** `parse_ping(win_ping_lt1ms).rtt_ms == 0.5`.
  - **Windows ARP:** `parse_arp(win_arp)` contains `"192.168.1.1"` mapped to the normalised `74:24:9f:…` MAC, and no broadcast or multicast entries.
  - **Windows gateway:** `parse_default_gateway(win_route, "192.168.1.95") == "192.168.1.1"`.
  - **Linux:** the same three parsers on the Linux fixtures.
  - **Vendor:**
    - `OuiVendorLookup().vendor("34:5e:08:b2:ae:f4") == "Roku"`
    - `.vendor("02:09:f4:2b:ab:36") == "Random or local MAC"`
    - `.vendor(None) == ""`
  - **`test_tools_survive_missing_commands`** (Review focus 4): with `monkeypatch` making `subprocess.run` raise `FileNotFoundError`, `ping()` is `None`, `arp_table()` is `{}` and `default_gateway()` is `None`.

- [ ] **Step 3: Run the tests and check they fail**

- [ ] **Step 4: Implement**

- [ ] **Step 5: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest tests/unit/infrastructure -q
  ```
  ```bash
  uv run lint-imports
  ```

- [ ] **Step 6: Commit**

---

### Task 8: SQLite persistence and migrations

**Files:**
- Create:
  - `src/netview/infrastructure/db/{engine,models,repositories,uow,migrate}.py`
  - `src/netview/infrastructure/db/alembic_env/env.py`, `script.py.mako`
  - `src/netview/infrastructure/db/core_versions/0001_core.py`
- Test: `tests/integration/db/test_repositories.py`, `test_migrate.py`

**Interfaces (produces):**
- **`make_engine(url: str) -> Engine`:**
  - SQLite connections run `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` on connect.
  - `check_same_thread=False`.
  - Creates the parent folder of the database file.
- **`models.py`:** `class CoreBase(DeclarativeBase)` with tables:
  - `devices(key PK, ip, mac, vendor, first_seen_ms, last_seen_ms, status, rtt_ms, ttl, is_self, missed, is_new)`
  - `name_claims(key, source, name, rank, checked_ms, PK(key, source))`
  - `type_claims(key, source, type, reason, updated_ms, PK(key, source))`
  - `hints(id PK, key, source, text)`
  - `nicknames(key PK, value)`
  - `nickname_history(id PK, key, old, new, by TEXT, t_ms)`, where `by` is free text
  - `watches(ip PK, ports TEXT, label)`
  - `events(id PK, t_ms, kind, text, ip, key)`
  - `inspection_reports(id PK, ip, ports_spec, started_ms, finished_ms, sections_json)`
  - `plugin_state(plugin_id PK, enabled, settings_json, installed_version)`
- **`SqlUnitOfWork(session_factory)`:** implements `UnitOfWork` with SQL repositories (one class per port in `repositories.py`), and also exposes `.session`.
- **`migrate.py`:**
  - `upgrade_core(engine: Engine) -> None`
  - `upgrade_plugin(engine: Engine, plugin_id: str, versions_dir: Path) -> None`
  - Both run Alembic programmatically with `script_location` set to `alembic_env` and `version_locations` set to the versions directory.
  - The version table is `alembic_version` for the core and `alembic_version_<plugin_id>` for each plugin.
  - `env.py` reads `config.attributes["connection"]` and `config.attributes["version_table"]`, and has no autogenerate target.
  - **`0001_core.py`** creates all the core tables above with explicit `op.create_table` calls (no `metadata.create_all`).

- [ ] **Step 1: Write the failing tests**

  Each test uses a temporary SQLite file through `tmp_path`.
  - **`test_upgrade_core_creates_tables_and_is_idempotent`:** run it twice and check the `alembic_version` row.
  - **`test_device_roundtrip`.**
  - **`test_rekey_moves_nickname_and_claims`.**
  - **`test_uncommitted_changes_rolled_back`.**
  - **`test_nickname_history_free_text_by`:** stores `"claude: cleared auto-written nickname"`.
  - **`test_plugin_upgrade_uses_own_version_table`:** a test versions folder creates `demo_items`; afterwards `alembic_version_demo` exists and the core `alembic_version` is unchanged.
  - **Contract parity test:** run the task 4 use-case tests against `SqlUnitOfWork`. Parametrise one sightings test and one nickname test across both factories, so the SQL repositories match the fakes' behaviour.

- [ ] **Step 2: Run the tests and check they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest tests/integration/db tests/unit -q
  ```
  ```bash
  uv run lint-imports
  ```

- [ ] **Step 5: Commit**

---

### Task 9: Plugin host: discovery, validation, context, lifecycle and settings

**Files:**
- Create:
  - `src/netview/infrastructure/plugins/{discovery,validation,context,host}.py`
  - `src/netview/sdk/__init__.py`
  - `src/netview/sdk/testing/contract.py`
- Test: `tests/integration/plugins/test_host.py`, `test_validation.py`, using test plugins defined inside the test package as `tests/integration/plugins/sample_plugins/*.py`

**Interfaces:**
- **Consumes:** tasks 3, 5, 6 and 8.
- **Produces:**
  - **`netview.sdk`** re-exports:
    - **Contracts and SDK constant:** `SDK_VERSION = "1.0"`, `Plugin`, `PluginManifest`, `Permission`, `Capability`, `PluginContext`, `JobSpec`, `UiContribution`, `StorageSpec`, and every provider Protocol.
    - **Domain value types:** `Sighting`, `NameClaim`, `TypeClaim`, `Hint`, `LatencySample`, `TrafficReading`, `Flow`, `ReportSection`, `EventKind`, `DeviceView`, `PingResult`, `TcpResult`, `NAME_RANKS`.

    Set an explicit `__all__`.
  - **`discover_plugin_classes(group: str = "netview.plugins", extra_dirs: Sequence[Path] = ()) -> list[DiscoveredPlugin]`:**
    - `DiscoveredPlugin(source: str, cls: type[Plugin] | None, error: str | None)`.
    - A folder plugin is a subfolder holding `__init__.py` that defines `plugin_class`. It is imported with `importlib.util.spec_from_file_location` under the module name `netview_local_plugins.<folder>`.
    - An entry point that fails to import gives `cls=None` and an error; it never raises.
  - **`validate_manifest(m: PluginManifest, sdk_version: str, seen_ids: set[str]) -> list[str]`:**
    - The id must match the regex.
    - The SDK version must be satisfied by `packaging.specifiers.SpecifierSet(m.sdk_version)`.
    - The id must not be a duplicate.
    - Capabilities must be a subset of `Capability`.
  - **`validate_storage(plugin_id: str, metadata: Any) -> list[str]`:** every table name must start with `f"{plugin_id}_"`.
  - **`validate_providers(plugin: Plugin) -> list[str]`:**
    - Every key in `providers()` must be in `manifest.capabilities`.
    - `router()` returning a router requires `Capability.API`.
    - `ui()` requires `WEB_UI`; `storage()` requires `STORAGE`; `jobs()` being non-empty requires `JOBS`.
  - **`PluginHost(engine, uow: UnitOfWorkFactory, registry: CapabilityRegistry, scheduler: Scheduler, context_factory: Callable[[str, Any], PluginContext], seeds: dict[str, dict[str, Any]], discovered: list[DiscoveredPlugin])`:**
    - Implements `PluginAdmin`, plus:
      - `load_all() -> None`
      - `start_jobs() -> None`
      - `shutdown() -> None`
      - `routers() -> list[tuple[str, Any]]`
      - `ui_contributions() -> list[tuple[str, UiContribution]]`
    - **`load_all` lifecycle**, per §7.3 (validate, then state, settings, migrations, setup, registration). Each step is wrapped so a failure gives `state="failed"` with an error message and no partial registration:
      1. Run the validators above.
      2. Read the `PluginState` from the database. If there is none, create it from `seeds.get(id, {})`, where `enabled` defaults to True and the rest are settings.
      3. If the plugin is disabled, its state is `disabled`.
      4. Validate settings with `settings_model.model_validate(...)`. Invalid stored settings make the plugin `failed`, with the pydantic error text.
      5. If there is a `storage()` spec, run `upgrade_plugin` and store `installed_version`.
      6. Call `setup(ctx)`.
      7. Register its providers.
    - **`update_settings`:**
      - Validate first; a bad value raises `ValidationError` carrying pydantic's message.
      - Persist the new settings.
      - Call `on_settings_changed(new)`.
      - Replace the plugin's jobs with `scheduler.remove_owner(id)` followed by `add` for each spec in `plugin.jobs()`.
    - **`set_enabled`:** persists the flag and sets `restart_required = (enabled != (state == "active"))`. It never loads or unloads at runtime (§7.7).
    - **`settings_schema`** is `settings_model.model_json_schema()`.
  - **`DefaultPluginContext`:** implements `PluginContext`.
    - `unit_of_work()` yields a session from the shared engine and commits on `commit()`.
    - `log` is `logging.getLogger(f"netview.plugin.{id}")`.
  - **`netview.sdk.testing.contract.check_plugin(cls: type[Plugin]) -> None`:** asserts the plugin is valid: the manifest validates, defaults validate against `settings_model`, `setup` runs on a fake context, the providers match their capabilities, storage tables are prefixed, and the UI static folder and module exist.

- [ ] **Step 1: Write the sample plugins**

  In `tests/integration/plugins/sample_plugins/`:
  - **`good.py`:**
    - Manifest: id `good`.
    - Provides `DISCOVERY` and `JOBS`, plus an `API` router with `GET /ping`.
    - Storage: table `good_items`.
    - Settings model: `GoodSettings(level: int = 1)`.
  - **`bad_prefix.py`:** a table named `items`.
  - **`bad_sdk.py`:** `sdk_version=">=2"`.
  - **`crash_setup.py`:** `setup` raises `RuntimeError("boom")`.
  - **`undeclared.py`:** provides `TRAFFIC` without declaring it.

- [ ] **Step 2: Write the failing tests**
  - **`test_good_plugin_active_and_registered`:** state `active`, provider in the registry, table `good_items` exists, `alembic_version_good` exists.
  - **`test_invalid_plugins_marked_failed_with_reason`:** one parametrised test per bad plugin, checking state `failed` and that the error mentions `prefix`, `sdk`, `boom` or `undeclared` respectively.
  - **`test_failed_plugin_does_not_stop_others`.**
  - **`test_seed_used_only_on_first_run`:**
    - Seed `{"good": {"level": 5}}`.
    - Run `load_all`, then `update_settings("good", {"level": 7})`.
    - Build a new host with the same seed.
    - Expect `level == 7`.
  - **`test_update_settings_invalid_raises`:** `{"level": "x"}`.
  - **`test_update_settings_restarts_jobs`:** the scheduler fake records `remove_owner("good")` followed by `add`.
  - **`test_set_enabled_requires_restart`.**
  - **`test_broken_entry_point_reported`:** monkeypatch `importlib.metadata.entry_points` to return an entry point whose load raises; expect a `DiscoveredPlugin` with an error, and no exception.
  - **`test_check_plugin_contract_passes_for_good`.**

- [ ] **Step 3: Run the tests and check they fail**

- [ ] **Step 4: Implement**

- [ ] **Step 5: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest -q
  ```
  ```bash
  uv run mypy src/netview/sdk src/netview/application
  ```
  ```bash
  uv run lint-imports
  ```

- [ ] **Step 6: Commit**

---

### Task 10: Composition root and REST API

**Files:**
- Create:
  - `src/netview/bootstrap.py`
  - `src/netview/presentation/api/{app,security,deps,schemas,errors}.py`
  - `src/netview/presentation/api/routers/{state,devices,watches,scan,inspections,events,plugins,stream}.py`
- Test: `tests/integration/api/test_security.py`, `test_devices_api.py`, `test_plugins_api.py`, `test_capability_409.py`, `test_stream.py`

**Interfaces:**
- **Consumes:** everything so far.
- **Produces:**
  - **`bootstrap.build_container(settings: AppSettings) -> Container`:**
    - Builds the engine, `upgrade_core`, the UoW factory, `SystemClock`, `InMemoryEventBus`, `RingMetricsStore`, `SystemNetworkTools`, `OuiVendorLookup`, `CapabilityRegistry`, `AsyncScheduler`, the use cases, `CoreFacade` and `PluginHost`, then calls `load_all()`.
    - `Container` holds those plus `services: AppServices`.
    - **Subnet:** `settings.subnet` or `f"{local_ip}/24"`. Reject networks larger than 1024 hosts with `ValidationError`, the same rule as LM's `MAX_HOSTS`.
  - **`bootstrap.create_application(settings: AppSettings) -> FastAPI`:** builds the container, then calls `presentation.api.app.create_app(services, routers=host.routers(), ui=host.ui_contributions(), lifespan_hooks=...)`.
    - **On start:** the scheduler starts, the core job `("core", "scan")` is added with `interval_s=settings.scan_interval_s` running `services.run_scan` (a `CapabilityUnavailableError` is logged at most once per run), and `host.start_jobs()` runs.
    - **On stop:** the scheduler stops, then `host.shutdown()`.
  - **`create_app(services: AppServices, routers: list[tuple[str, APIRouter]], ui: list[tuple[str, UiContribution]], allowed_hosts: set[str], lifespan) -> FastAPI`:**
    - **Middleware** (`security.py`): Host check, then the `X-Netview: 1` check on unsafe methods, then CSP and `X-Content-Type-Options: nosniff` on every response (values in Global constraints).
    - **Core routers** under `/api/v1`, using pydantic response models in `schemas.py`:
      - `GET /state` → `NetworkStateOut`
      - `GET /devices` and `GET /devices/{key}`
      - `PUT /devices/{key}/nickname`, body `{"nickname": str | null}` → `DeviceOut`
      - `GET /watches`, `POST /watches` with body `{"spec": str}`, `DELETE /watches/{ip}`
      - `POST /scan` → `SweepSummaryOut`; it runs `run_scan` in a thread
      - `POST /inspections` with body `{"ip": str, "ports": "top"}`, and `GET /inspections/{ip}`
      - `GET /events?limit=300`
      - `GET /plugins` and `GET /plugins/{id}`
      - `PATCH /plugins/{id}` with body `{"enabled"?: bool, "settings"?: dict}`
      - `GET /stream`: SSE (`text/event-stream`), one `event: domain` with a JSON `DomainEvent` per bus event, and `: keep-alive` every 15 s
    - **Plugin routers** are mounted with `app.include_router(router, prefix=f"/api/v1/plugins/{id}")`.
    - **Plugin static files:** `app.mount(f"/plugins/{id}/static", StaticFiles(directory=contribution.static_dir))`.
    - **Core static files:** `/static` → `presentation/web/static`, and `GET /` serves `index.html`.
    - **Swagger UI:** `/docs` uses the `swagger_ui_bundle` assets mounted at `/static/swagger/`. Set `docs_url=None` and add a custom route using `get_swagger_ui_html` with local URLs.
    - **Error mapping** (`errors.py`): `NotFoundError` → 404, `ValidationError` → 422, `CapabilityUnavailableError` → 409. Each returns `{"error": str(exc)}`.

- [ ] **Step 1: Write the failing tests**

  The tests use `TestClient` against `create_app`, with `AppServices` built from the in-memory fakes. Add a test helper `tests/integration/api/conftest.py::services()` for this.
  - **`test_host_header_rejected`:** `Host: evil.example` gives 403.
  - **`test_localhost_with_port_allowed`:** `Host: localhost:8765` gives 200.
  - **`test_post_without_header_forbidden`:** 403.
  - **`test_csp_header_present`:** the response has the exact CSP string.
  - **`test_set_nickname_roundtrip`:** PUT, then GET `/devices/{key}`, returns `nickname == "Jessi's Kindle"`.
  - **`test_nickname_too_long_422`.**
  - **`test_unknown_device_404`.**
  - **`test_inspection_without_provider_409`:** body `{"error": "no enabled plugin provides inspection"}`.
  - **`test_scan_without_provider_409`.**
  - **`test_plugins_patch_settings_and_enable`:** uses a stub `PluginAdmin`.
  - **`test_plugin_router_mounted`:** a stub router with `GET /hello` answers at `/api/v1/plugins/demo/hello`.
  - **`test_stream_emits_domain_event`:** publish a `NICKNAME` event on the bus while reading the stream with `client.stream`, and assert one `event: domain` line arrives within 2 s.
  - **`test_docs_served_without_cdn`:** `/docs` HTML contains `/static/swagger/` and not `cdn.jsdelivr`.

- [ ] **Step 2: Run the tests and check they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest -q
  ```
  ```bash
  uv run lint-imports
  ```
  Contract 4 must stay kept: presentation never imports infrastructure.

- [ ] **Step 5: Commit**

---

### Task 11: Web shell, slots, Devices page and Plugins page

**Files:**
- Create:
  - `src/netview/presentation/web/static/index.html`, `css/app.css`
  - `src/netview/presentation/web/static/js/{main,api,slots,util,table-model}.js`
  - `src/netview/presentation/web/static/js/pages/{dashboard,devices,plugins}.js`
- Test: `tests/js/table-model.test.mjs` (run with `node --test tests/js`); manual browser check

**Interfaces (produces).** These are JS ES modules. There is no inline `<script>`, because of the CSP. `index.html` loads `/static/js/main.js` with `type="module"`.

- **`api.js`:**
  - `apiGet(path)`, `apiSend(method, path, body)`; `apiSend` always sets `X-Netview: 1` and JSON.
  - `openStream(onEvent)`: an `EventSource('/api/v1/stream')` with reconnect.
  - If the stream is down for more than 10 s, `/api/v1/state` is polled every 10 s instead.
- **`util.js`:** `esc(s)` (HTML escape of `& < > " '`), `fmtTime(ms)`, `fmtAgo(ms)`, `fmtBytes(n)`, `fmtRate(bps)`. Port these from LD.
- **`slots.js`:**
  - `createUiHost()` returns `{slot(name, spec), get(name) -> spec[], loadPlugins(pluginInfos)}`.
  - Valid slot names are `dashboard.tile`, `dashboard.card`, `devices.column`, `report.live-section`, `report.section`, `page`, `settings.section`. An unknown name throws.
  - **`loadPlugins`:**
    - Calls `import(info.ui_module)` for each active plugin, then `mod.default(uiApi)`, where `uiApi = {slot, apiBase: '/api/v1/plugins/' + id, apiGet, apiSend, util, pluginId: id}`.
    - Any throw is caught, logged with `console.error`, and recorded in `host.errors[id]`; the page shows those in the plugin's slot area.
- **`table-model.js`.** Pure functions with no DOM access, ported from LD's `DEV_COLS`, `visibleCols`, `groupKeyFn` and `NAME_PAIR` logic:
  - `visibleColumns(cols, hidden: Set, groupBy) -> cols`. Fixed columns are `status`, `ip` and `actions`, and are always shown except when grouped by.
  - `canHide(colId, hidden) -> {ok: boolean, reason: string}`:
    - Fixed columns give "always shown".
    - The last remaining one of `nickname`/`device_name` gives "needed while <other label> is hidden".
  - `groupKey(device, groupBy, ipRegex) -> string`. With `groupBy === 'ip'`, the key is the first capture group of `ipRegex` or `"(no match)"`. An invalid regex throws an `Error` whose message is shown in the UI.
  - `sortDevices(devices, sortKey, dir, cols) -> devices`. A column's `sortKey(device)` wins; the default is the IP compared numerically.
- **Pages:**
  - **Dashboard:** tile grid with core tiles (devices online / total, quiet, offline, last sweep) and every `dashboard.tile` from plugins.
  - **Devices:** a port of LD's devices card:
    - filter box, status buttons, sortable header
    - Group-by select (none / status / type / vendor / ip) and IP-regex input with error text
    - Columns popover with "Show all", the "Columns (N hidden)" label, and closing on Escape or an outside click
    - collapsible group rows
    - click-to-edit nickname (PUT); a 422 shows the error inline
    - core columns: status, nickname, device_name, type, ip, mac, vendor, first_seen, last_seen, actions
    - plugin `devices.column` specs appended, so hide, group and sort apply to them as well
    - `localStorage` keys `netview-hidden-cols`, `netview-group-by`, `netview-ip-regex` and `netview-theme`, each wrapped in `try/catch`
    - every value inserted with `esc()`
  - **Plugins:** one card per plugin with:
    - name, version, state badge (active / disabled / failed with error)
    - capabilities and permissions shown as chips
    - an enable toggle; when the API returns `restart_required` it shows "Restart to apply"
    - a settings form generated from `settings_schema` for `integer`, `number`, `string`, `boolean`, `enum` and `array of string`; Save sends a PATCH and shows any 422 message
- **Shell and theme:**
  - Navigation: Dashboard, Devices, Plugins, plus a nav entry for each plugin `page` slot. Hash routing (`#/devices`).
  - Theme tokens and the toggle are ported from LD (light/dark using `prefers-color-scheme` plus a manual override).
  - The header shows "This device <ip> (<hostname>)".

- [ ] **Step 1: Write the failing JS tests in `tests/js/table-model.test.mjs`**

  Use `node:test` and `node:assert`:
  - `visibleColumns` drops hidden columns and the column used for grouping, but still shows `status` when not grouping by status.
  - `canHide('nickname', new Set(['device_name']))` returns `{ok: false, reason: 'needed while Device name is hidden'}`.
  - `canHide('ip', new Set())` returns `ok === false` with reason `always shown`.
  - With `/^(\d+\.\d+\.\d+)\./`, `groupKey` gives `'192.168.1'`.
  - `groupKey` with regex `'('` throws.
  - `sortDevices` puts `192.168.1.2` before `192.168.1.10`.

- [ ] **Step 2: Run them and check they fail**

  Run `node --test tests/js`.

- [ ] **Step 3: Implement the static files**

- [ ] **Step 4: Run the JS tests and confirm they pass**

  Run `node --test tests/js`.

- [ ] **Step 5: Manual browser check**

  1. Add `.claude/launch.json` in `HomeLab` with configuration `netview`:
     - command `uv` with args `--directory "R:/source/claude projects/HomeLab/netview" run netview serve --data-dir "R:/source/claude projects/HomeLab/network/netview-dev"`
     - port 8766, so it doesn't clash with lan_monitor's 8765, and add `--port 8766` to the args
  2. Start it with `preview_start`. Check:
     - the page loads with no CSP errors in the console
     - the Plugins page lists `lan_discovery` (after task 12) or none
     - a nickname with `<b>` displays literally (Review focus 2)
     - the grouping and columns rules behave as in LD
  3. Take a screenshot.

- [ ] **Step 6: Commit**

---

### Task 12: Built-in plugin `lan_discovery`

**Files:**
- Create: `src/netview/plugins/builtin/lan_discovery/{__init__,plugin,settings,routes}.py`, `static/ui.js`
- Test: `tests/integration/plugins/test_lan_discovery.py`

**Interfaces:**
- **Consumes:** `netview.sdk` only.
- **Produces:** `LanDiscoveryPlugin(Plugin)` with the manifest:
  - id `lan_discovery`, name `LAN discovery`, version `0.1.0`, `sdk_version=">=1.0,<2"`
  - capabilities `{DISCOVERY, API, WEB_UI}`
  - permissions `{DEVICES_READ, NETWORK_PROBE, API, UI}`

  Settings model: `LanDiscoverySettings(ping_timeout_ms: int = 800 (100..5000), workers: int = 64 (1..256))`.

  **Provider `discover(subnet)`:**
  1. Ping every host in `subnet.hosts()` with `ctx.net.ping` in a `ThreadPoolExecutor(workers)`.
  2. Then read `ctx.net.arp_table()`.
  3. Yield one `Sighting` per IP that replied or has an ARP MAC, with `seen_ms=ctx.clock.now_ms()`.
  4. Remember the last summary: hosts tried, replied, ARP-only, duration.

  **Router:** `GET /summary` returns `{"hosts": int, "replied": int, "arp_only": int, "duration_ms": int, "last_ms": int | null}`.

  **UI (`static/ui.js`):** registers one `dashboard.tile`, "Last sweep", which shows replied/hosts and the duration, fetched from `${apiBase}/summary`.

- [ ] **Step 1: Write the failing tests**

  The tests use `netview.sdk.testing`:
  - **`test_contract`:** `check_plugin(LanDiscoveryPlugin)`.
  - **`test_discover_yields_replies_and_arp_only`:** `FakeNetworkTools` with one reply at `.1` and an ARP-only entry at `.74`, subnet `192.168.1.0/29`. Expect 2 sightings; `.74` has `rtt_ms is None`.
  - **`test_discover_with_no_network`** (Review focus 4): `FakeNetworkTools(fail=True)` gives 0 sightings and no exception.
  - **`test_summary_route`:** mount the router in a bare FastAPI app and GET `/summary` after one discover.
  - **`test_end_to_end_scan`:** `create_application` with `tmp_path` as `data_dir` and `SystemNetworkTools` monkeypatched to `FakeNetworkTools`. Then `POST /api/v1/scan` with the header returns 200, and `GET /api/v1/devices` lists the fake devices.

- [ ] **Step 2: Run the tests and check they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest -q
  ```
  ```bash
  uv run lint-imports
  ```
  The plugin may import only `netview.sdk`.

- [ ] **Step 5: Commit**

---

### Task 13: lan_store import and CLI

**Files:**
- Create: `src/netview/infrastructure/lanmon_import.py`, `src/netview/presentation/cli.py`
- Fixtures: `tests/fixtures/lanmon/store_basic.json`, `store_odd.json`. These are hand-written in the real format; do not copy the user's real file into the repository.
- Test: `tests/integration/test_lanmon_import.py`, `tests/integration/test_cli.py`

**Interfaces (produces):**
- **`LanmonImporter(uow: UnitOfWorkFactory, clock: Clock)`**, with `run(path: Path, prefer_source: bool = False, dry_run: bool = False) -> ImportReport`.
  - `ImportReport` dataclass fields: `devices_added`, `devices_updated`, `nicknames_added`, `history_added`, `watches_added: int`, and `conflicts: list[NicknameConflict(key, netview, source)]`.
  - **Reading:**
    - Opened read-only with `encoding="utf-8-sig"`.
    - `schema` must start with `"ketiv.network-tools/lan-store@"`, otherwise `ValidationError`.
    - Unknown keys are ignored.
  - **`known`** (key → `{ip, mac, first_seen, last_seen, name?, name_source?, type?}`):
    - Adds a missing device as `offline`. For an existing one, it only widens `first_seen_ms` (min) and `last_seen_ms` (max).
    - A name becomes a `NameClaim(rank=NAME_RANKS.get(source, 1), checked_ms=0)`.
    - A type becomes a `TypeClaim(source="lan_monitor", reason="imported")`.
  - **`labels`:**
    - A non-empty source value with an empty netview value is set, and a history entry `by="import: lan_monitor"` is added.
    - Equal values: nothing happens.
    - Both non-empty and different: a conflict, unless `prefer_source`, in which case the value is set with history `by="import: lan_monitor (prefer source)"`.
    - An empty source value never clears anything.
  - **`label_history`:** each entry becomes a `NicknameChange`, with `by` defaulting to `"lan_monitor"` and missing old or new values defaulting to `""`. Entries already present (`has_history`) are skipped, which makes re-runs idempotent.
  - **`watches`:** specs are parsed and added if not present.
  - **`dry_run`:** everything runs inside a unit of work that is rolled back.
  - **Never writes to `path`.**
- **`cli.py`** (Typer `app`):
  - **`serve`** options:
    - `--config PATH`, `--data-dir PATH`, `--bind`, `--port`, `--open`
    - Runs `uvicorn.run(create_application(settings), host=bind, port=port)`.
  - **`scan --once [--list] [--out PATH]`:**
    - Builds the container without a server and runs `run_scan` once.
    - Prints `"<n> devices (<replied> replied, <quiet> ARP only) in <s>s"`.
    - `--list` prints one line per device: `ip  mac  vendor  display_name`.
    - `--out` writes the `NetworkState` as JSON with `"schema": "netview/state@1"`.
  - **`import-lanmon PATH [--prefer-source] [--dry-run]`:** prints the report and lists every conflict as `key: netview="…" source="…"`. Exit code 0, or 1 when there were conflicts without `--prefer-source`.
  - **`plugins list`:** a table of id, state, version and error.
  - **`db upgrade`:** core plus every enabled plugin.

- [ ] **Step 1: Write the fixtures**
  - **`store_basic.json`:**
    - 2 known devices (one with `name_source: "DHCP"`), 2 labels and 2 history entries.
    - 1 watch `"192.168.1.128:443,22=R720 iDRAC"`.
  - **`store_odd.json`** (Review focus 5):
    - starts with a UTF-8 BOM
    - a history entry without `by`, and one with `by: "claude: cleared auto-written nickname"` and `new: ""`
    - a label `""`, a known entry without `name`, and an extra top-level key `"future": 1`

- [ ] **Step 2: Write the failing tests**
  - **`test_import_basic_counts`.**
  - **`test_import_is_idempotent`:** a second run adds 0 of everything.
  - **`test_import_never_overwrites_existing_nickname`:** `SetNickname` first, then the import reports 1 conflict and leaves the value unchanged.
  - **`test_prefer_source_overwrites_with_history`.**
  - **`test_import_odd_store`:** succeeds, the empty label sets nothing, the history `by` defaults to `"lan_monitor"`, and the free-text `by` is kept.
  - **`test_import_does_not_modify_source`:** byte-for-byte equality of the file before and after, plus an unchanged modification time.
  - **`test_import_rejects_unknown_schema`.**
  - **`test_dry_run_writes_nothing`.**
  - **`test_cli_import_exit_code_on_conflict`:** Typer `CliRunner`.
  - **`test_cli_scan_once_list`:** monkeypatch the network tools to the fake.

- [ ] **Step 3: Run the tests and check they fail**

- [ ] **Step 4: Implement**

- [ ] **Step 5: Run the checks and confirm they pass**

  Run:
  ```bash
  uv run pytest -q
  ```
  ```bash
  uv run lint-imports
  ```

- [ ] **Step 6: Commit**

---

### Task 14: Whole-system verification on the real network

**Files:**
- Modify:
  - `README.md`: install, run, CLI, plugin authoring quick-start (entry point, manifest, `check_plugin`), data directory
  - `.claude/launch.json` in HomeLab (from task 11)

- [ ] **Step 1: Run every check**

  Run:
  ```bash
  uv run pytest -q
  ```
  ```bash
  uv run ruff check .
  ```
  ```bash
  uv run mypy src
  ```
  ```bash
  uv run lint-imports
  ```
  ```bash
  node --test tests/js
  ```
  Expected: all green, and "Contracts: 6 kept, 0 broken".

- [ ] **Step 2: Do a dry-run import of the real store**

  Run against the user's real store into the dev data folder:
  ```bash
  uv run netview import-lanmon "R:/source/claude projects/HomeLab/network/lan_store.json" --dry-run --data-dir "R:/source/claude projects/HomeLab/network/netview-dev"
  ```
  Expected: 0 conflicts and 9 nicknames to add. Confirm `lan_store.json` is byte-identical afterwards, by comparing its SHA-256 before and after.

- [ ] **Step 3: Run the real import**

  Run the same command without `--dry-run`, then check `GET /api/v1/devices` shows "Roku TV (Bedroom)", "Jessi's Kindle" and the others.

- [ ] **Step 4: Run a live scan**

  Start the `netview` preview and click Scan. Devices should appear with vendors, and the "Last sweep" tile updates. Compare the device count with the running lan_monitor. They should match within ARP timing (±2).

- [ ] **Step 5: Run the failure drill** (Review focus 3)

  1. Temporarily set `lan_discovery`'s `ping_timeout_ms` to 100 in the Plugins page and confirm the jobs restart and the sweep still completes.
  2. Toggle the plugin off and confirm "Restart to apply".
  3. Restart and confirm `POST /api/v1/scan` returns 409 and the UI's Scan button is disabled.
  4. Re-enable it.

- [ ] **Step 6: Commit the README and finish**

---

## Self-review notes

**Spec coverage:**

| Spec section | Task |
|---|---|
| §5 layers | 1, 2–10 |
| §5.2 patterns | 3–6 |
| §5.3 scheduler | 6 |
| §6 domain and capabilities | 2, 3 |
| §6.2 fan-out and 409 | 4, 10 |
| §7.1 discovery | 9 |
| §7.2 manifest | 3, 9 |
| §7.3 lifecycle | 9 |
| §7.4 context | 3, 9 |
| §7.5 storage | 8, 9 |
| §7.6 UI slots | 11 |
| §7.7 settings precedence and live apply | 6, 9 |
| §8 data | 8 |
| §8.5 import | 13 |
| §9 API and CLI | 10, 13 |
| §11 quality | 1, 14 |

Deferred to plan 2, as stated in the header: the §10 parity items for `health`, `identity`, `local_host`, `inspection` and `starlink`, the charts, the report dialog, the watches UI (watches API is here), the connections card and Events list UI (events API is here), and `netview inspect`.
