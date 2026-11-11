# netview parity (plan 2): implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reach feature parity with the old LAN monitor (spec §10). That means five new built-in plugins (`health`, `identity`, `local_host`, `inspection`, `starlink`), the charts, the report dialog, the watches UI, the connections card, the Events list, `netview inspect`, and the items deferred from plan 1.

**Architecture:**
- **Core polls, plugins measure.** For each provider of a polled capability (health, identity, traffic), the plugin host schedules a job under the plugin's own id (`poll.health`, `poll.identity`, `poll.traffic`), so the scheduler's failure backoff applies per plugin.
  - Each job calls a core use case that turns the provider's output into domain changes: metrics, watch status, name claims, traffic rates and events.
  - Plugin-specific data with no core rules (this device's throughput, Wi-Fi, connections) is collected by the plugin's own jobs.
- **Shared probes live in the core.** mDNS, NetBIOS, SSDP/UPnP, reverse DNS, HTTP/TLS and the OS readers (byte counters, Wi-Fi, sockets) are new ports, implemented in infrastructure and handed to plugins on `ctx`. Built-in plugins never import each other; an import-linter independence contract enforces it.
- **UI follows ownership.**
  - The core adds shared chart helpers, a metrics cache, a card layout, and the Watches, Events and report-dialog shells.
  - Each plugin draws its own tiles, cards, columns and report sections through the existing slots.

**Tech stack:** as in plans 1 and 1b. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-11-10-netview-design.md`, especially §6, §7, §10 and §13. The Global Constraints of `2026-11-10-netview-core.md` and `2026-11-10-netview-ui-settings-themes.md` still apply.

**Porting source:** `R:\source\scripts\network-tools\scripts\lan_monitor.py` (*LM*, cited by line) and `R:\source\scripts\network-tools\templates\lan_dashboard.html` (*LD*). Both are read-only: never edit them. "Port LM 1332-1377" means: reproduce that behaviour and its user-visible text, adapted to the copy rules below.

## Global constraints (in addition to plans 1 and 1b)

- **SDK:**
  - `SDK_VERSION = "1.1"`. The new built-in manifests declare `sdk_version=">=1.1,<2"`; `lan_discovery` keeps `">=1.0,<2"`.
  - The changed provider signatures (`HealthProvider.probe`, `IdentityProvider.identify`) were never called in 1.0 and had no implementer. README notes the change.
- **Units:** rates are bits per second (`*_bps`); latency is milliseconds; times are epoch milliseconds (`*_ms`).
- **Metric series names** (the contract between core, plugins and UI):

  | Series | Value |
  |---|---|
  | `health.gateway`, `health.internet` | ping round-trip time in ms, or `null` when there was no reply |
  | `health.dns.<server ip>` | DNS answer time in ms, or `null` |
  | `health.device.<device key>` | ping round-trip time in ms, or `null` |
  | `local.down_bps`, `local.up_bps` | this device's throughput |
  | `traffic.down.<ip>`, `traffic.up.<ip>` | a device's rate from its traffic provider |

  Series under `health.gateway`, `health.internet`, `health.dns.` and `local.` keep **720** samples (1 h at 5 s, as LM's `SERIES_LEN`); every other series keeps **120** (10 min).
- **Limits ported from LM:**
  - Live device pings: at most **64** online devices (LM 1383).
  - Identity: runs every **60 s**, at most **128** devices per run, recheck after **1800 s** (LM 1650-1652).
  - Watch history: **60** checks (LM 1377).
  - Traffic entries are dropped after **600 s** unseen (LM 1461).
  - Connections lists: listening **60**, established **40**, trying **20** (LM 1524-1526).
  - Inspection: at most **64** open ports analysed by **16** workers; port-scan workers **256** with a **0.8 s** timeout, or **1024** workers and **0.5 s** above 5000 ports (LM 985-991).
- **Read-only probing:** the Starlink plugin only ever sends the empty `wifi_get_clients` request (field 3002, LM 1095), and UPnP descriptions are fetched only over `http` from the IP that announced them (LM 777-779).
- **Copy:**
  - Sentence case.
  - **No middle dots (`·`) anywhere** (spec §13.3). LD's `a · b · c` strings become commas, "and", or separate lines. Arrows (`→`, `↓`, `↑`) are fine.
  - "This device", never "This PC".
- **Charts follow the dataviz skill.** Read it before writing `chart.js` or any plugin card.
  - One y-axis per chart; 2 px round lines; markers r ≥ 4 with a 2 px surface ring.
  - Hairline solid gridlines (`--border`) and baseline (`--border-strong`); tick and label text in `--text-muted`, never a series colour.
  - Series colours `--series-1..4`, assigned in order, never cycled.
  - A legend (line keys) for ≥ 2 series and none for one. Direct end labels for ≤ 4 series, dropped entirely when any two would sit closer than 14 px (no nudging).
  - Crosshair plus one tooltip listing every series at that time, value first. The tooltip, legend and table are built with `textContent`, never `innerHTML`.
  - Keyboard: the chart is focusable, and ← / → move the crosshair.
  - A "Data table" `<details>` with the last 12 samples.
  - A jump of more than 2.5× the median sample spacing draws a gap, not a line (LD 576-579).
- **Escaping:** as in plan 1b. Anything that came from a device (UPnP names, HTTP titles, banners, certificate fields, mDNS TXT) is untrusted text.
- **Commits:** one per task on branch `feature/netview-parity`, conventional-commit style, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review focus

The five inputs most likely to bite a user that no feature test naturally covers. Each has a pinned test in the owning task.

1. **A gateway that is not a Starlink router, or answers garbage.**
   - **Cases:** HTTP 404, connection refused, `grpc-status: 12`, a truncated protobuf.
   - **Expected:** the `poll.traffic` job fails with a readable error and backs off. The Traffic column says "router data unavailable", and nothing else stops (Task C5).
2. **Byte counters going backwards** (the device reconnected, the router rebooted, the adapter was reset).
   - **Expected:** the rate is `null` for that sample, never negative or huge, and the next sample recovers (Tasks B1 and C3).
3. **Hostile or broken device answers.**
   - **Cases:** UPnP XML with `<!DOCTYPE`/`<!ENTITY`, an mDNS name-pointer loop, a 1 MB HTTP body, a binary banner, `<script>` in a page title or UPnP friendlyName.
   - **Expected:** XML is refused, the loop is caught, reads are capped, and the text shows literally in the report (Tasks B2 and D).
4. **No gateway or no network mid-run.**
   - **Expected:** health still writes `null` samples for `health.gateway`; a watch outside the subnet reads "No reply" with ARP "n/a (routed)"; nothing raises out of the job (Tasks B1 and C1).
5. **A watch removed or re-added between ticks.**
   - **Expected:**
     - a probe result for a removed watch is ignored, and its status disappears from `/state`;
     - re-adding it starts at "Checking";
     - the first result after "Checking" being *up* writes no event (LM 1372) (Task B1).

---

## File structure

```
src/netview/
  domain/
    watch.py            + WatchState, WatchProbe, WatchStatus, assess_watch, WATCH_LABELS
    samples.py          + counter_rate
    naming.py           + TypeClaim.checked_ms, TYPE_RANKS, best_type
    device_kind.py      NEW: vendor_type, os_hint (shared by identity and inspection)
    events.py           + EventKind.INSPECTED
  application/
    capabilities.py     HealthTargets; new HealthProvider / IdentityProvider signatures
    ports/probes.py     NEW: ServiceProbes + DnsRecord, NetbiosName, NetbiosInfo, SsdpEntry, CertInfo, HttpProbe
    ports/system.py     NEW: SystemInfo + WifiInfo, TcpSocket
    ports/metrics.py    + snapshot(), drop()
    usecases/health.py  NEW: PollHealth, WatchMonitor
    usecases/traffic.py NEW: TrafficLedger, PollTraffic, TrafficView, TrafficTotals
    usecases/identity_poll.py NEW: PollIdentity
    plugins/core_facade.py   + device_by_ip(), host()
    plugins/context.py       + probes, system
  infrastructure/
    net/probes.py       NEW: SystemServiceProbes (mDNS, NetBIOS, SSDP, UPnP, rDNS, HTTP/TLS, banner)
    net/dnswire.py      NEW: DNS message build/parse (shared by mDNS)
    net/system_info.py  NEW: SystemSystemInfo (+ windows/linux parsers in net/windows.py, net/linux.py)
    metrics.py          long-series capacity, snapshot, drop
    plugins/host.py     capability poll jobs
  presentation/
    api/routers/metrics.py  NEW: GET /api/v1/metrics
    api/routers/devices.py  + POST /devices/{ip}/probe
    cli.py                  + netview inspect
    web/static/js/chart.js        NEW
    web/static/js/metrics.js      NEW
    web/static/js/cards/watches.js NEW
    web/static/js/cards/events.js  NEW
    web/static/js/report/dialog.js NEW
  plugins/builtin/
    health/     __init__ plugin.py settings.py routes.py static/ui.js
    identity/   __init__ plugin.py settings.py
    local_host/ __init__ plugin.py settings.py routes.py connections.py static/ui.js
    inspection/ __init__ plugin.py settings.py ports.py analysis.py hints.py routes.py static/ui.js
    starlink/   __init__ plugin.py settings.py client.py protobuf.py storage.py routes.py
                versions/0001_starlink.py static/ui.js
tests/ ... one test module per new module, plus tests/fixtures/net/{win_netstat_e,win_netstat_ano,
       win_tasklist,win_netsh_wlan,linux_proc_net_dev,linux_ss,linux_nmcli}.txt and
       tests/fixtures/starlink/clients.bin
```

---

### Task A: Deferred items from plan 1

**Files:** `application/usecases/{forget,sightings,scan}.py`, `application/queries/state.py`, `application/ports/repositories.py`, `infrastructure/db/{engine,repositories}.py`, `infrastructure/plugins/context.py`, `sdk/testing/fakes.py`, `tests/fixtures/net/*`, and tests.

**Requirements** (one item per bullet of `docs/superpowers/deferred.md`):
1. **Self guard:** `ForgetDevice` raises `ValidationError("this device cannot be forgotten")` for `SELF_KEY`, and the API returns 422. **Test:** `DELETE /api/v1/devices/self` → 422, and the self row still exists.
2. **DDL fence:** the plugin authorizer also denies `SQLITE_CREATE_TABLE`, `SQLITE_CREATE_INDEX`, `SQLITE_DROP_TABLE`, `SQLITE_DROP_INDEX` and `SQLITE_ALTER_TABLE` on names outside the plugin's prefix (still allowing `sqlite_*` and `alembic_version_<id>`).
   - **Tests:** a plugin session `DROP TABLE nicknames` and `CREATE TABLE other_x(...)` both raise; `CREATE TABLE <id>_x(...)` works.
   - Check that plugin migrations still run: they use the core engine, not the fenced one. If they don't, run them on the core engine.
3. **Closed context:** `DefaultPluginContext` gets a `_closed` flag set in `close()`. After it, `subscribe()` returns a no-op unsubscriber and registers nothing. **Test:** subscribe after close; publishing an event does not call the handler.
4. **No-network guard in `RecordSightings`:** it raises `NoNetworkError` before touching the repository when `local_ip()` has no LAN address (reuse `has_lan_address`). `RunScan` keeps its early check. **Test:** `CoreFacade.record_sightings` with a loopback local IP raises, and the repository stays empty.
5. **Bulk loads:** add `IdentityRepository.all_types() -> dict[str, list[TypeClaim]]` and `all_hints() -> dict[str, list[Hint]]`. `build_device_view` accepts both, and `GetNetworkState` loads each once. **Test:** a counting fake shows one `all_types` call and zero `types(key)` calls for a 3-device state.
6. **Conflict de-duplication survives a restart:**
   - Remove the in-memory `_conflicts`. Before emitting a CONFLICT event, `RecordSightings` reads `uow.events.last(EventKind.CONFLICT, ip)` (a new repository method: newest event of that kind for that IP, or `None`) and skips when that event's `key` equals the new owner key.
   - CONFLICT events carry `key=<new owner key>`.
   - **Test:** two `RecordSightings` instances on the same database (a restart) give one CONFLICT event, not two.
7. **`updated_ms` filled in:** `TypeClaim` gets `checked_ms: int = 0` (domain). `upsert_type` stores it in `updated_ms`, and `types()` returns it. (Its use by `best_type` is in Task B1.) **Test:** a round trip keeps `checked_ms`.
8. **Scrub the captures:** in `tests/fixtures/net/*.txt`, replace every real MAC with the `02:00:5e:10:00:xx` range and every non-documentation IP with `192.0.2.x`/`198.51.100.x`, keeping the line format. Parser tests are updated to the new values and still pass. Then empty `docs/superpowers/deferred.md` down to its heading and the line "All items were handled in plan 2."

- [ ] **Step 1: Write the failing tests above; run them and see them fail**
- [ ] **Step 2: Implement**
- [ ] **Step 3: Run all checks**

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
  Expected: all pass, and `Contracts: 6 kept, 0 broken`.
- [ ] **Step 4: Commit** `fix(core): deferred review items from plan 1`

---

### Task B1: Domain rules, ports and core use cases for health, identity and traffic

**Files:** the domain and application files in the file structure, `sdk/__init__.py`, `sdk/testing/fakes.py`, `application/queries/{state,read_models}.py`, `application/usecases/{identity,inspection,forget}.py`, and tests under `tests/unit/domain/` and `tests/unit/application/`.

**Interfaces (produces):**
- **`domain/watch.py`**
  - `class WatchState(StrEnum)`: `PENDING`, `UP`, `DEGRADED`, `PRESENT`, `ABSENT`, `DOWN` (values are the lower-case names).
  - `WATCH_LABELS: Mapping[WatchState, str]`: pending "checking", up "up", degraded "partly up", present "on the network only", absent "not on the network", down "not replying".
  - `@dataclass(frozen=True) WatchProbe(ip: str, checked_ms: int, on_subnet: bool, l2: bool | None, mac: str | None, rtt_ms: float | None, ports: Mapping[int, Literal["open", "closed", "filtered"]])`.
  - `assess_watch(watch: Watch, probe: WatchProbe) -> tuple[WatchState, str]`: port LM 1342-1368 exactly, including the diagnosis texts.
  - `@dataclass(frozen=True) WatchStatus(ip: str, label: str, ports: tuple[int, ...], state: WatchState, since_ms: int | None, checked_ms: int | None, on_subnet: bool, l2: bool | None, mac: str | None, rtt_ms: float | None, port_state: Mapping[int, str], diagnosis: str, history: tuple[float, ...])`. History values are 1 (up), 0.5 (degraded) and 0 (anything else), keeping the last 60.
- **`domain/samples.py`:** `counter_rate(prev: tuple[int, int, int] | None, down_bytes: int, up_bytes: int, t_ms: int) -> tuple[float, float] | None`. `prev` is `(down, up, t_ms)`. It returns `(down_bps, up_bps)`, or `None` when `prev` is `None`, `dt <= 0`, or either counter went backwards (LM 1444-1448).
- **`domain/naming.py`:**
  - `TYPE_RANKS: Mapping[str, float] = {"inspection": 2.0, "vendor": 1.0}`; an unknown source ranks 1.5.
  - `best_type(claims: Iterable[TypeClaim]) -> TypeClaim | None`: highest rank, ties to the newest `checked_ms`, empty types ignored.
- **`domain/device_kind.py`:** `vendor_type(vendor: str, ttl: int | None, private_mac: bool) -> str` (port LM 830-844) and `os_hint(ttl: int | None) -> str` (port LM 403-410).
- **`domain/events.py`:** `EventKind.INSPECTED = "inspected"`.
- **`application/capabilities.py`:**
  - `@dataclass(frozen=True) HealthTargets(gateway: str | None, subnet: IPv4Network, devices: tuple[tuple[str, str], ...], watches: tuple[Watch, ...])`. `devices` holds `(key, ip)` of online, non-self devices, at most 64, in IP order.
  - `HealthProvider.probe(self, targets: HealthTargets) -> Iterable[LatencySample | WatchProbe]`.
  - `IdentityProvider`: `recheck_after_s: float` and `identify(self, devices: Sequence[DeviceView]) -> Iterable[NameClaim | TypeClaim | Hint]`.
  - `TrafficProvider.read(self) -> Iterable[TrafficReading]`, unchanged. `TrafficReading.extra` keys used by the core: `name`, `role`, `signal_dbm`, `down_link`, `up_link`, `assoc_s`, `ap`; any other keys are passed through.
  - `InspectionProvider.inspect(ip, ports_spec)`: its docstring lists the specs `"top"`, `"all"`, `"common"` and range lists.
- **`application/ports/probes.py`** (frozen dataclasses plus the Protocol):
  - `DnsRecord(name: str, rtype: int, value: str | tuple[str, ...] | None)`
  - `NetbiosName(name: str, suffix: int, group: bool)`
  - `NetbiosInfo(name: str, workgroup: str, names: tuple[NetbiosName, ...], mac: str)`
  - `SsdpEntry(ip: str, location: str, server: str, usn: str, st: tuple[str, ...])`
  - `CertInfo(sha256: str, subject: str = "", subject_org: str = "", issuer: str = "", issuer_org: str = "", not_after: str = "", self_signed: bool = False, san: tuple[str, ...] = ())`
  - `HttpProbe(scheme: Literal["http", "https"], url: str, status: int | None, reason: str, server: str, powered_by: str, location: str, title: str, generator: str, auth: str, realm: str, tls: str | None, cert: CertInfo | None)`
  - `class ServiceProbes(Protocol)`:
    - `reverse_dns(ip: str, timeout_s: float = 2.0) -> str`
    - `netbios(ip: str, timeout_s: float = 1.5) -> NetbiosInfo | None`
    - `mdns_query(ip: str, qname: str, qtype: int = 12, timeout_s: float = 1.2) -> list[DnsRecord]`
    - `ssdp_search(target: str | None = None, timeout_s: float = 2.5) -> list[SsdpEntry]`
    - `upnp_description(ip: str, location: str) -> dict[str, str]`
    - `http_probe(ip: str, port: int, tls: bool, timeout_s: float = 3.0) -> HttpProbe | None`
    - `tcp_banner(ip: str, port: int, timeout_s: float = 2.0) -> bytes | None`: `None` when the connection fails; `b""` when the service sends nothing within 1.2 s.
- **`application/ports/system.py`:**
  - `WifiInfo(ssid: str = "", bssid: str = "", signal_pct: int | None = None, radio: str = "", band: str = "", channel: str = "", rx_rate_mbps: float | None = None, tx_rate_mbps: float | None = None, state: str = "", auth: str = "")`
  - `TcpSocket(local_ip: str, local_port: int, remote_ip: str, remote_port: int, state: str, process: str)`
  - `class SystemInfo(Protocol)`:
    - `interface_bytes() -> tuple[int, int] | None`: total `(rx, tx)` across adapters.
    - `wifi() -> WifiInfo | None`
    - `tcp_sockets() -> list[TcpSocket]`: netview's own sockets are left out, and process names are resolved.
- **`MetricsStore`** gains:
  - `snapshot(prefixes: Sequence[str] = (), since_ms: int = 0) -> dict[str, list[tuple[int, float | None]]]`: points with `t > since_ms`; every series when `prefixes` is empty.
  - `drop(name: str) -> None`.
- **`application/usecases/health.py`:**
  - `WatchMonitor(uow: UnitOfWorkFactory, bus: EventBus, clock: Clock)`, thread-safe:
    - `record(probes: Iterable[WatchProbe]) -> None`: ignores probes for IPs that are not current watches; on a state change it sets `since_ms` and writes and publishes a WATCH event `"<label or ip> is now <new label> (was <old label>)"`, except for pending → up.
    - `statuses(watches: Sequence[Watch], subnet: IPv4Network) -> list[WatchStatus]`: one per watch in IP order. A watch with no result yet is pending, with the diagnosis "Waiting for the first check."; statuses of removed watches are forgotten.
  - `PollHealth(targets: Callable[[], HealthTargets], metrics: MetricsStore, monitor: WatchMonitor)` with `__call__(provider: HealthProvider) -> None`: appends each `LatencySample` to `metrics` and hands the `WatchProbe`s to `monitor.record`.
  - `HealthTargetsQuery(uow, host: Callable[[], HostInfo], subnet: Callable[[], IPv4Network])` with `__call__() -> HealthTargets`.
- **`application/usecases/traffic.py`:**
  - `@dataclass(frozen=True) TrafficView(ip: str, source: str, down_bps: float | None, up_bps: float | None, down_avg_bps: float | None, up_avg_bps: float | None, down_total: int | None, up_total: int | None, seen_ms: int, extra: Mapping[str, Any])`. The averages are the mean of the non-null samples in the series (10 min).
  - `@dataclass(frozen=True) TrafficTotals(source: str, clients: int, down_bps: float, up_bps: float, t_ms: int)`.
  - `TrafficLedger(metrics: MetricsStore)`, thread-safe:
    - `record(source: str, readings: Iterable[TrafficReading]) -> None`: per reading it computes `counter_rate`, appends `traffic.down.<ip>` and `traffic.up.<ip>` (null when there is no rate), and keeps the latest reading. It then drops IPs unseen for 600 s (and their series) and sets the totals.
    - `views() -> list[TrafficView]`
    - `totals() -> list[TrafficTotals]`
  - `PollTraffic(ledger: TrafficLedger)` with `__call__(source: str, provider: TrafficProvider) -> None`.
- **`application/usecases/identity_poll.py`:** `PollIdentity(devices: Callable[[], list[DeviceView]], claim: ClaimIdentity, clock: Clock)` with `__call__(plugin_id: str, provider: IdentityProvider) -> None`.
  - **Picks:** non-self, non-offline devices whose last check by this plugin is older than `provider.recheck_after_s` (never checked counts as oldest), oldest first, at most 128.
  - **Records:** marks them all checked, even when nothing was claimed, then passes the claims to `claim`. The checked-at map is in memory.
- **Existing types and queries:**
  - **`DeviceView`:** gains `type_source: str` (`""` when there is no type). `build_device_view` uses `best_type`, and `ClaimIdentity`'s TYPE event compares `best_type` before and after.
  - **`NetworkState`:** gains `watch_status: list[WatchStatus]`, `traffic: list[TrafficView]`, `traffic_totals: list[TrafficTotals]` and `inspected: dict[str, int]` (ip → newest report's `finished_ms`, from the new `InspectionRepository.latest_times()`). `GetNetworkState` receives the monitor, the ledger and the subnet callable.
  - **`RunInspection.__call__(ip, ports_spec="top", store=True)`:** when `store` is true it saves the report and writes and publishes `EventKind.INSPECTED`, `"Inspected <display name or ip>"`.
  - **`ForgetDevice`:** also calls `metrics.drop(f"health.device.{key}")`.
- **`CoreFacade`** gains:
  - `device_by_ip(ip: str) -> DeviceView | None`: the online owner first, as in `get_by_ip`.
  - `host() -> HostInfo`
- **`PluginContext`** gains `probes: ServiceProbes` and `system: SystemInfo`.
- **`netview.sdk`** re-exports every new public type above, plus `HostInfo`, `HealthTargets`, `NAME_RANKS`, `TYPE_RANKS`, `vendor_type` and `os_hint`, and sets `SDK_VERSION = "1.1"`.
- **`netview.sdk.testing.fakes`** gains `FakeServiceProbes` and `FakeSystemInfo`. Their constructors take canned answers (dicts keyed by IP, or by `(ip, port)`); they return `None` or empty for anything not given. The fake context exposes both.

- [ ] **Step 1: Write the failing tests**
  - **`assess_watch`:**
    - ports (443, 22) both open → `UP`, "Reachable: every watched port answers."
    - no ports and a ping reply → `UP`
    - 443 open, 22 filtered → `DEGRADED`, with a diagnosis containing "port 22 is not open"
    - only `l2=True` → `PRESENT`
    - `on_subnet=True` and nothing at all → `ABSENT`
    - `on_subnet=False` and nothing at all → `DOWN`, "No reply. This address is outside the local subnet, so the gateway must route to it."
  - **`counter_rate`:**
    - `counter_rate((1000, 0, 0), 2000, 500, 1000) == (8000.0, 4000.0)`
    - going backwards → `None`
    - `dt == 0` → `None`
    - `prev is None` → `None`
  - **`best_type`:** inspection beats vendor; between two vendor claims the newer wins.
  - **`vendor_type`:**
    - `vendor_type("Roku, Inc", None, False) == "Roku device"`
    - `vendor_type("Intel Corporate", 128, False) == "Windows PC"`
    - `vendor_type("", None, True) == "Phone, tablet or laptop"`
  - **`WatchMonitor`** (fake uow and bus) — Review focus 5:
    - pending → up gives no event; up → degraded gives one WATCH event with "is now partly up (was up)";
    - history caps at 60;
    - a probe for an unwatched IP is ignored;
    - after removing a watch, `statuses()` no longer lists it, and re-adding it shows `PENDING`.
  - **`PollHealth`** with a provider returning `[LatencySample("health.gateway", 1, None), WatchProbe(...)]`: the metrics store holds `[(1, None)]`, and the monitor got the probe (Review focus 4).
  - **`HealthTargetsQuery`:** 70 online devices give 64 targets; self and offline devices are excluded; a gateway of `None` passes through.
  - **`TrafficLedger`** — Review focus 2:
    - two readings 5 s apart, +5 MB down → `down_bps == 8_000_000.0`;
    - a third reading with a lower counter → a null sample appended and no exception;
    - an IP unseen for 601 s is dropped from `views()`, and its series from the metrics store;
    - `totals()` sums the latest rates per source.
  - **`PollIdentity`:**
    - 200 eligible devices → the provider gets 128;
    - a second call right away → the provider gets the other 72;
    - a device checked within `recheck_after_s` is skipped;
    - self is never passed.
  - **`RunInspection(store=False)`** saves nothing and writes no event; `store=True` writes one INSPECTED event.
  - **State:** `type_source == "vendor"` shows through, and `inspected` maps the IP to `finished_ms`.
- [ ] **Step 2: Run them and see them fail**

  Run `uv run pytest tests/unit -q`.
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run all checks**, as in Task A. Expected: all pass.
- [ ] **Step 5: Commit** `feat(core): health, identity and traffic use cases, new probe and system ports, SDK 1.1`

---

### Task B2: Infrastructure adapters for the probe and system ports

**Files:**
- Create: `infrastructure/net/{dnswire,probes,system_info}.py`
- Modify: `infrastructure/net/{windows,linux}.py` (new parsers), `infrastructure/plugins/context.py`, `bootstrap.py` (build and pass both adapters)
- Create the fixtures in the file structure. The Windows ones are captured on this laptop with `netstat -e`, `netstat -ano -p tcp`, `tasklist /fo csv /nh` and `netsh wlan show interfaces`, then scrubbed as in Task A item 8. The Linux ones are hand-written in the real formats.
- Tests: `tests/unit/infrastructure/test_dnswire.py`, `test_probes.py`, `test_system_info.py`

**Interfaces (produces):** `SystemServiceProbes()` implements `ServiceProbes`; `SystemSystemInfo(platform: str = sys.platform, own_pid: int = os.getpid())` implements `SystemInfo`.

**Requirements:**
- **`dnswire.py`:**
  - `build_query(tid: int, qname: str, qtype: int, unicast_response: bool) -> bytes`
  - `parse_records(data: bytes) -> list[DnsRecord]`: port LM 593-638. It raises `ValueError` on a pointer loop (more than 30 hops) or truncated data, never `IndexError` or `struct.error`.
- **`SystemServiceProbes`:**
  - **Ports:** port LM 641-666 (`mdns_query`), 691-715 (`netbios`), 734-772 (`ssdp_search`, sending on `IP_MULTICAST_IF = local_ip`), 775-791 (`upnp_description`), 718-731 (the XML field filter with its `DOCTYPE`/`ENTITY` refusal), 873-885 (`reverse_dns` with a timeout thread), 508-558 (`http_probe`, which caps the read at 64 KiB) and 466-505 (the TLS context and `decode_cert`).
  - **`tcp_banner`:** port LM 563-569: connect timeout `timeout_s`, recv 512 bytes with a 1.2 s timeout.
  - **Input checks:** every method checks IPv4 with `common.valid_ipv4` first and returns the empty result for bad input.
  - **Network I/O:** each socket call goes through a small injectable seam (a module-level `_socket_factory` or constructor argument), so tests drive it with fake sockets and never touch the network.
- **`SystemSystemInfo`:**
  - **`interface_bytes`:** Windows `netstat -e` (LM 274-279); Linux `/proc/net/dev` without `lo` (LM 280-291). The `/proc` path is a constructor argument for tests.
  - **`wifi`:** Windows `netsh wlan show interfaces` (LM 294-311), mapping "Receive rate (Mbps)" to `rx_rate_mbps` as a float; Linux `nmcli -t -f active,ssid,signal,chan,rate dev wifi` (LM 312-317). Not on Wi-Fi → `None`.
  - **`tcp_sockets`:**
    - **Commands:** Windows `netstat -ano -p tcp`, Linux `ss -tanpH -4`, macOS `netstat -anp tcp` (LM 330-360). Rows whose PID is `own_pid` are dropped.
    - **Process names:** on Windows, PIDs become names via `tasklist /fo csv /nh`, cached for 30 s (LM 1485-1486 and 321-327); elsewhere the name comes from `ss`.
  - **Commands:** every command runs through `common.run` with the absolute System32 path on Windows (as plan 1b's M19).
- **Context and bootstrap:** `DefaultPluginContext` takes and exposes `probes` and `system`; `build_container` builds one of each.

- [ ] **Step 1: Write the failing tests**
  - **`parse_records`** on a recorded mDNS answer (craft the bytes in the test) returns the PTR, TXT, SRV and A records. A two-label pointer loop raises `ValueError`; a truncated packet raises `ValueError` (Review focus 3).
  - **`netbios`**, given a canned node-status reply through a fake socket, returns the workstation name, the workgroup and the MAC.
  - **`upnp_description`:**
    - a body with `<!DOCTYPE` returns `{}`;
    - a normal body returns `friendlyName` and `manufacturer`, truncated to 120 characters;
    - a `location` on another host, or on `https`, returns `{}` without connecting.
  - **`http_probe`:**
    - a fake server sends `HTTP/1.1 401` with `WWW-Authenticate: Basic realm="iDRAC"` and `<title>a <script></title>` → status 401, realm `iDRAC`, title `a <script>` (raw text; escaping is the UI's job);
    - a 1 MB body is read only up to 64 KiB;
    - a non-HTTP TLS answer → scheme `https`, status `None`.
  - **`tcp_banner`:** `None` when the connection is refused.
  - **Parsers:** `parse_netstat_e` → `(rx, tx)`; `parse_netstat_ano` drops our PID; `parse_tasklist` maps PID → name; `parse_netsh_wlan` → a `WifiInfo` with `signal_pct`; `parse_proc_net_dev` skips `lo`; `parse_ss` reads the process name; `parse_nmcli`.
  - **Bad input:** every probe given `"x; rm -rf"` returns its empty value and never opens a socket or runs a command (patch `common.run` and the socket seam to fail if called).
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run all checks.** Then run a real-network smoke test, without asserting values, to show the adapters work on this laptop:
  ```bash
  uv run python -c "from netview.infrastructure.net.system_info import SystemSystemInfo as S; s=S(); print(s.interface_bytes(), s.wifi(), len(s.tcp_sockets()))"
  ```
  Record the output in the task report.
- [ ] **Step 5: Commit** `feat(infrastructure): service probes and system info adapters`

---

### Task B3: Wiring, API, metrics endpoint and `netview inspect`

**Files:**
- Modify: `application/plugins/jobs.py`, `infrastructure/plugins/host.py`, `infrastructure/metrics.py`, `infrastructure/settings.py`, `bootstrap.py`, `presentation/api/{app,schemas}.py`, `presentation/api/routers/{devices,inspections,watches}.py`, `presentation/cli.py`, `pyproject.toml`
- Create: `presentation/api/routers/metrics.py`
- Tests: `tests/integration/plugins/test_host_polling.py`, `tests/integration/api/test_metrics_api.py`, `test_probe_api.py`, `test_state_parity.py`, `tests/integration/test_cli_inspect.py`, `tests/unit/infrastructure/test_metrics.py` (extend)

**Requirements:**
- **Poll jobs:**
  - `PluginHost(..., poller: Callable[[str, Capability, object], JobSpec | None] | None = None)`.
  - In `start_jobs` and after a settings change in `update_settings`, the host adds `poller(plugin_id, capability, provider)` for every provider that plugin registered, next to the plugin's own `jobs()`.
  - A plugin job whose name starts with `poll.` is refused at load time: the plugin is marked failed with `job name "<name>" is reserved`.
- **The bootstrap poller:**
  - `HEALTH` → `JobSpec("poll.health", settings.fast_interval_s, lambda: poll_health(provider), timeout_s=30)`
  - `IDENTITY` → `JobSpec("poll.identity", 60.0, lambda: poll_identity(plugin_id, provider), timeout_s=120, initial_delay_s=10)`
  - `TRAFFIC` → `JobSpec("poll.traffic", settings.fast_interval_s, lambda: poll_traffic(plugin_id, provider), timeout_s=15)`. The traffic `source` is the plugin id.
  - Any other capability → `None`.
- **Startup claim:** bootstrap claims `NameClaim("self", hostname, "hostname", NAME_RANKS["hostname"], now)`.
- **Metrics capacity:** `RingMetricsStore(maxlen=120, long_prefixes=("health.gateway", "health.internet", "health.dns.", "local."), long_maxlen=720)`, plus `snapshot` and `drop`.
- **Settings:** remove `AppSettings.internet_target` and `dns_servers`; they become health plugin settings in C1, and nothing else uses them.
- **API:**
  - **`GET /api/v1/metrics?since_ms=<int>&prefix=<str>`:** `prefix` is repeatable; `since_ms` defaults to 0. It returns `{"now_ms": int, "series": {name: [[t_ms, value|null], ...]}}`.
  - **`POST /api/v1/devices/{ip}/probe`:** IPv4 only. It runs `run_inspection(ip, "common", store=False)` and returns the report. It is 409 when no inspection plugin is on.
  - **`InspectionIn.ports`:** must match `^(top|all|common|\d{1,5}(-\d{1,5})?(,\d{1,5}(-\d{1,5})?)*)$`, else 422.
  - **`NetworkStateOut`:** gains `watch_status`, `traffic`, `traffic_totals` and `inspected`. `WatchStatusOut.port_state` is keyed by the port as a string.
  - **`DeviceOut`:** gains `type_source`.
  - **`GET /api/v1/watches`:** each item includes its status fields.
- **CLI:** `netview inspect IP [--ports SPEC] [--out FILE]` builds the container (no server, no jobs) and runs the inspection.
  - **Output:** each section's title, then its `data["text"]` lines indented two spaces, or `json.dumps(data, indent=2)` when there is no `text`.
  - **`--out`:** writes `{"schema": "netview/inspection@1", **report}` as JSON.
  - **Exit codes:** 2 for an invalid IP; 1 with "no enabled plugin provides inspection".
- **Entry points:** add `health`, `identity`, `local_host`, `inspection` and `starlink` under `[project.entry-points."netview.plugins"]`, pointing at `netview.plugins.builtin.<id>.plugin:<Name>Plugin` (`HealthPlugin`, `IdentityPlugin`, `LocalHostPlugin`, `InspectionPlugin`, `StarlinkPlugin`). Run `uv sync`. Until tasks C1–C5 land, the Plugins tab lists them as failed; that is expected.

- [ ] **Step 1: Write the failing tests**
  - **Host polling:** a sample plugin providing `HEALTH` gets a scheduler job `(plugin id, "poll.health")`. After `update_settings` the job still exists. A plugin declaring a job `poll.x` is failed with the reserved-name message.
  - **Metrics API:** after three appends at t = 1, 2, 3, `?since_ms=1` returns only t = 2 and 3; `?prefix=health.` filters; a `health.gateway` series holds 720 samples and `health.device.x` holds 120.
  - **Probe API:**
    - with a fake inspection provider: 200, and nothing stored (`GET /inspections/{ip}` → 404);
    - with none: 409;
    - `ip=abc`: 422.
  - **Inspections API:** `ports="1-1024; rm"` → 422.
  - **State:** `/api/v1/state` includes `watch_status` with `"state": "pending"` for a new watch, plus `traffic: []` and `inspected: {}`.
  - **CLI:** `netview inspect 192.0.2.10 --out x.json` with a fake inspection plugin from `tests/integration/plugins/sample_plugins` writes the schema id and prints the section titles; `netview inspect nope` exits 2.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run all checks**, including `npm test`. Expected: all pass, with `Contracts: 6 kept`.
- [ ] **Step 5: Commit** `feat(core): capability poll jobs, metrics and probe endpoints, netview inspect`

---

### Task D: Core UI: charts, metrics cache, card layout, Watches, Events, report dialog

Read the dataviz skill first (Global constraints).

**Files:**
- Create: `js/chart.js`, `js/metrics.js`, `js/cards/watches.js`, `js/cards/events.js`, `js/report/dialog.js`
- Modify: `js/util.js` (add `fmtMs`, and re-export the chart helpers for `ui.util`), `js/main.js`, `js/slots.js`, `js/pages/dashboard.js`, `js/pages/devices.js`, `css/app.css` (tokens only), `index.html` (the report `<dialog>`)
- Tests: `tests/js/chart.test.mjs`, `tests/js/metrics.test.mjs`, `tests/js/report.test.mjs`, `tests/js/dashboard-layout.test.mjs`

**Interfaces (produces; plugins rely on these):**
- **`chart.js`:**
  - **Pure helpers:**
    - `niceMax(v: number) -> number` (LD 548-552)
    - `gapMs(times: number[]) -> number`: 2.5 × the median step, 12500 when there are fewer than 2 steps
    - `segments(points: [t, v][], gap: number) -> {runs: [t, v][][], lone: [t, v][]}`
    - `endLabels(items: {y, text}[], minGap = 14) -> items | []`: returns `[]` when any two are closer than `minGap`
    - `latencyStats(values: (number|null)[]) -> {last, loss, avg, min, max, jitter}` (port LM 1588-1591; `loss` is a whole percent)
  - **DOM:** `lineChart(el, {label, series: [{name, color, points}], fmt, height = 170})`. `color` is a CSS variable name such as `"--series-1"`, resolved at draw time; `fmt(v)` returns the full text with its unit.
    - **Empty state:** "Collecting samples…" when no series has 2 points.
    - **Redraws:** each redraw keeps an open "Data table" `<details>` open.
    - Everything else follows the dataviz rules in Global constraints.
  - **`sparkline(values, {w = 72, h = 18, color = "--series-1"}) -> string`:** an SVG string. Missing samples are short ticks in `--bad` (LD 668-678).
- **`metrics.js`:**
  - `limitFor(name) -> 720 | 120`, by the long prefixes in Global constraints.
  - `mergeMetrics(cache, delta) -> cache`: appends the delta's points, drops points at or before the last cached time, and trims each series to `limitFor`.
  - `createMetricsClient(apiGet) -> {refresh(): Promise<cache>, cache}`: calls `/api/v1/metrics?since_ms=<newest time seen>`.
  - `main.js` refreshes metrics alongside every state refresh and sets `state.metrics = cache` (an object of name → `[t, v][]`) before pages update. A metrics failure keeps the old cache.
- **Card layout:**
  - **Card spec:** `dashboard.card` specs may have `order` (default 30), `span` (`"full" | "half" | "third"`, default `"half"`), `title`, `sub`, and either `render(state) -> html` (existing) or `draw(el, state)`.
  - **Persistent cards:** the dashboard keeps one persistent `<section class="card">` per spec, keyed `<pluginId>.<id>`, and never rebuilds it.
    - A `draw` spec owns the inside of a body element below the card's `<h2>` and sub.
    - A spec that throws shows its error in that card only.
  - **Tiles:** `dashboard.tile` specs may have `order` (default 50). The core tiles are order 0–3.
  - **Grid:** a 6-column CSS grid, where full = 6, half = 3 and third = 2. Under 900 px every card is full width.
  - **Core cards:** Watches (`order: 10`, full) and Events (`order: 60`, half).
- **`cards/watches.js` (core):** draws from `state.watch_status` (port LD 510-545, without middle dots).
  - **Each watch:** the label (or IP), the IP in `.addr`, and a status chip with icon and label: up "Up", degraded "Partly up", present "On the network only", absent "Not on the network", down "No reply", pending "Checking".
  - **Layer chips:**
    - ARP: "n/a (routed)", "✓ ARP <mac>" or "✕ ARP";
    - ping: "✓ Ping 2.1 ms" or "✕ Ping";
    - each port: "✓ TCP 443 open", "✕ TCP 22 refused" or "✕ TCP 22 no answer".
  - **Below the chips:** the diagnosis; a history strip of the last 60 checks; "since <time>".
  - **Remove:** a Remove button sends `DELETE /api/v1/watches/{ip}`.
  - **Add form:** placeholder `192.168.1.128:443,22=R720 iDRAC`, button "Watch host", `POST /api/v1/watches {spec}`. A 422 shows "Couldn't add that: <message>. Format: IP[:port,port][=label]".
  - **Empty state:** "No watched hosts. Add one below, for example the iDRAC address with ports 443 and 22."
  - **Sub:** "Checked every few seconds, layer by layer: ARP (is it on this network?), ping, then each TCP port."
  - **No health plugin:** when `state.capabilities` lacks `health`, a note says "No health plugin is turned on, so watches are not being checked."
- **`cards/events.js` (core):**
  - **List:** `state.events`, newest first. Each row is the time, a kind chip and the text.
  - **Sub:** "New devices, devices leaving and returning, address changes, watch changes and inspections."
  - **Empty state:** "Nothing yet. Events start after the first sweep."
- **`report/dialog.js` (core):** `openReport(ip, {fresh = false, ports = "top"})`.
  - **Header:** the title is the device's display name, or the IP; the sub-line is the IP (and, once a report exists, "Checked <date and time>"). Buttons: Run again, All ports (title "Scan all 65,535 TCP ports (about a minute)"), Close.
  - **Live area:** every `report.live-section` spec gets `draw(el, {ip, device, state})` when the dialog opens and on every state update while it is open. Each has its own container; one failing shows its error only.
  - **Body:**
    - **Loading:** `GET /api/v1/inspections/{ip}` unless `fresh`; on 404, or when `fresh`, `POST /api/v1/inspections {ip, ports}`.
    - **While running:** "Inspecting <ip>: about 1,100 TCP ports, web pages, certificates, mDNS, NetBIOS and UPnP, about 10 seconds…" (or "all 65,535 TCP ports, about a minute" for `all`). Both buttons are disabled.
    - **Sections:** for each report section, the matching `report.section` spec (`spec.section === section.id && spec.pluginId === section.plugin_id`) gets `draw(el, section, report)`. Without one, a generic renderer shows `<h3>` with the title, then a `<dl>` of the top-level scalar data (except `text`). A section with `error` shows "This section failed: <error>".
    - **Failures:** a 409 shows "No inspection plugin is turned on." Any other failure shows "Inspection failed: <message>".
  - **Closing:** Escape, the Close button, or a click on the backdrop closes it; focus returns to the opener.
  - `ctx.openReport` is added to the page context.
- **`devices.js`:**
  - **Actions:** "Inspect", or "View report" when `state.inspected[ip]` exists, opens the report. "Watch" (when not watched) posts `{spec: ip}`. Forget stays. Inspect is disabled with the title "No inspection plugin is turned on" without the capability.
  - **Toolbar:** an "Inspect any IP" form with the placeholder "Inspect any IP, e.g. 192.168.1.125". A non-IPv4 value gets `setCustomValidity("Enter an IPv4 address")`.
  - **Type cell:** adds a muted "guess from maker" line when `type_source === "vendor"` and the row is not self.
  - **Plugin columns:** `render(d, state)` now also receives the state, so plugin columns can read `state.metrics` and `state.traffic`. `sortKey(d, state)` likewise.

- [ ] **Step 1: Write the failing JS tests**
  - `niceMax(7.3) === 8`, `niceMax(0) === 1`, `niceMax(130) === 200`.
  - `gapMs([0, 5000, 10000, 40000]) === 12500`; `segments` splits at the 30 s jump, and a single isolated point goes to `lone`.
  - `endLabels([{y: 10}, {y: 20}]) → []`; `endLabels([{y: 10}, {y: 40}])` keeps both.
  - `latencyStats([10, null, 20, 30])` → `{last: 30, loss: 25, avg: 20, min: 10, max: 30, jitter: 10}`; `latencyStats([])` → all `null`.
  - `mergeMetrics`: a delta overlapping the cache adds no duplicates; `health.device.x` trims to 120 and `health.gateway` to 720.
  - **Dashboard layout:**
    - `orderCards` sorts by `order`, then registration order;
    - `spanClass("third") === "span-2"`;
    - a throwing `draw` gives an error card while the others render (use a minimal DOM stub, as `pages.test.mjs` does).
  - **Report:** the generic renderer escapes `<script>` in section data (Review focus 3); `matchSection` finds a renderer by plugin id and section id.
- [ ] **Step 2: Run `npm test` and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run `npm test`, `uv run pytest -q` and the token-only grep from plan 1b U2.** Expected: all pass; the grep prints nothing.
- [ ] **Step 5: Commit** `feat(ui): charts, metrics cache, card layout, watches, events and report dialog`

---

### Task C1: `health` plugin

**Files:** `plugins/builtin/health/{__init__,plugin,settings,routes}.py`, `static/ui.js`; tests `tests/integration/plugins/test_health.py`, `tests/js/health-ui.test.mjs`

**Manifest:**
- id `health`, name "Health", version `0.1.0`, description "Pings the gateway, the internet and every online device, times DNS and checks watched hosts"
- capabilities `HEALTH, API, WEB_UI`
- permissions `devices:read, network:probe, api, ui`

**Settings (`HealthSettings`):**

| Field | Type and default | Limits |
|---|---|---|
| `internet_target` | `str = "1.1.1.1"` | IPv4 |
| `dns_servers` | `list[str] = []` | at most 2, each IPv4 |
| `dns_names` | `list[str]` | default `["www.google.com", "www.cloudflare.com", "www.microsoft.com", "www.amazon.com"]` |
| `ping_timeout_ms` | `int = 1000` | 100–5000 |
| `internet_timeout_ms` | `int = 1500` | 100–5000 |
| `port_timeout_s` | `float = 1.5` | 0.2–10 |
| `max_devices` | `int = 64` | 0–64 |

**Behaviour:** `probe(targets)` ports LM 1380-1400 and 1332-1340.
- **Probes**, all at once in one pool of `8 + n` threads:
  - gateway ping → `health.gateway` (a `null` sample when there is no gateway);
  - internet ping → `health.internet`;
  - one DNS query per server, with a random name from `dns_names` → `health.dns.<server>`. With no `dns_servers` set, the servers are `[gateway, "1.1.1.1"]`, de-duplicated, without `None`, at most 2;
  - a device ping for the first `max_devices` targets → `health.device.<key>`;
  - for each watch: ping (1000 ms), `tcp_probe` on each port, and the ARP table only when `on_subnet` → one `WatchProbe`.
- **Timing:** every sample of one run carries the same `t_ms`, taken after all probes finish.
- **Failures:** a probe that raises gives `None` for that target; `probe()` never raises.
- **Router:** `GET /summary` → `{"gateway": str | null, "internet": str, "dns": [str]}`, using the current settings and `ctx.core.host().gateway`.

**UI (`static/ui.js`):** values come from `state.metrics` and the summary (fetched as `lan_discovery` does).
- **Tiles** (order 10–12):
  - "Gateway ping": the last value in ms, with the sub "<loss>% loss, average <avg> ms over 5 min", computed with `latencyStats` over samples newer than now − 300 000 ms;
  - "Internet ping (<target>)": the same;
  - "DNS (<server 1>)": the last value, with the sub "<server 2>: <n> ms" when there are two servers.
- **Cards** (both third width, order 20 and 21):
  - "Latency": sub "Round-trip time in ms; gaps are lost pings."; series "Gateway <ip>" (`--series-1`) and "Internet <ip>" (`--series-2`);
  - "DNS response": sub "Time to answer one lookup, in ms."; one series per server (`--series-1`, `--series-2`).
- **`devices.column`** `lat`: label "Latency", sub "(live, 10 min)". The sort key is the last value, with `null` sorting last. Port LD 687-692 without middle dots: "<n> ms" or "no reply", a sparkline, then "average <n> ms, <x>% loss" (the loss in a `.warn` span when above 0). A quiet device shows "ignores ping", self shows "–", and anything else "waiting…".
- **`report.live-section`** `latency`: port LD 963-973 and 1004.
  - **Heading:** "Live".
  - **Tiles:** Now, Average, Best, Worst, Jitter and Loss. "Now" reads "lost" in `--bad` when the last sample is `null`.
  - **Chart:** "Latency from this device to <ip>, last 10 min".
  - **No samples:** the quiet, self and waiting messages from LD 973.

- [ ] **Step 1: Write the failing tests**
  - Through `check_plugin(HealthPlugin)` (the contract kit).
  - **`probe`** with `FakeNetwork`, where the gateway answers 2 ms, the internet doesn't answer, DNS answers 15 ms, and two devices of which one replies: it returns `health.gateway` 2.0, `health.internet` `None`, `health.dns.192.168.1.1` 15.0 and two device samples (one `None`), all with the same `t_ms`.
  - **Review focus 4:** with `HealthTargets(gateway=None, ...)` and no DNS servers set, the DNS servers are `["1.1.1.1"]`, the gateway sample is `None`, and no exception is raised.
  - **Watch probe:** a watch outside the subnet → `on_subnet False`, `l2 None`, and the ARP table is not read.
  - **`max_devices=1`** with 3 targets → one device sample.
  - **End to end:** the plugin loaded through `PluginHost` with the real poller in `build_container` (a tmp data dir and fake network tools); one `poll.health` run fills `health.gateway` in `/api/v1/metrics`.
  - **JS:** the tile sub-text for samples `[10, null, 20, 30]` reads "25% loss, average 20 ms over 5 min".
- [ ] **Step 2: See them fail; Step 3: Implement; Step 4: Run all checks; Step 5: Commit** `feat(plugins): health plugin`

---

### Task C2: `identity` plugin

**Files:** `plugins/builtin/identity/{__init__,plugin,settings}.py`; test `tests/integration/plugins/test_identity.py`

**Manifest:**
- id `identity`, name "Identity", version `0.1.0`, description "Names devices from UPnP, NetBIOS, mDNS and reverse DNS, and guesses their type from the maker"
- capabilities `IDENTITY`
- permissions `devices:read, names:write, types:write, network:probe`

**Settings:**

| Field | Default | Limits |
|---|---|---|
| `recheck_after_s` | `1800` | 300–86400 |
| `ssdp_timeout_s` | `3.0` | |
| `mdns_timeout_s` | `1.0` | |
| `netbios_timeout_s` | `1.0` | |
| `rdns_timeout_s` | `1.5` | |
| `workers` | `16` | 1–64 |

The provider's `recheck_after_s` reads the live setting.

**Behaviour:** `identify(devices)` ports LM 1646-1675 and 802-811.
- **SSDP:** one `ssdp_search(None, ssdp_timeout_s)`. For each IP in the batch, the first entry whose `upnp_description` has a `friendlyName` gives a UPnP name.
- **Per device**, in a pool of `workers`:
  - mDNS reverse PTR (`<reversed ip>.in-addr.arpa`, type 12), with a trailing `.local` or `.local.` stripped;
  - the NetBIOS `name`;
  - `reverse_dns`.
- **Name claims:** one `NameClaim` per source that found a non-empty name (`UPnP`, `NetBIOS`, `mDNS`, `DNS`), with `rank = NAME_RANKS[source]` and `checked_ms = now`. Names are truncated to 80 characters. Every claim is sent; the domain picks the best.
- **Type claim:** `TypeClaim(key, vendor_type(vendor, ttl, private_mac), "guess from maker", "vendor", now)` when non-empty. `private_mac` comes from the locally-administered bit of `device.mac`.
- **Failures:** a probe that raises counts as not found; `identify` never raises.

- [ ] **Step 1: Write the failing tests**
  - Contract check.
  - **Claims** with `FakeServiceProbes`, where SSDP finds `192.0.2.5` with friendlyName "Roku TV", mDNS answers `jessis-ipad.local.` for `.6`, and NetBIOS answers `R720` for `.7`:
    - claims `(.5, "Roku TV", "UPnP", 6)`, `(.6, "jessis-ipad", "mDNS", 3)`, `(.7, "R720", "NetBIOS", 4)`;
    - a vendor `TypeClaim` for a device whose vendor is "Roku, Inc".
  - **Escaping:** a friendlyName of `<b>TV</b>` is stored as typed; the UI test in Task D covers the escaping.
  - **Ranking:** through `PollIdentity` and the real `ClaimIdentity` on a SQLite database, a device with both UPnP and DNS names gets `device_name` from UPnP.
- [ ] **Step 2: See them fail; Step 3: Implement; Step 4: Run all checks; Step 5: Commit** `feat(plugins): identity plugin`

---

### Task C3: `local_host` plugin

**Files:** `plugins/builtin/local_host/{__init__,plugin,settings,routes,connections}.py`, `static/ui.js`; tests `tests/integration/plugins/test_local_host.py`, `tests/js/local-host-ui.test.mjs`

**Manifest:**
- id `local_host`, name "This device", version `0.1.0`, description "This device's throughput, Wi-Fi link and TCP connections"
- capabilities `LOCAL_HOST, API, WEB_UI, JOBS`
- permissions `devices:read, api, ui`

**Settings:** `throughput_interval_s: float = 5.0` (1–60) and `connections_interval_s: float = 10.0` (5–120).

**Behaviour:**
- **Job `throughput`:** reads `ctx.system.interface_bytes()`. It computes the rate against the previous reading (LM 1401-1409: a negative delta or `dt <= 0` gives `None`) and appends `local.down_bps` and `local.up_bps` (bits per second).
- **Job `snapshot`:** reads `ctx.system.wifi()` and `tcp_sockets()`, then `connections.summarize(sockets, subnet, name_for) -> dict`, a pure port of LM 1488-1529:
  - **Sorting:** `LISTEN*` sockets go to listening; remotes on `127.*`, `0.0.0.0` or `*` are skipped; `ESTABLISHED`/`ESTAB` sockets are grouped by (process, remote, port), and `SYN*` sockets go to trying.
  - **Scope:** `lan`, `private` (private or 100.64/10) or `internet`.
  - **`service`:** comes from `COMMON_PORTS` (copy LM 100-106 into `connections.py`).
  - **Limits:** 60 / 40 / 20.
  - **Summary fields:** `total`, `states`, `unique_remotes`, `lan_conns`.
  - **`name_for(ip)`:** `ctx.core.device_by_ip(ip).display_name`, else the label of a watch on that IP, else `""`.
- **Provider:** `snapshot()` returns `{"wifi": asdict(wifi) | None, "connections": dict, "t_ms": int}`. The router's `GET /snapshot` returns the same.

**UI:**
- **Tiles** (order 20–22):
  - "Wi-Fi signal": the value in %, with the sub "<ssid>, <band>, channel <n>" (the parts that exist), or the value "–" with "Not on Wi-Fi";
  - "Download (this device)": the last `local.down_bps` through `fmtRate`, with the sub "Wi-Fi link <n> Mbit/s" or "All adapters";
  - "Upload (this device)": the same, from `local.up_bps`.
- **Card "This device's throughput"** (third, order 22): sub "All adapters."; series Download (`--series-1`) and Upload (`--series-2`); `fmt = fmtRate`.
- **Card "This device's connections"** (half, order 40): port LD 863-887.
  - **Sub:** "<n> TCP sockets, <n> remote hosts, <n> connections to this LAN. Refreshed every 10 s."
  - **Above the tabs:** state chips.
  - **Tabs:** Established, Trying to connect and Listening, with `role="tablist"` and arrow keys.
  - **Table columns:** Process, Remote (address in `.addr`, then the name and the scope), Port (with the service) and Count. Listening shows Port, Address and Process.
  - **Empty text:** LD 880.
- **`report.live-section`** `connections`: port LD 993-997.
  - **Connections:** "Between this device and <ip>: <n> open connections from <process> to port <p> (<service>); still trying to reach ports …", or "This device has no open connections to <ip> right now."
  - **No traffic data:** when `state.traffic` has no entry for the IP, it also draws "This device's throughput (all its traffic, not just to <ip>)" as a chart of the last 120 `local.*` samples, and the line "This device can't see <ip>'s own traffic. After the OPNsense cutover, its Reporting and Insight pages show per-device traffic."

- [ ] **Step 1: Write the failing tests**
  - Contract check.
  - **Throughput** — Review focus 2: readings `(1000, 500)` then `(6000, 1500)` 5 s apart → `8000.0` and `1600.0` bps; then `(10, 10)` → `None` for both.
  - **`summarize`** on a fixture list of `TcpSocket`:
    - two ESTABLISHED to the same `(chrome, 142.250.1.1, 443)` give one row with count 2, scope `internet` and service "HTTPS";
    - a SYN_SENT to `192.168.1.128:443` goes to trying with scope `lan` and the watch label as its name;
    - LISTEN rows sort by port;
    - a `127.0.0.1` remote is skipped.
  - **End to end:** the `/snapshot` route through the API test client (fake system info) returns the summary.
  - **JS:** the connections sub-text has no `·`; the Wi-Fi tile sub for `{ssid: "Home", band: "5 GHz", channel: "36"}` is "Home, 5 GHz, channel 36".
- [ ] **Step 2: See them fail; Step 3: Implement; Step 4: Run all checks; Step 5: Commit** `feat(plugins): local_host plugin`

---

### Task C4: `inspection` plugin

**Files:** `plugins/builtin/inspection/{__init__,plugin,settings,ports,analysis,hints,routes}.py`, `static/ui.js`; tests `tests/integration/plugins/test_inspection.py`, `tests/unit/plugins/test_inspection_hints.py`, `tests/js/inspection-ui.test.mjs`

**Manifest:**
- id `inspection`, name "Inspection", version `0.1.0`, description "Scans a device's TCP ports and reads its web pages, certificates and discovery answers"
- capabilities `INSPECTION, API, WEB_UI`
- permissions `devices:read, names:write, types:write, network:probe, api, ui`

**Settings:**

| Field | Default | Limits |
|---|---|---|
| `workers` | `256` | 16–1024 |
| `port_timeout_s` | `0.8` | |
| `full_scan_timeout_s` | `0.5` | |
| `max_analyzed` | `64` | 1–256 |

**Behaviour:**
- **`ports.py`:**
  - Copy `COMMON_PORTS`, `DEEP_PORTS`, `LOW_NAMES` and `TLS_FIRST` verbatim (LM 100-106 and 415-442).
  - `ALL_PORT_NAMES`.
  - `parse_ports(spec) -> list[int]`: LM 445-463, plus `"common"` → the `COMMON_PORTS` ports.
- **`analysis.py`:**
  - **`analyze_port(probes, ip, port) -> dict`:** port LM 561-590 through `probes.tcp_banner` and `probes.http_probe`, including the HTTP/2 SETTINGS check. Its banner text is "HTTP/2 without TLS (server sent SETTINGS first): usually a gRPC API".
  - **`mdns_info(probes, ip)`:** port LM 669-688, including the TXT key filter.
  - **`ssdp_info(probes, ip)`:** port LM 794-799, at most 6 entries.
- **`hints.py`:** pure functions over a plain result dict shaped like LM's `inspect_host` result.
  - `discovered_name(r)` (LM 817-827), `device_type(r)` (LM 847-870, falling back to the SDK's `vendor_type`) and `device_hints(r)` (LM 888-972). Hint texts are verbatim.
  - **The fixed rules:**
    - a self-identification hint comes first;
    - an AirPlay receiver whose maker isn't Apple gets the "Accepts AirPlay from Apple devices (built into this <maker> device)." hint, not the Apple one.
- **`inspect(ip, ports_spec)`:** ports LM 975-1015.
  - **Lookups:** the MAC comes from `ctx.core.device_by_ip(ip)`, else the ARP table; the vendor from `ctx.vendors`, or "Random or local MAC".
  - **`"common"`:** only a `ports` section with TCP states (no banners or HTTP), and no claims.
  - **Every other spec:** returns these sections in order; each one's `data` includes `text: list[str]`, a port of the matching lines of LM 1018-1052 without middle dots:
    1. `summary`, "What it probably is": `{hints, type, device_name, name_source}`
    2. `identity`, "Identity": `{mac, vendor, private_mac, rtt_ms, ttl, os_hint, names, netbios}`
    3. `web`, "Web interfaces", only when there are any: `{items: [{port, url, status, reason, title, server, powered_by, generator, realm, location, tls, cert}]}`
    4. `ports`, "Open TCP ports": `{ports_spec, scanned, open: [{port, name, banner?, http?}], refused, no_answer, duration_s}`
    5. `mdns`, "mDNS and Bonjour", when there is an answer
    6. `upnp`, "UPnP and SSDP", when there is an answer
    7. `discovery`, "Discovery protocols", when none of mDNS, UPnP or NetBIOS answered: `{}`, with the text "No answer to mDNS, UPnP/SSDP or NetBIOS."
- **After a non-`common` inspection of a known, non-self device:** `ctx.core.claim([...])` sends the discovered name (`NameClaim` with its source rank), `TypeClaim(type, "from inspection", "inspection", now)` when non-empty, and every hint as `Hint(key, text, "inspection")`. It then records `open_ports[ip] = [{port, name}]` in memory.
- **Router:** `GET /open-ports` → `{ip: [{port, name}]}`.

**UI:**
- **`report.section` renderers**, ports of LD 919-955 without middle dots:
  - **`summary`:** the hints list, or "No clear match.".
  - **`identity`:** a key/value list.
  - **`web`:** links appear only for URLs that start with `http://` or `https://`, with `target="_blank" rel="noopener noreferrer"`; the details follow, joined with commas.
  - **`ports`:**
    - **First line:** "<scanned> TCP ports in <s> s: <n> open, <n> refused, <n> no answer".
    - **Table:** Port, Usually, What answered.
    - **Certificate line:** "TLS <v>, certificate <subject> (<org>), issued by <issuer>, self-signed, expires <date>, also <san…>".
  - **`mdns`, `upnp` and `discovery`.**
- **`devices.column`** `ports`: label "Open ports". It shows "open: 22 SSH, 80 HTTP +2 more" (the first 3), "no open ports found", or blank when the device has never been inspected. It reads `/open-ports`, refetched once per state change.

- [ ] **Step 1: Write the failing tests**
  - **`parse_ports`:**
    - `parse_ports("top")` has 1024 + (the number of `DEEP_PORTS` above 1024) entries, sorted;
    - `parse_ports("common") == [p for p, _ in COMMON_PORTS]`;
    - `parse_ports("0-5")` raises `ValueError`.
  - **Hints:**
    - for a result with an AirPlay service, TXT `manufacturer=LG`, and UPnP friendlyName "LG TV": the first hint is "It identifies itself as LG TV (LG …)."; the AirPlay hint is the non-Apple one; there is no "Apple device" hint;
    - port 62078 open → "iPhone or iPad" type;
    - a certificate issued by "SpaceX Router CA" → "Starlink router" type and the Starlink hint.
  - **`analyze_port`** with a fake banner of `b"\x00\x00\x12\x04\x00\x00\x00\x00\x00..."` → the gRPC banner text.
  - **`inspect`** with fakes:
    - port 80 is open with title `<script>x</script>` → `web.items[0].title` keeps the raw text (escaping is tested in the JS below);
    - claims reach the facade for a known device and not for self;
    - `"common"` gives only the `ports` section, with no claims.
  - **Through the real `RunInspection`**, the report has the sections in the order listed, and `netview inspect` prints each section's `text`.
  - **JS:** the `web` renderer turns the title `<script>` into `&lt;script&gt;` (Review focus 3) and does not link a `javascript:` URL.
- [ ] **Step 2: See them fail; Step 3: Implement; Step 4: Run all checks; Step 5: Commit** `feat(plugins): inspection plugin`

---

### Task C5: `starlink` plugin

**Files:** `plugins/builtin/starlink/{__init__,plugin,settings,client,protobuf,storage,routes}.py`, `versions/0001_starlink.py`, `static/ui.js`; tests `tests/integration/plugins/test_starlink.py`, `tests/unit/plugins/test_starlink_protobuf.py`, `tests/js/starlink-ui.test.mjs`; fixture `tests/fixtures/starlink/clients.bin` (a synthetic gRPC-Web response built in a test helper with documentation IPs, not a capture)

**Manifest:**
- id `starlink`, name "Starlink router", version `0.1.0`, description "Per-device traffic, signal and names from a Starlink router's local API (read-only)"
- capabilities `TRAFFIC, STORAGE, API, WEB_UI`
- permissions `devices:read, names:write, traffic:write, storage:own, network:probe, api, ui`

**Settings:** `router: str | None = None` (IPv4; `None` means the gateway), `port: int = 9001`, `timeout_s: float = 4.0` (1–30). Turning the plugin off replaces LM's `--router-api off`.

**Behaviour:**
- **`protobuf.py`:**
  - `varint(buf, i)` and `fields(buf) -> dict[int, list[int | bytes]]`: port LM 1061-1090.
  - **Strictness:** truncated input or an unknown wire type raises `ValueError`, never `IndexError`.
- **`client.py`:**
  - `starlink_clients(host, port, timeout_s, post=_http_post) -> list[dict]`: port LM 1093-1135.
  - **Transport:** `post(host, port, path, body, headers, timeout_s) -> (status, headers, bytes)` is the injectable transport, and `_http_post` uses `http.client`.
  - **Failures:** an HTTP or gRPC error raises `OSError` with LM's message. Every parse error is re-raised as `ValueError("router API sent an unreadable answer")`.
- **Storage:**
  - **Table** `starlink_counters`: `ip` (primary key), `name`, `down_bytes`, `up_bytes`, `t_ms`. Use SQLAlchemy Core metadata plus an Alembic version file with `branch_labels=("starlink",)`, following `tests/integration/plugins/sample_plugins/good_versions/0001_good.py`.
  - **Writes:** each successful read upserts every client in `ctx.unit_of_work()`.
  - **Baselines after a restart:** on the first successful read after setup, for each client whose stored row is younger than 60 s and whose counters are not higher than the current ones, `read()` emits the stored reading first (with its stored `t_ms`), so the core ledger has a rate at once.
- **`read()`:**
  - **No target:** no router address and no gateway → `[]`.
  - **Readings:** `TrafficReading(ip, now, down_bytes, up_bytes, extra={name, signal_dbm, down_link, up_link, assoc_s, role, ap})`. Clients with no byte counters are skipped.
  - **Names:** for each client with a name whose IP maps through `ctx.core.device_by_ip` to a non-self key, it claims `NameClaim(key, name, "DHCP", NAME_RANKS["DHCP"], now)` (LM 1457-1459).
  - **Failures:** propagate, so the `poll.traffic` job fails and the scheduler backs off.
- **Router:** `GET /status` → `{"target": str | null, "last_ok_ms": int | null, "error": str}`.

**UI:** reads `state.traffic`, `state.traffic_totals`, `state.metrics`, and the job status `owner "starlink", name "poll.traffic"`.
- **Tiles** (order 30–31), when the job's `last_ok` is true:
  - "All Wi-Fi devices": the value "<down> / <up>" in Mbit/s, with the sub "<n> clients, from the Starlink router";
  - "Top uploader (10 min average)": the non-self device with the highest `up_avg_bps`, showing its rate and display name.
- **Failing tile:** while the job is failing, one tile "Router traffic" with the value "–" and the sub "Unavailable: <last_error>".
- **`devices.column`** `traffic`: label "Traffic", sub "(from router)", sort key the upload average descending.
  - **Cell:** port LD 660-666: "↓ <rate>", "↑ <rate>" plus a sparkline of `traffic.up.<ip>` (`--series-2`), and "sent <bytes> since connecting".
  - **No traffic entry:** "not a Wi-Fi client of the router" when the job is ok, else "router data unavailable".
- **`report.live-section`** `traffic`, when the IP has a traffic entry: port LD 975-999.
  - **Tiles:** Upload now, Download now, Upload 10 min average, Uploaded while idle (with "in <n> min"), Sent since connecting, Received since connecting, Wi-Fi signal (dBm).
  - **Link line** (spec §10: signal, link rates and mesh role), below the tiles: "Connected as a <role> to access point <ap> for <duration>. Link rates <down_link> down and <up_link> up, as the router reports them." Parts that are missing are left out.
  - **Chart:** "<ip>'s own traffic, from the router's counters, last 10 min", with Download (`--series-1`) and Upload (`--series-2`).
  - **ACR note:** when the type, device name, nickname or router name matches `/\btv\b|roku|television/i`, the ACR note from LD 992.
  - **Footer:** the line from LD 998, about traffic figures coming from the router's counters.
  - **`uploadedWhileIdle(times_ms, down_bps, up_bps) -> {bytes, seconds}`:** a pure, exported port of LD 978-982. A sample counts as idle when download is below 50 000 bps and the step is under 30 s.

- [ ] **Step 1: Write the failing tests**
  - Contract check, including storage validation.
  - **`fields`** on the synthetic fixture yields two clients, `192.0.2.20` (down 5 000 000, up 300 000, signal −52.5, role client) and `192.0.2.21` (role mesh node). The router's own entry (no IP) is skipped.
  - **Review focus 1:**
    - a transport returning 404 → `OSError` with "router API refused: HTTP 404";
    - `grpc-status: 12` → `OSError`;
    - a body cut in half → `ValueError("router API sent an unreadable answer")`;
    - through `PluginHost` and the real scheduler with a 0.05 s interval, three failures give `consecutive_failures == 3` and a growing `next_run_ms` gap, while another plugin's job keeps running.
  - **DHCP names:** a read claims the name "Living room TV" for the known device at `192.0.2.20`, and nothing for an unknown IP.
  - **Baselines:** with a stored row 20 s old and lower counters, the first `read()` returns 2 readings for that IP; with a row 120 s old, it returns 1.
  - **Fence:** writes go only to `starlink_counters`; a write to `devices` through the plugin's unit of work raises (the fence from plan 1b and Task A).
  - **JS:** `uploadedWhileIdle([0, 5000, 10000], [0, 10000, 10000], [0, 80000, 80000])` → `{bytes: 100000, seconds: 10}`. The traffic cell without an entry reads "router data unavailable" while the job is failing.
- [ ] **Step 2: See them fail; Step 3: Implement; Step 4: Run all checks; Step 5: Commit** `feat(plugins): starlink plugin`

---

### Task E: Independence contract, docs and the parity check

**Files:** `pyproject.toml`, `README.md`, `docs/superpowers/parity-2026-11-10.md` (new)

- [ ] **Step 1: Add the independence contract**

  ```toml
  [[tool.importlinter.contracts]]
  name = "Built-in plugins are independent"
  type = "independence"
  modules = [
      "netview.plugins.builtin.lan_discovery",
      "netview.plugins.builtin.health",
      "netview.plugins.builtin.identity",
      "netview.plugins.builtin.local_host",
      "netview.plugins.builtin.inspection",
      "netview.plugins.builtin.starlink",
  ]
  ```
  Run `uv run lint-imports`. Expected: `Contracts: 7 kept, 0 broken`.
- [ ] **Step 2: Update `README.md`**
  - a table of the built-in plugins (id, what it does, settings);
  - `netview inspect`;
  - `GET /api/v1/metrics` and the series names;
  - SDK 1.1: the new `ctx.probes` and `ctx.system`, the poll jobs and the `poll.` job-name reservation, and the changed provider signatures.
- [ ] **Step 3: Run every check**

  Run:
  ```bash
  uv run pytest -q
  ```
  ```bash
  npm test
  ```
  ```bash
  uv run ruff check .
  ```
  ```bash
  uv run mypy src/netview/domain src/netview/application src/netview/sdk
  ```
  ```bash
  uv run lint-imports
  ```
  Expected: all pass. Record the counts.
- [ ] **Step 4: The parity check (the controller, in the browser)**
  - Run the old monitor (launch config `lan-monitor`, port 8765) and netview (launch config `netview`, port 8766, data dir `network/netview-dev`) side by side on the real network.
  - Walk every bullet of spec §10 on both, and write `docs/superpowers/parity-2026-11-10.md`: one row per bullet with "match", "differs (why)" or "missing".
  - Then a browser pass over all four themes at 1280 px and 375 px: dashboard (tiles, watches, three charts with hover and the data table, connections tabs, events), devices (latency and traffic columns, grouping, columns menu), the report dialog (live section updating, sections, All ports) and the settings tabs of the five new plugins.
  - Anything "missing", or any visual bug, gets fixed before the review.
- [ ] **Step 5: Commit** `docs: parity check, README for plan 2, plugin independence contract`

---

## Execution notes for the controller

- Order: A → B1 → B2 → B3 → D → C1–C5 → E.
  - C1–C5 touch disjoint files once B3 has added the entry points.
  - C1, C3 and C5 depend on D's `chart.js`, card layout and `state.metrics`.
  - C2 and C4 depend only on B1–B3.
- After each stage, run the full checks and have a reviewer read that stage's diff against this plan before the next stage builds on it.
- Then a whole-branch review on Opus. Fix its findings, re-run every check and the browser pass, and merge only when the user says so.
