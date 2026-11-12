# GS105E switch plugin, phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only netview folder plugin for the NETGEAR GS105Ev2. It logs in to the switch's web pages and shows identity, ports, traffic, VLAN/QoS/IGMP/mirroring/loop/management settings and change events on a Switch page built on the drawn faceplate.

**Architecture:** A pure layer of model types, login hash, HTML page parsers and analysis rules, tested against the scrubbed pages in `plugins/gs105e/tests/fixtures/fw-1.6.0.11/`. Above it sit an HTTP session with an injectable transport, a collector, SQLite storage, and a service that runs the poll jobs and applies the session rules. A FastAPI router and a plain-JS UI (slots) sit on top. The structure mirrors `plugins/gsm7248/`, with no imports between the two.

**Tech Stack:** Python 3.11+ standard library (`http.client`, `html.parser`, `hashlib`, `gzip`), SQLAlchemy and Alembic through the netview SDK, FastAPI, pydantic, and plain ES modules tested with `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-11-gs105e-plugin-design.md`. Read §4.1 (facts about the pages), §5.3 (session rules) and §6 (features) before any task.

**Interface reference:** this plan names the SDK and GSM7248 interfaces it relies on. When a step says "as GSM7248 does", open that file at the line given and follow its pattern.

## Global Constraints

- Plugin id `gs105e`; folder `plugins/gs105e/`; module name at runtime and in tests `netview_local_plugins.gs105e`; `__init__.py` defines `plugin_class`.
- Import netview only from `netview.sdk` in plugin code (tests may import `netview.infrastructure`). No imports from `plugins/gsm7248`: copy and adapt instead.
- **No new dependencies.** HTTP through `http.client`, HTML through `html.parser`.
- Manifest: name "NETGEAR GS105E", version "0.1.0", `sdk_version=">=1.3,<2"`, capabilities `{API, WEB_UI, STORAGE, JOBS}`, permissions `{DEVICES_READ, NAMES_WRITE, TYPES_WRITE, STORAGE_OWN, API, UI, NETWORK_PROBE}`. Not `TRAFFIC`.
- Tables are prefixed `gs105e_`; the migration revision is `"gs105e_0001"` with `down_revision = None`.
- Settings tabs: exactly "General" and "Connection". The `tab:` in UI code must match.
- The password is a top-level `SecretStr | None`. It never appears in a response, an event, a log line or an exception text that leaves the service.
- With default settings (no password) the plugin registers only the `prune` job and does no network I/O. `setup()` never logs in.
- Requests to the switch go one at a time, with `page_gap_ms` (default 200) between them.
- Event texts start with `"GS105E: "`; events use `EventKind.PLUGIN` and `ip=settings.host`.
- Claims use source `"GS105E"`, name rank 8.
- Colours come only from theme tokens (`--ok --warn --bad --idle --accent --text --text-muted --border --surface …`). The two exceptions: the drawn hardware colours in `faceplate.svg`, and the VLAN palette `["#94a3b8", "#a855f7", "#22b8cf", "#f472b6", "#60a5fa", "#c8a27a", "#818cf8", "#e2e8f0"]`.
- Test file names are unique across the repo: `test_gs105e_*.py` and `gs105e-*.test.mjs`.
- Checks for every task: `uv run pytest plugins/gs105e -q`, `uv run ruff check plugins/gs105e`, `uv run ruff format --check plugins/gs105e`, `uv run mypy plugins/gs105e`, `npm test` (from the repo root; quote paths, since the repo path has a space).
- Commit on branch `feature/gs105e-plugin`. Keep the repo's `user.email`. End every message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A non-ASCII or 20-character password.** The switch's JS MD5 encodes UTF-8, so the hash must match `md5(merge(pw, rand).encode("utf-8"))` (test in Task 2).
2. **The switch reboots while netview is logged in.** The session is lost and the counters drop: netview should log in again once, record no negative or huge rate, and raise exactly one "counters reset" event (test in Task 6).
3. **A wrong password.** Across many poll ticks there must be exactly one login POST and one event. Changing the password, or pressing Test, clears the stop (test in Task 6).
4. **The switch is unreachable from the start.** There's no crash, `summary()` answers with no snapshot, polls back off, and the unreachable event fires once (tests in Tasks 6 and 7).
5. **One page stops parsing** (a firmware change). Only that group fails, with the page named in `summary()["errors"]`; the other groups keep polling, and the password never shows in any error text (test in Task 6).

---

### Task 1: Model types and snapshot codec

**Files:**
- Create: `plugins/gs105e/model/__init__.py`, `model/switch.py`, `model/port.py`, `model/config.py`, `model/snapshot.py`, `model/codec.py`
- Test: `plugins/gs105e/tests/unit/test_gs105e_codec.py`

**Interfaces:**
- Produces (all `@dataclass(frozen=True, slots=True)`, stdlib only, re-exported from `model/__init__.py`):
  - `SwitchInfo(product: str, name: str, serial: str, mac: str, bootloader: str, firmware: str, dhcp: bool, ip: str, mask: str, gateway: str)`
  - `PortStatus(port: int, description: str, up: bool, speed_setting: str, link_mbps: int | None, flow_control: bool, max_mtu: int | None)`. `speed_setting` is the shown text ("Auto", "Disable", "10M Half", …).
  - `PortCounters(port: int, t_ms: int, rx_bytes: int, tx_bytes: int, crc_errors: int)`
  - `PortRates(port: int, t_ms: int, in_bps: float, out_bps: float, crc_delta: int, util_percent: float | None)`. "In" means received by the switch port.
  - `VlanMembers(vid: int, members: tuple[str, ...])`: one code per port, `"U"` untagged, `"T"` tagged, `""` not a member, `"?x"` an unknown character x.
  - `VlanMode = Literal["off", "basic_8021q", "advanced_8021q", "basic_port", "advanced_port"]`
  - `VlanConfig(mode: VlanMode, vlan_ids: tuple[int, ...], shown: VlanMembers | None, pvids: tuple[tuple[int, int], ...])`
  - `RateLimit(port: int, ingress_kbps: int | None, egress_kbps: int | None)`, where `None` means no limit.
  - `QosConfig(mode: Literal["port", "dot1p"], rate_limits: tuple[RateLimit, ...], storm_control: bool)`
  - `IgmpConfig(enabled: bool, vlan: int | None, validate_v3_header: bool, block_unknown: bool, router_port: str | None)`
  - `MirrorConfig(enabled: bool, destination: int | None, sources: tuple[int, ...])`
  - `ManagementConfig(mode: Literal["web", "web_and_utility"], tftp: bool, access_list: tuple[tuple[str, str], ...], power_saving: bool, loop_detection: bool)`
  - `PollGroup = Literal["status", "config"]`; `GROUP_FIELDS = MappingProxyType({"status": ("ports",), "config": ("info", "vlans", "qos", "igmp", "mirror", "management")})`
  - `Snapshot(t_ms: int, groups: frozenset[PollGroup], info: SwitchInfo | None, ports: tuple[PortStatus, ...], vlans: VlanConfig | None, qos: QosConfig | None, igmp: IgmpConfig | None, mirror: MirrorConfig | None, management: ManagementConfig | None)` with `port(n) -> PortStatus | None`.
  - `SCHEMA = "netview.gs105e.snapshot/1"`; `snapshot_to_json(s: Snapshot) -> str`; `snapshot_from_json(text: str) -> Snapshot`, which raises `ValueError` on a wrong schema or malformed body. Follow `plugins/gsm7248/model/codec.py:15-126`.

- [ ] **Step 1: Write the failing tests** in `test_gs105e_codec.py`:
  - `test_round_trip_full_snapshot`: a snapshot holding one of every type survives `snapshot_from_json(snapshot_to_json(s)) == s`.
  - `test_round_trip_partial_status_only` (`groups={"status"}`, config fields `None`).
  - `test_wrong_schema_raises` and `test_bad_literal_raises`: a body with `"mode": "weird"` raises `ValueError`.
- [ ] **Step 2: Run** `uv run pytest plugins/gs105e/tests/unit/test_gs105e_codec.py -q`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** the model files and codec.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(gs105e): model types and snapshot codec`.

### Task 2: Login hash and page parsers

**Files:**
- Create: `plugins/gs105e/auth.py`, `plugins/gs105e/pages.py`
- Test: `plugins/gs105e/tests/unit/test_gs105e_auth.py`, `plugins/gs105e/tests/unit/test_gs105e_pages.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces:
  - `auth.merge(a: str, b: str) -> str` and `auth.login_hash(password: str, rand: str) -> str`, which is `hashlib.md5(merge(password, rand).encode("utf-8")).hexdigest()`. Credit py-netgear-plus (Apache-2.0) and the switch's `login.js` in the docstring.
  - `pages.PageChanged(Exception)` with attribute `page: str` and message `f"{page}: {reason}"`.
  - Path constants: `LOGIN = "/login.cgi"`, `LOGOUT = "/logout.cgi"`, `SWITCH_INFO = "/switch_info.cgi"`, `PORT_STATUS = "/status.cgi"`, `PORT_STATISTICS = "/portStatistics.cgi"`, `VLAN_MODE_PAGES = {"basic_8021q": "/8021qBasic.cgi", "advanced_8021q": "/8021qCf.cgi", "basic_port": "/portBasedBasic.cgi", "advanced_port": "/portBasedAdvanced.cgi"}`, `VLAN_MEMBERSHIP = "/8021qMembe.cgi"`, `PVID = "/portPVID.cgi"`, `QOS = "/qos.cgi"`, `RATE_LIMIT = "/rateLimit.cgi"`, `BROADCAST_FILTER = "/broadCastFilter.cgi"`, `IGMP = "/igmp.cgi"`, `MIRROR = "/mirror.cgi"`, `LOOP = "/loop_detection.cgi"`, `GREEN = "/green_ethernet.cgi"`, `PLUS_UTILITY = "/plus_utility.cgi"`, `ACCESS_CONTROL = "/ip_source.cgi"`. `CONFIG_PAGES` is the tuple of the config group's paths in the order the collector reads them.
  - `is_login_page(html: str) -> bool`: true for the "Redirect to Login" page (fixture `logged_out.html`) and for the login form (`id='rand'`).
  - `LoginPage(rand: str, title: str, firmware: str | None)` and `parse_login(html: str) -> LoginPage`. Firmware comes from the `?a1.6.0.11` asset query.
  - `parse_switch_info(html) -> SwitchInfo`
  - `parse_port_status(html) -> tuple[PortStatus, ...]`
  - `parse_port_statistics(html, t_ms) -> tuple[PortCounters, ...]`
  - `parse_vlan_mode(page_html: Mapping[str, str]) -> VlanMode` (keys are the `VLAN_MODE_PAGES` keys; checked radio `status=Enable`)
  - `parse_vlan_membership(html) -> tuple[tuple[int, ...], VlanMembers | None]`
  - `parse_pvids(html) -> tuple[tuple[int, int], ...]`
  - `parse_qos(qos_html, rate_html, broadcast_html) -> QosConfig`
  - `parse_igmp(html) -> IgmpConfig`
  - `parse_mirror(html) -> MirrorConfig`
  - `parse_management(plus_html, access_html, green_html, loop_html) -> ManagementConfig`
  - Every parser raises `PageChanged(page, reason)` when an element it needs is missing.
- Approach: one private `html.parser.HTMLParser` subclass collects `<title>`, all `<input>` attributes (name, id, type, value, checked), each `<select>`'s options and selected value, and the `tr.portID` rows as (cell texts, hidden input values). Parsers read from that result. Decoding:
  - **Status:** speed codes 1–6 are Auto, Disable, 10M Half, 10M Full, 100M Half, 100M Full. Linked "1000M"/"100M"/"10M" give 1000/100/10; "No Speed" gives `None`; status "Up" gives `up=True`.
  - **Statistics:** the counter is `high * 2**32 + low` for each of rx, tx and crc.
  - **Rate limits:** codes 1–12 are None, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288 kbps.
  - **Membership:** `hiddenMem` characters: `"1"` is "U", `"0"` is "", `"2"` is "T"; anything else is `"?c"`. Only `"1"` is verified (spec §4.1).
  - **Mirror:** `select mirroring` value 0 is on; destination from `DestiPort`'s selected value; sources are the ports with `"1"` in `hiddenMem`.
  - **IGMP:** `status` radio value 1 is on; empty `VLAN_ID_ENABLED` gives `None`; `ROUTER_PORT` with no selected option gives `None`.
  - **Management:** `plusUtility` value 1 is "web"; `tftpflag` value 0 is on; `powerSavingMode` and `loopDetection` value 1 are on. Access rows are the IP/mask pairs in the table (none in the fixture).

- [ ] **Step 1: Write the failing tests.**
  - `test_gs105e_auth.py`:
    - `merge("abc","12") == "a1b2c"`; `merge("", "9") == "9"`.
    - `login_hash("t1e2s3t4"[::2], "1234")` equals `hashlib.md5(b"t1e2s3t4").hexdigest()` (the merge of "test" and "1234").
    - **Review Focus 1:** `login_hash("pässwörd", "123") == hashlib.md5(merge("pässwörd", "123").encode("utf-8")).hexdigest()`, and a 20-character password works.
  - `test_gs105e_pages.py` loads files with `FIX = Path(__file__).resolve().parents[1] / "fixtures" / "fw-1.6.0.11"` and asserts these exact values:
    - `parse_login(login.cgi)`: `rand == "12345678"`, `title == "NETGEAR GS105Ev2"`, `firmware == "1.6.0.11"`.
    - `is_login_page` is true for `logged_out.html` and `login.cgi`, and false for `status.cgi`.
    - `parse_switch_info(switch_info.cgi)` returns `SwitchInfo("GS105Ev2", "GS105E Switch", "SERIAL0000000", "02:00:00:00:00:01", "V1.6.0.2-VB", "V1.6.0.11", False, "192.0.2.1", "255.255.255.0", "192.0.2.2")`.
    - `parse_port_status(status.cgi)` gives five ports. Ports 1 and 2 have `up=True, link_mbps=1000`; ports 3–5 have `up=False, link_mbps=None`. All have `speed_setting == "Auto"`, `flow_control is False`, `max_mtu == 16349` and `description == ""`.
    - `parse_port_statistics(portStatistics.cgi, 1000)`: port 1 has `rx_bytes == 5569902238` and `tx_bytes == 615446200`; port 2 has `rx_bytes == 615854972` and `tx_bytes == 5569725891`; ports 3–5 are zero; every `crc_errors == 0`.
    - `parse_vlan_mode({...the four fixtures...}) == "off"`; `parse_vlan_membership(8021qMembe.cgi) == ((1,), VlanMembers(1, ("U",)*5))`; `parse_pvids(portPVID.cgi) == tuple((p, 1) for p in range(1, 6))`.
    - `parse_qos(...)` returns `QosConfig("dot1p", tuple(RateLimit(p, None, None) for p in 1..5), False)`.
    - `parse_igmp(igmp.cgi)` returns `IgmpConfig(True, None, False, False, None)`.
    - `parse_mirror(mirror.cgi)` returns `MirrorConfig(False, None, ())`.
    - `parse_management(...)` returns `ManagementConfig("web", False, (), False, False)`.
    - A hand-edited membership string `"1203x"` decodes to `("U", "T", "", "?3", "?x")`.
    - `parse_port_status("<html></html>")` raises `PageChanged` whose `.page == "/status.cgi"`.
- [ ] **Step 2: Run** `uv run pytest plugins/gs105e/tests/unit -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `auth.py` and `pages.py`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(gs105e): login hash and page parsers, tested on the captured pages`.

### Task 3: Analysis rules

**Files:**
- Create: `plugins/gs105e/analysis.py`
- Test: `plugins/gs105e/tests/unit/test_gs105e_analysis.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces:
  - Text constants:
    - `PREFIX = "GS105E: "`
    - `UNREACHABLE_TEXT = "GS105E: the switch is not answering"`
    - `REACHABLE_TEXT = "GS105E: the switch is answering again"`
    - `LOGIN_FAILED_TEXT = "GS105E: login failed; polling stopped until the password or address changes or Test connection is pressed"`
    - `PAUSED_ANOTHER_LOGIN_TEXT = "GS105E: paused, another login keeps ending netview's session"`
    - `COUNTERS_RESET_TEXT = "GS105E: counters reset (switch rebooted or statistics cleared)"`
  - `ChangeKind(StrEnum)`: `LINK_UP, LINK_DOWN, SPEED, CRC, FIRMWARE, CONFIG, ACCESS_LIST`; `Change(kind: ChangeKind, text: str, port: int | None = None)` (frozen, slots).
  - `compute_rates(prev: PortCounters, cur: PortCounters, link_mbps: int | None) -> PortRates | None`: returns None if `cur.t_ms <= prev.t_ms` or any of the three counters went backwards. Otherwise bits per second are `delta_bytes * 8 / seconds`, `crc_delta = cur - prev`, and `util_percent = max(in, out) / (link_mbps * 1e6) * 100`, or None when the link speed is unknown.
  - `counters_reset(prev: Mapping[int, PortCounters], cur: Sequence[PortCounters]) -> bool`: True when at least one port had `rx+tx > 0` before, and every such port now has a lower `rx+tx`.
  - `crc_alerts(rates: Sequence[PortRates], threshold: int, last_alert_ms: MutableMapping[int, int], now_ms: int) -> list[Change]`: one `CRC` change per port whose `crc_delta > threshold`, at most once per port per `3_600_000` ms (it updates `last_alert_ms`). Text: `f"GS105E: port {p} CRC errors rising ({d} in the last poll)"`.
  - `ip_allowed(ip: str, access_list: Sequence[tuple[str, str]]) -> bool`: an empty list allows everything; otherwise the IP must be inside one ip/mask (use `ipaddress`).
  - `diff(prev: Snapshot | None, cur: Snapshot, *, own_ip: str | None) -> list[Change]`: `prev is None` gives `[]`. A group is compared only when both snapshots hold it. Texts:
    - `"GS105E: port {p} link up at {mbps} Mb/s"`
    - `"GS105E: port {p} link down"`
    - `"GS105E: port {p} speed {a} → {b} Mb/s"`
    - `"GS105E: firmware {a} → {b}"`
    - one `CONFIG` change per differing setting, for example `"GS105E: port 3 PVID 1 → 20"`, `"GS105E: VLAN mode off → advanced_8021q"`, `"GS105E: mirroring turned on"`, `"GS105E: loop detection turned off"`, `"GS105E: port 2 ingress limit none → 65536 kbps"`, `"GS105E: storm control turned on"`, `"GS105E: IGMP snooping turned off"`, `"GS105E: power saving turned on"`, `"GS105E: management mode web → web_and_utility"`
    - `ACCESS_LIST` `"GS105E: Access Control no longer includes netview's address {own_ip}; the next login may be refused"` when the list changed and `ip_allowed(own_ip, new) is False`.
  - `merge_snapshot(base: Snapshot | None, part: Snapshot) -> Snapshot`: as `plugins/gsm7248/analysis.py:275-283`.
  - **No loop-detected event.** Netgear's help text says the switch reports a loop only by blinking the port LEDs, and no page shows a per-port loop state. Spec §6.5 makes the event conditional on such a state, so phase 1 reports only loop detection turned on or off.

- [ ] **Step 1: Write the failing tests:**
  - **Rates:** a 15 s step with 1_875_000 bytes received gives `in_bps == 1_000_000.0` and, at 1000 Mb/s, `util_percent == 0.1`. A backward rx gives None. Equal `t_ms` gives None. `link_mbps=None` gives `util_percent is None`.
  - **Counters reset:** True when ports 1 and 2 drop and 3–5 stay 0. False when only port 1 drops. False when nothing had traffic before.
  - **CRC alerts:** the threshold is exceeded only above `threshold`. A second alert within the hour is suppressed, and one after 3_600_001 ms fires.
  - **IP allowed:** `ip_allowed("192.168.1.50", [])` is True; `("192.168.1.50", [("192.168.1.0", "255.255.255.0")])` is True; `("10.0.0.5", same)` is False.
  - **Diff:**
    - the baseline is `[]`;
    - port 3 going up at 1000 gives exactly the link-up text;
    - 1000 → 100 gives the SPEED text;
    - a PVID change gives the CONFIG text above;
    - a status-only snapshot compared with a config-only one gives `[]`;
    - an access list that excludes the own IP gives one ACCESS_LIST change.
  - **Merge:** a status part keeps the base's config fields.
- [ ] **Step 2: Run** `uv run pytest plugins/gs105e/tests/unit/test_gs105e_analysis.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `analysis.py`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(gs105e): rates, reset detection, CRC alerts and change summaries`.

### Task 4: HTTP session, transport and fake switch

**Files:**
- Create: `plugins/gs105e/client.py`, `plugins/gs105e/tools/__init__.py` (empty), `plugins/gs105e/tools/fake_switch.py`
- Test: `plugins/gs105e/tests/unit/test_gs105e_client.py`

**Interfaces:**
- Consumes: `auth.login_hash`, `pages.parse_login`, `pages.is_login_page`, `pages.LOGIN`, `pages.LOGOUT`, `pages.PageChanged`.
- Produces:
  - `Fetch = Callable[[str, int, str, str, bytes | None, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]`: `(host, port, method, path, body, headers, timeout_s) -> (status, lower-cased headers, body)`.
  - `http_fetch: Fetch`, the real transport. It is `http.client.HTTPConnection`, `Accept-Encoding: gzip`, `Connection: close`, reads at most `MAX_BODY = 1 << 20`, and gunzips when `content-encoding: gzip` or the body starts with `\x1f\x8b`. It maps `http.client.HTTPException` to `MalformedReply` and lets `OSError` through. Like `plugins/starlink/client.py:30-42`.
  - Errors: `SwitchError(Exception)`, `Unreachable(SwitchError)`, `AuthFailed(SwitchError)`, `UnsupportedSwitch(SwitchError)`, `SessionLost(SwitchError)`, `MalformedReply(Exception)`. `pages.PageChanged` is re-raised as is.
  - `class SwitchSession(host: str, port: int, password: str, fetch: Fetch, *, timeout_s: float = 8.0, gap_s: float = 0.2, sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic)`
  - `login() -> LoginPage`:
    - GET `/login.cgi`;
    - `UnsupportedSwitch` unless the title contains `"GS105E"` and `rand` is present;
    - POST `password=<login_hash>` with the form content type;
    - stores the `SID` cookie; with no `SID` in `set-cookie`, raises `AuthFailed("login refused")`.
  - `get(path: str) -> str`:
    - sends the cookie and decodes UTF-8 with replacement;
    - raises `SessionLost` when `is_login_page(text)`;
    - a non-200 status raises `PageChanged(path, f"HTTP {status}")`;
    - `MalformedReply` raises `PageChanged(path, "malformed reply")`;
    - `OSError` raises `Unreachable(type(exc).__name__)`, with no message text, so the password can never leak through it.
  - `logout() -> None` is best effort and never raises; `logged_in: bool`.
  - Every request waits until `gap_s` has passed since the previous one.
  - `tools/fake_switch.py`: `class FakeSwitch(fixtures: Path, password: str = "secret")`, a `Fetch`-compatible callable.
    - It serves `fixtures/<name>` for GET `/<name>` with a valid `SID`, and `logged_out.html` without one; it serves `login.cgi` to anyone.
    - POST `/login.cgi` sets `set-cookie: SID=s<n>; PATH=/` only when the body is `password=` plus `login_hash(password, "12345678")`.
    - GET `/logout.cgi` drops that SID.
    - Test controls: `.requests: list[tuple[str, str]]` (method, path), `.drop_sessions()`, `.down: bool` (raises `OSError` when True), `.override: dict[str, str]` (path to body), `.tick: Callable[[], None] | None` (called on each statistics read, to let tests change counters).
    - It also has a `main()` with `--help`, `--port` (default 8105), `--fixtures` and `--password`, which serves the same behaviour on `127.0.0.1` through `http.server.ThreadingHTTPServer`, for browser checks.

- [ ] **Step 1: Write the failing tests** (using `FakeSwitch(FIX)` and a `sleep` that records instead of sleeping):
  - Login with "secret" sets `logged_in`, and the POST body is `password=` plus the expected hash for rand `12345678`.
  - A wrong password raises `AuthFailed`.
  - A title override without "GS105E" raises `UnsupportedSwitch`.
  - `get("/status.cgi")` returns the fixture text.
  - After `drop_sessions()`, `get` raises `SessionLost`.
  - `.down = True` raises `Unreachable`, and `str(exc)` does not contain "secret".
  - Two quick requests with `gap_s=0.2` record a sleep of about 0.2.
  - `logout()` with `.down = True` does not raise.
  - `http_fetch` against a local `socket` server thread:
    - a normal gzip reply with `Content-Encoding: gzip` comes back decoded;
    - a reply of bare gzip bytes with no status line raises `MalformedReply` (spec §4.1, `product_registration_popup.cgi`).
- [ ] **Step 2: Run** `uv run pytest plugins/gs105e/tests/unit/test_gs105e_client.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `client.py` and `tools/fake_switch.py`.
- [ ] **Step 4: Run** the same command, then `uv run python -I plugins/gs105e/tools/fake_switch.py --help`. Expected: PASS, and the help text prints.
- [ ] **Step 5: Commit** `feat(gs105e): switch session over the web pages, real and fake transports`.

### Task 5: Settings, storage, migration, plugin shell, and a clean capture tool

**Files:**
- Create: `plugins/gs105e/settings.py`, `storage.py`, `migrations/versions/0001_initial.py`, `plugin.py`, `__init__.py`, `static/ui.js` (a stub `export default function register(ui) {}` that Task 8 replaces)
- Modify: `plugins/gs105e/tools/capture.py` (lint only, no behaviour change)
- Test: `plugins/gs105e/tests/unit/test_gs105e_settings.py`, `plugins/gs105e/tests/integration/test_gs105e_storage.py`, `plugins/gs105e/tests/integration/test_gs105e_plugin_load.py`

**Interfaces:**
- Consumes: Task 1 types and codec.
- Produces:
  - **Settings tabs and groups:** `GENERAL_TAB = "General"`, `CONNECTION_TAB = "Connection"`. Groups: `CONNECTION = setting_group("Switch", tab=CONNECTION_TAB)`, `POLLING = setting_group("Polling", tab=GENERAL_TAB)`, `RETENTION = setting_group("Traffic history", tab=GENERAL_TAB)`, `ALERTS = setting_group("Alerts", tab=GENERAL_TAB)`. Use `settings_tabs([GENERAL_TAB, CONNECTION_TAB], then=settings_requirements(required=["host", "password"]))`.
  - **`Gs105eSettings` fields:**
    - `host: str = "192.168.1.3"`
    - `port: int = 80` (1–65535)
    - `password: SecretStr | None = None`
    - `counters_interval_s: int = 15` (5–300)
    - `status_interval_s: int = 30` (10–600)
    - `config_interval_s: int = 300` (60–3600)
    - `page_gap_ms: int = 200` (0–2000)
    - `pause_minutes: int = 15` (1–240)
    - `raw_retention_h: int = 24` (1–168)
    - `rollup_retention_d: int = 30` (1–365)
    - `crc_alert_threshold: int = 10` (1–1_000_000)

    Methods: `password_text() -> str | None` (`""` gives None) and `configured() -> bool` (host and password set). The password description says "Stored in netview's local database. Disabling this plugin takes effect after a restart; use Pause on the Switch page to free the switch's login at once." (spec §5.3).
  - **Storage:**
    - `metadata = sa.MetaData()`.
    - `gs105e_port_samples`: PK `(switch_id, port, resolution, t_ms)`; `rx_bytes`, `tx_bytes`, `crc_errors` are BigInteger not null; `in_bps`, `out_bps`, `util_percent` are Float nullable; `crc_delta` is Integer nullable.
    - `gs105e_snapshots`: `switch_id` String PK, `t_ms` BigInteger, `body` Text.
    - `storage_spec() -> StorageSpec(metadata, Path(__file__).parent / "migrations" / "versions")`.
    - `class SwitchStore(uow_factory: Callable[[], PluginUnitOfWork], switch_id: str)` with:
      - `add_samples(rates: Sequence[PortRates], counters: Mapping[int, PortCounters]) -> None`
      - `samples(port: int, from_ms: int, to_ms: int, resolution: Literal["raw", "5m"]) -> list[PortRates]`
      - `rollup_and_prune(now_ms: int, raw_keep_ms: int, rollup_keep_ms: int) -> int`
      - `save_snapshot(s: Snapshot) -> None` and `load_snapshot() -> Snapshot | None`

      Copy the SQL shape of `plugins/gsm7248/storage.py:63-239`, including the 5-minute buckets (`BUCKET_MS = 300_000`), `max()` of byte counts, `sum()` of `crc_delta` and `avg()` of rates.
    - Migration `revision = "gs105e_0001"`, `down_revision = None`, creating both tables with an explicit `sa.PrimaryKeyConstraint`.
  - **`plugin.py`:** `class Gs105ePlugin(Plugin)` with the manifest from Global Constraints and `settings_model = Gs105eSettings`.
    - `__init__` sets `self._service = None` and `self.fetch = _client.http_fetch`, where `from . import client as _client` and the attribute is read **at instance creation**, so tests can patch `netview_local_plugins.gs105e.client.http_fetch`.
    - `storage()`, `ui()` (`UiContribution(static_dir, "ui.js")`), `router()` (an empty `APIRouter()` until Task 7) and `jobs()` (only `JobSpec("prune", 3600, …, timeout_s=120)` while unconfigured) all work before `setup()`.
    - `setup(ctx)` only stores `ctx.settings` for now; Task 6 builds the service there. `shutdown()` calls the service's `shutdown()` when there is a service.
  - `__init__.py`: a docstring, `from .plugin import Gs105ePlugin`, and `plugin_class = Gs105ePlugin`.

- [ ] **Step 1: Write the failing tests:**
  - **Settings:** `Gs105eSettings.model_validate({})` succeeds with `configured() is False`; with a password it is True; `password_text()` unwraps; the schema's tabs are exactly `["General", "Connection"]`; the password field's schema is `writeOnly`/`format: password` (as `plugins/gsm7248/tests/unit/test_gsm7248_settings.py` checks).
  - **Storage** (file SQLite plus `upgrade_core` and `upgrade_plugin(engine, "gs105e", storage_spec().versions_dir)`, like `plugins/gsm7248/tests/integration/test_storage.py`):
    - samples come back in `t_ms` order for a port;
    - a rollup over complete buckets writes `5m` rows, and `sum(crc_delta)` per bucket is kept;
    - pruning deletes raw rows older than the keep window and returns the count;
    - the snapshot round-trips;
    - a second `rollup_and_prune` writes nothing new.
  - **Plugin load:** `check_plugin(Gs105ePlugin)` passes; the exact manifest; `jobs()` names are `["prune"]` with default settings; not built in; folder discovered (`discover_plugin_classes(group="none", extra_dirs=[tmp_path])` after `copytree`); as `plugins/gsm7248/tests/integration/test_plugin_load.py`.
- [ ] **Step 2: Run** `uv run pytest plugins/gs105e -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the files listed. Then fix `tools/capture.py` until ruff, format and mypy pass, without changing what it does.
- [ ] **Step 4: Run** `uv run pytest plugins/gs105e -q`, `uv run ruff check plugins/gs105e`, `uv run ruff format --check plugins/gs105e` and `uv run mypy plugins/gs105e`. Expected: all clean. Also run `uv run pytest plugins/gsm7248 -q`: its API test loads every folder plugin, so it must still pass.
- [ ] **Step 5: Commit** `feat(gs105e): settings, storage and the plugin shell; capture tool lint-clean`.

### Task 6: Collector and service

**Files:**
- Create: `plugins/gs105e/collector.py`, `plugins/gs105e/service.py`
- Modify: `plugins/gs105e/plugin.py` (`setup`, `jobs`, `on_settings_changed`, `shutdown`)
- Test: `plugins/gs105e/tests/unit/test_gs105e_collector.py`, `plugins/gs105e/tests/integration/test_gs105e_service.py`

**Interfaces:**
- Consumes: Tasks 1–5. From the SDK: `PluginContext`, `EventKind.PLUGIN`, `NameClaim`, `TypeClaim`, `Hint`, `ctx.core.devices()`, `ctx.core.claim`, `ctx.core.add_event(kind, text, ip)`, `ctx.clock.now_ms()`, `ctx.log`.
- Produces:
  - **`collector.py`** (module functions):
    - `read_counters(session: SwitchSession, t_ms: int) -> tuple[PortCounters, ...]`
    - `read_status(session, t_ms) -> Snapshot` (`groups={"status"}`)
    - `read_config(session, t_ms) -> Snapshot` (`groups={"config"}`)

    Each one GETs the pages from Task 2's constants in `CONFIG_PAGES` order and calls the parsers.
  - **`service.py`:**
    - Constants: `SOURCE = "GS105E"`, `SWITCH_ID = "gs105e"`, `NAME_RANK = 8`, `MAX_BACKOFF_S = 300`, `MASK = "********"`, `RELOGIN_WINDOW_MS = 600_000`, `TESTED_FIRMWARE = frozenset({"V1.6.0.11"})`.
    - `class Gs105eService(ctx: PluginContext, store_factory: Callable[[str], SwitchStore], fetch: Fetch)`, with one `threading.Lock` held for each whole poll and for `test_connection`, as `plugins/gsm7248/service.py:55-247` does.
    - Job methods: `poll_counters()`, `poll_status()`, `poll_config()`, `prune()`.
    - Controls: `start_poll_all() -> bool` (False when busy, paused, stopped or unconfigured), `pause(reason: Literal["user", "another_login"] = "user") -> None`, `resume() -> None`, `test_connection() -> dict[str, str]`, `settings_changed() -> None`, `shutdown() -> None`.
    - Read models: `summary() -> dict`, `ports() -> list[dict]`, `port(n: int) -> dict | None`, `samples(n, from_ms, to_ms, resolution) -> list[dict]`, `config() -> dict`.
  - **Rules** (spec §5.3 and §5.4):
    - **Poll gate:** a poll runs only when configured, not stopped after a login failure, not paused, and not backing off. It logs in on demand.
    - **`SessionLost`:** if the previous re-login was less than `RELOGIN_WINDOW_MS` ago, call `pause("another_login")` and raise `PAUSED_ANOTHER_LOGIN_TEXT` once. Otherwise log in again, record the time, and retry that group once.
    - **`AuthFailed`:** stop polling, raise `LOGIN_FAILED_TEXT` once, and make no further login attempts until `settings_changed()` (when host, port or password differ) or a successful `test_connection()`.
    - **`Unreachable`:** per-group backoff `min(MAX_BACKOFF_S, interval * 2**failures)`. The first failure flips `reachable` to False and raises `UNREACHABLE_TEXT`; recovery raises `REACHABLE_TEXT`.
    - **`PageChanged`:** record `errors[group] = str(exc)` (the page path and reason); no backoff. A group's error clears when it next succeeds.
    - **Masking:** every error string is passed through a `_scrub` that replaces the password with `MASK`.
    - **Counters:** compute rates from the previous counters. When `counters_reset` is true, raise `COUNTERS_RESET_TEXT` and store no rates for that step. Store samples, then raise `crc_alerts` using `settings.crc_alert_threshold`.
    - **Status and config:** `merge_snapshot`, `diff(..., own_ip=<the address netview reaches the switch from>)`, events, `save_snapshot`, then claims. For `own_ip` use `ctx.core.host().ip` when available, else None, which skips the ACCESS_LIST check. `FakeCore` lacks `host()`, so wrap the call in `getattr`/`try`.
    - **Claims:** find the device in `ctx.core.devices()` by `ip == settings.host`, else by `mac` equal to `info.mac`, ignoring case. Claim `NameClaim(key, info.name or "GS105E", SOURCE, NAME_RANK, now)`, `TypeClaim(key, "switch", "NETGEAR GS105E web interface", SOURCE)` and `Hint(key, f"NETGEAR {info.product} firmware {info.firmware} serial {info.serial}", SOURCE)`, and skip them when they are unchanged since the last claim.
    - **`pause()`:** log out (best effort) and set `paused_until_ms = now + pause_minutes*60_000` with the reason. Polls skip until that time; `resume()` clears it. `shutdown()` and `settings_changed()` (when the connection fields changed) log out.
    - **`summary()` keys:** `configured, host, reachable (bool|None), polling (lock held), login ("ok"|"failed"|"paused"|"not_configured"|"unknown"), paused_until_ms, pause_reason, last_poll_ms, errors {group: text}, switch {name, product, firmware, firmware_tested, serial, mac, bootloader} | None, ports {total: 5, up}, throughput_bps {in, out}`.
    - **`ports()`:** each `PortStatus` field, plus `in_bps`, `out_bps`, `util_percent`, `crc_errors`, `crc_delta`, `pvid`, `vlan_member`, `ingress_kbps`, `egress_kbps` and `mirror` ("source"|"destination"|None).
    - **`samples`:** the default window is the last hour for raw and the last day for 5m; rows are `asdict(PortRates)`.
  - **`plugin.py` jobs when configured:**
    - `counters` (`counters_interval_s`, initial delay 2 s)
    - `status` (`status_interval_s`, 5 s)
    - `config` (`config_interval_s`, 8 s)
    - `prune`

    Each has `timeout_s=min(2*interval, 120)`. `setup` builds `Gs105eService(ctx, lambda sid: SwitchStore(ctx.unit_of_work, sid), self.fetch)`. `on_settings_changed` stores the settings and calls `service.settings_changed()`.

- [ ] **Step 1: Write the failing tests.**
  - **Collector:** against `FakeSwitch(FIX)`, `read_config` returns a snapshot equal to the Task 2 parser values, and requests every config page exactly once.
  - **Service** (fixture as `plugins/gsm7248/tests/integration/test_service.py:73-138`: file SQLite engine, `upgrade_plugin(... "gs105e" ...)`, a real `DefaultPluginContext` for its `unit_of_work`, then `FakePluginContext(settings, snmp=FakeSnmpClient([]), core=FakeCore([...]), uow_factory=real.unit_of_work, clock=FakeClock(), plugin_id="gs105e")`, with the transport `FakeSwitch(FIX)`). Tests:
    - `test_first_polls_are_a_baseline`: status then config produce no events and claim name "GS105E Switch", type "switch" and the hint for the device whose ip is `settings.host`.
    - `test_link_down_event`: override `status.cgi` with port 1 changed to Down and "No Speed"; a status poll raises `"GS105E: port 1 link down"`.
    - `test_rates_after_two_counter_polls`: advance the clock 15 s and bump port 1 rx through `.tick`; `ports()[0]["in_bps"] > 0`; samples are stored.
    - **Review Focus 2** `test_reboot_relogs_once_and_reports_reset`:
      - `drop_sessions()` plus counters overridden to lower values;
      - the next counters poll logs in again (exactly one more POST `/login.cgi` in `.requests`);
      - it stores no rates for that step;
      - `COUNTERS_RESET_TEXT` appears exactly once.
    - `test_second_loss_within_window_pauses`: drop sessions twice within 10 minutes. The second loss gives `summary()["login"] == "paused"`, `pause_reason == "another_login"` and one `PAUSED_ANOTHER_LOGIN_TEXT`; further polls make no requests until `paused_until_ms`.
    - **Review Focus 3** `test_wrong_password_logs_in_once`: the settings password is "wrong"; 10 polls across all groups leave exactly one POST `/login.cgi` and one `LOGIN_FAILED_TEXT`. After `settings_changed()` with the password "secret", the next poll logs in and succeeds. Separately, a successful `test_connection()` clears the stop.
    - **Review Focus 4** `test_unreachable_from_start`:
      - with `.down = True`, `summary()` before any poll answers with `reachable is None, switch is None`;
      - after polls, `reachable is False` with one `UNREACHABLE_TEXT`;
      - a poll inside the backoff window makes no request;
      - after `.down = False`, the clock is advanced past the backoff and `REACHABLE_TEXT` appears.
    - **Review Focus 5** `test_one_page_changed_others_continue`:
      - override `/igmp.cgi` with `"<html></html>"`;
      - a config poll leaves `summary()["errors"]["config"]` containing `"/igmp.cgi"`;
      - status and counters polls still succeed;
      - no error text contains the password. Make the fake raise `OSError("secret")` once and check that no `summary()` text or event contains "secret".
    - `test_pause_logs_out_and_resume`: `pause()` sends GET `/logout.cgi`, and polls during the pause make no requests; after `resume()` they do.
    - `test_snapshot_survives_restart`: a new service on the same engine raises no events on its first status poll.
- [ ] **Step 2: Run** `uv run pytest plugins/gs105e -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `collector.py`, `service.py`, and the `plugin.py` wiring.
- [ ] **Step 4: Run** `uv run pytest plugins/gs105e -q` and `uv run mypy plugins/gs105e`. Expected: PASS and clean.
- [ ] **Step 5: Commit** `feat(gs105e): polling service with session, pause, backoff, events and claims`.

### Task 7: API routes

**Files:**
- Create: `plugins/gs105e/routes.py`
- Modify: `plugins/gs105e/plugin.py` (`router()` returns `build_router(self._service)` once set up)
- Test: `plugins/gs105e/tests/integration/test_gs105e_api.py`

**Interfaces:**
- Consumes: the `Gs105eService` methods from Task 6.
- Produces: `build_router(service: Gs105eService) -> APIRouter`, with plain `def` routes:
  - `GET /summary`, `GET /ports`, `GET /config`.
  - `GET /ports/{n}/samples` (declared before `/ports/{n}`): `from_ms: int | None`, `to_ms: int | None`, `resolution` matching `^(raw|5m)$`.
  - `GET /ports/{n}`. `n` must be 1–5, otherwise 404 `{"detail": "unknown port {n}"}`.
  - `POST /poll`: 202 `{"started": true}`, or 409 `{"detail": "poll already running"}` / `{"detail": "polling is paused"}` / `{"detail": "not configured"}`.
  - `POST /pause` returns `{"paused_until_ms": int}`; `DELETE /pause` returns `{"paused_until_ms": null}`.
  - `POST /test` takes an optional body that is ignored, and returns `test_connection()`.
  - The `X-Netview` check is core middleware; the plugin does nothing for it.

- [ ] **Step 1: Write the failing tests** with the full app, as `plugins/gsm7248/tests/integration/test_api.py:48-73`:
  - `monkeypatch.setattr("netview_local_plugins.gs105e.client.http_fetch", FakeSwitch(FIX))` **before** `create_application(AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24", plugins={"gs105e": {"password": "secret", "host": "192.168.1.3"}}, plugin_dirs=[PLUGINS]))`.
  - `TestClient(..., headers={"X-Netview": "1"})`.

  Tests:
  - `/summary` answers before any poll, with `configured: true`.
  - After `POST /poll` and waiting until `polling` is false, `/ports` has 5 entries and `/ports/1` has `link_mbps == 1000`.
  - `/ports/9` returns 404.
  - `/config` has `vlans.mode == "off"` and `qos.mode == "dot1p"`.
  - `POST /pause` then `POST /poll` returns 409 "polling is paused"; `DELETE /pause` then `POST /poll` returns 202.
  - `POST /test` returns `{"ok": "true", ...}` with the model "GS105Ev2".
  - `POST /poll` without `X-Netview` returns 403.
  - **No response body contains "secret"**: scan the bodies of all of the above.
  - A second app with no password: `/summary` has `configured: false`, and no request reached the fake.
- [ ] **Step 2: Run** `uv run pytest plugins/gs105e/tests/integration/test_gs105e_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `routes.py` and the router wiring.
- [ ] **Step 4: Run** `uv run pytest plugins -q`. Expected: PASS, including the GSM7248 and Starlink suites.
- [ ] **Step 5: Commit** `feat(gs105e): API under /api/v1/plugins/gs105e`.

### Task 8: Web UI

**Files:**
- Create: `plugins/gs105e/static/port-grid.js`, `static/page.js`, `static/report.js`, `static/gs105e.css`
- Modify: `plugins/gs105e/static/ui.js` (replace the stub)
- Test: `plugins/gs105e/tests/js/gs105e-faceplate.test.mjs`, `gs105e-ui.test.mjs`, `gs105e-page.test.mjs`, `gs105e-report.test.mjs`

**Interfaces:**
- Consumes: the API from Task 7; the host slot contract (`src/netview/presentation/web/static/js/slots.js:3-11`: `dashboard.tile {render(state)}`, `page {id, title, mount(el, ctx) -> {update, destroy}}`, `report.live-section {id, draw(el, {ip, device, state})}`, `settings.section {title, tab, render(body, {apiBase, apiSend, util})}`); `ui.util.esc`, `fmtRate`, `fmtAgo`, and `lineChart(el, {label, series, fmt, height})` (`chart.js:130`).
- Produces:
  - **`port-grid.js`** (pure; no imports):
    - `FACE_W = 940`, `FACE_H = 270`, `JACK_X = [200, 340, 480, 620, 784]`, `JACK_Y = 104`, `JACK_W = 130`, `JACK_H = 118`, `POWER_LED = [30, 192, 26, 16]` (from the `faceplate.svg` header);
    - `jackBox(n) -> {left, top, width, height} | null` in percent;
    - `ledState(linkMbps) -> {left: boolean, right: boolean}`: 1000 gives both, 100 left, 10 right, null neither;
    - `ledBoxes(n) -> {left, right}` in percent;
    - `speedShort(mbps)` gives "1G", "100M", "10M" or "—";
    - `portState(port) -> {cls: "up"|"down"|"disabled", words}`;
    - `vlanColors(vids)`, using the palette from Global Constraints;
    - `jackHtml(port, esc, mode: "status"|"vlan", colors)`: a `<button type="button" class="jack …" data-port="N" style="…" title aria-label>` with the speed text, LED dots and mirror badge;
    - `portChartSeries(samples)`: In `--series-1`, Out `--series-2`.
  - **`report.js`:** `reportModel(summary, ip) -> null | {heading, tiles: [{k, v}], link}` (null unless `ip === summary.host`) and `drawReport(box, model)`, which uses `textContent` only.
  - **`page.js`:** `createPage(ui, store) -> {id: "switch", title: "GS105E", mount(el)}`. The page holds:
    - the faceplate inside `.faceplate-scroll` with `<img src=new URL("./faceplate.svg", import.meta.url)>`;
    - the Status/VLAN toggle, remembered in `localStorage` key `netview.gs105e.faceView` under try/catch;
    - a Pause/Resume button with a countdown, Poll now, and the port detail panel with a `lineChart` for 1 h / 24 h / 7 d;
    - the configuration sections in spec §6.4 order, with "VLANs off" when the mode is off;
    - per-group errors.

    A dot over `POWER_LED` uses `--ok` when `reachable` is true and `--bad` when it is false, with a word in its title.

    Exported pure helpers: `pauseLabel(summary, now) -> string`, `statusBanner(summary) -> {cls, text} | null` (unreachable, login failed, paused, untested firmware; `pause_reason == "another_login"` gives the text "Paused: another login") and `configSectionsHtml(config, esc) -> string`. After its own POSTs the page re-fetches every 1.5 s until `summary.polling` is false (up to 60 s), because plugins cannot push SSE state (`plugins/gsm7248/static/page.js:537-560`).
  - **`ui.js`:**
    - `createStore(ui, now)` fetches `/summary`, `/ports` and `/config`, at most every 10 s unless forced.
    - `tileHtml(summary, esc, fmtRate)`: "GS105E", ports up out of 5, throughput. Bad states use `class="v bad"` (unreachable, login failed) or `class="v warn"` (paused), with `⚠` and a word.
    - `renderConnection` (the Test connection button) and `register(ui)`, which injects `gs105e.css` (guarding `document`) and registers `dashboard.tile`, `page`, `report.live-section` (`id: "gs105e-summary"`) and `settings.section` with `tab: "Connection"`.
  - **`gs105e.css`:** theme tokens only (Global Constraints). `.faceplate` has `aspect-ratio: 940 / 270` and `min-width: 560px`, inside `.faceplate-scroll { overflow-x: auto; max-width: 100% }`, so at 375 px only the faceplate scrolls.

- [ ] **Step 1: Write the failing tests** (header as `plugins/gsm7248/tests/js/gsm7248-ui.test.mjs`, using `fakeUi` from there):
  - **Faceplate:**
    - `jackBox(1)` equals `{left: 21.277, top: 38.519, width: 13.83, height: 43.704}` (rounded to 3 places, as GSM7248's `pct`);
    - `jackBox(6)` is null;
    - `ledState(1000)` is `{left: true, right: true}`, `ledState(100)` is `{left: true, right: false}`, `ledState(10)` is `{left: false, right: true}`, and `ledState(null)` has both false;
    - `jackHtml` for a down port contains a word, not only a class;
    - `speedShort(null) === "—"`.
  - **UI:** `register(fakeUi)` registers the four slots, and the settings section has `tab === "Connection"`; `tileHtml` for a `reachable: false` summary contains `class="v bad"` and a word; paused gives `warn`.
  - **Page:** `pauseLabel` gives "Paused for 14 min" at the right time; `statusBanner` with `login: "failed"` returns a bad banner; `configSectionsHtml` with the fixture config contains "VLANs off" and "802.1p/DSCP", and escapes `<` in a port description.
  - **Report:** null for another IP; tiles for the switch IP.
- [ ] **Step 2: Run** `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the static files.
- [ ] **Step 4: Run** `npm test`. Expected: PASS (all suites).
- [ ] **Step 5: Commit** `feat(gs105e): Switch page, faceplate overlays, tile, report section and settings test`.

### Task 9: Browser check, live check and setup notes

**Files:**
- Create: `docs/gs105e-setup.md`
- Modify: `R:\source\claude projects\HomeLab\.claude\launch.json` (add a `gs105e-fake` configuration that runs `uv run python -I plugins/gs105e/tools/fake_switch.py --port 8105` in the netview folder). It is outside the repo, so it is not committed.

- [ ] **Step 1: Browser check against the fake.**
  - Start the fake switch, then netview with `preview_start` "netview". In Settings → GS105E → Connection, set host `127.0.0.1`, port `8105` and password `secret` (the fake's test password), and run Test connection.
  - Check the dashboard tile, the Switch page (both views, LEDs on ports 1–2, ports 3–5 dark), a port panel with its chart after two counter polls, Pause/Resume, the configuration sections, and the report section on the switch's device.
  - Check at 375 px that only the faceplate scrolls, and check dark mode.
  - Expected: no console errors, and the layout matches the spec. Take screenshots as proof.
- [ ] **Step 2: Live check against 192.168.1.3.** The user enters the real password in Settings themselves; never type it for them.
  - Run Test connection, wait for the polls, and compare the ports, speeds and counters with the switch's own web page.
  - Open the switch's page in a browser while netview polls, to confirm both sessions keep working.
  - Then put the dev settings back to the real switch, or clear them, as the user prefers.
- [ ] **Step 3: Write `docs/gs105e-setup.md`:** setting or changing the switch password, the address, what netview reads, Pause, the fact that disabling takes effect at restart, and adding fixtures for a newly enabled feature with `tools/capture.py --rescrub`.
- [ ] **Step 4: Run the full checks:** `uv run pytest -q`, `uv run ruff check plugins/gs105e`, `uv run ruff format --check plugins/gs105e`, `uv run mypy plugins/gs105e`, `uv run lint-imports` and `npm test`. Expected: all pass. `src/netview/application/capabilities.py` already fails `ruff format --check` on main; leave it and report it.
- [ ] **Step 5: Commit** `docs(gs105e): setup notes; phase 1 checked in a browser and against the switch`.
