# GeoTrace part 1: spikes and core SDK 2.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the three risky assumptions behind GeoTrace (spikes S1-S3), then land the five core additions it needs as NetView SDK 2.1, before any plugin code exists.

**Architecture:** Three throwaway spikes record their findings and keep only their fixture captures. Then, in core: a new manifest permission plus a parser that tolerates unknown values in the plugin catalog; a per-plugin files folder on the plugin context; IPv6 support in `NetworkTools.ping`; and a new `NetworkTools.traceroute` that wraps `tracert` / `traceroute` / `tracepath` and streams hops. Part 2 (`2026-11-13-geotrace-2-plugin.md`) builds the plugin on top.

**Tech Stack:** Python 3.11, FastAPI, pydantic, stdlib `subprocess`/`ipaddress`/`urllib`; `maxminddb` (new core dependency); plain JS for one label map; pytest, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-12-geotrace-plugin-design.md` (§5 core changes, §14 spikes, §3 constraints). Executors read both documents.

## Global Constraints

- Work on branch `feature/geotrace` in the worktree `R:\source\claude projects\HomeLab\netview-geotrace`. Commit with the repo's `user.email` (the GitHub no-reply address); never with a work address. Do not push.
- Gate for every task: `uv run pytest -q && npm test && uv run ruff check src tests plugins && uv run mypy src plugins && uv run lint-imports`.
- `SDK_VERSION` becomes exactly `"2.1"`. Every test that pins `"2.0"` as *the current version* moves to `"2.1"`; tests that use `"2.0"` as an *older install's* version keep it.
- New permission: `Permission.NETWORK_INTERNET = "network:internet"`, gallery label exactly `Connects to the internet`.
- Unsupported catalog entries show the reason exactly `Needs a newer netview` (the wording `installable()` already uses).
- Plugin files folder: `<data dir>/plugin-data/<guid>/` (beside `<guid>.db`), created on first access of `ctx.files_dir`, removed by uninstall's `_delete_data`.
- Nothing ever passes a host name to a command line: `ping` and `traceroute` take IP literals only (IPv4 or IPv6), validated with `ipaddress`, else they return `None` / an error result without running anything.
- Traceroute limits: `max_hops` clamped to 1..64 (default 30); `probe_timeout_ms` clamped to 100..5000 (default 1000); whole-run timeout `max_hops * 3 * probe_timeout_ms / 1000 + 10` seconds.
- Windows commands use `windows.system_exe(...)` absolute paths (`TRACERT.EXE`, `PING.EXE`).
- Spike S2 stop rule (spec §12): if the Cesium **page** needs any CSP change, stop the plan and report to the user with the four options in the spec. Do not change the CSP in this plan.
- Spike S1 stop rule: if OSM serves the "blocked" tile to the server, stop after S1-S3 and report to the user before Part 2.
- Downloading the Cesium release zip (S2) is a file download: ask the user first, naming the file, source URL and size.

## Review Focus

1. **A catalog list with one bad entry** (unknown permission, unknown capability, unknown `plugin_type`, or a malformed entry missing `guid`): the rest of the list must still load. Unknown values are listed as "Needs a newer netview", and malformed entries are dropped and logged. Test in Task 1.
2. **`tracert` to a destination that never answers** (30 rows of `* * *`): returns 30 silent hops with `reached=False` within the whole-run timeout, without hanging. Test in Task 4.
3. **Linux `traceroute` rows where probes come back from different routers** (`5  1.2.3.4  10.1 ms 5.6.7.8  11.2 ms  10.9 ms`): the hop takes the first IP and all three RTTs. Test in Task 4.
4. **IPv6 ping on Windows** (no TTL in the reply): returns an RTT with `ttl=None`. A "Destination host unreachable" reply that carries no time returns `None`. Test in Task 3.
5. **Uninstall while the plugin's files folder holds open or read-only files** (Windows): `_delete_data` reports "its saved data was not fully deleted" instead of raising. Test in Task 2.

---

### Task 0: Spikes S1-S3 (findings + fixtures)

**Files:**
- Create: `docs/superpowers/spikes/2026-11-13-geotrace/README.md` (findings, one section per spike)
- Create: `docs/superpowers/spikes/2026-11-13-geotrace/osm_probe.py` (S1 script, kept for reference)
- Create: `tests/fixtures/net/traceroute/` capture files (S3), named below
- Create: `tests/fixtures/net/ping6/` capture files (S3)

**Interfaces:**
- Produces: the fixture files Tasks 3 and 4 parse, with these exact names:
  `tracert_win_reached.txt`, `tracert_win_silent_tail.txt`, `tracert_win_unreachable_target.txt`, `tracert_win_ipv6.txt`, `traceroute_linux_reached.txt`, `traceroute_linux_multi_ip.txt`, `tracepath_linux.txt`, `ping6_win_reply.txt`, `ping6_win_unreachable.txt`, `ping6_linux_reply.txt`.

- [ ] **Step 1: S1, OSM through the server.** `osm_probe.py` (stdlib `urllib.request`, `--help`, no side effects beyond printing) fetches tiles z/x/y = `3/1/3`, `8/53/97`, `14/3372/6261`, `17/26987/50097` from `https://tile.openstreetmap.org/` with `User-Agent: NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)`, and prints status, `Content-Type`, `Cache-Control`, `Expires`, `ETag`, byte size and SHA-256 per tile. Save one tile of each zoom to the scratchpad and look at them. Record in README: real tiles or the "Access blocked" image; the headers; whether a blocked tile is recognisable (distinct hash, size or header). **If blocked: stop the plan after Step 3 and report.**
- [ ] **Step 2: S2, Cesium in the NetView shell.** Ask the user before downloading `Cesium-1.144.zip` from `https://github.com/CesiumGS/cesium/releases` (state the size from the release page). Unpack it to the session scratchpad, not the repo. Make a throwaway folder plugin in the scratchpad (`spike_globe/`, with `__init__.py`, `plugin.json`, and `static/ui.js` that registers a `page` slot, sets `window.CESIUM_BASE_URL` from an external module, adds `<script src=…/Cesium.js>` and builds a `Cesium.Viewer` with a Natural Earth II base layer, `Ion.defaultAccessToken = ""`, `geocoder:false`, `baseLayerPicker:false`). Copy `Build/Cesium` into its `static/cesium/`. Run NetView on a scratch data dir with `--plugin-dir` pointing at it (add a temporary launch.json entry, port 8775), open the page in the browser pane, and read the console for CSP violations. Record every blocked directive and whether it came from the page or a worker. **If the page itself needs a change: stop the plan and report** (spec §12). Remove the temporary launch entry afterwards.
- [ ] **Step 3: S3, command captures.** On this PC: `tracert -d -h 30 -w 1000 1.1.1.1` → `tracert_win_reached.txt`; `tracert -d -h 30 -w 1000 192.0.2.1` (no route) → `tracert_win_unreachable_target.txt`; a public target whose tail is silent (try `tracert -d -h 30 -w 1000 microsoft.com`'s resolved IP) → `tracert_win_silent_tail.txt`; `tracert -6 -d -h 30 -w 1000 2606:4700:4700::1111` → `tracert_win_ipv6.txt`; `ping -6 -n 1 -w 800 2606:4700:4700::1111` → `ping6_win_reply.txt`; `ping -6 -n 1 -w 800 2001:db8::1` → `ping6_win_unreachable.txt`. For Linux: ask the user to run on the Proxmox host and paste back `traceroute -n -m 30 -w 1 1.1.1.1`, `traceroute -n -m 30 -w 1 8.8.8.8` (or any target with a multi-IP row), `tracepath -n 1.1.1.1` and `ping -6 -c 1 -W 1 2606:4700:4700::1111`. If a multi-IP row never appears, hand-write `traceroute_linux_multi_ip.txt` from the real capture with one row edited, and say so in a first-line comment `# edited: ...`. Replace this house's public addresses in captures with `203.0.113.x` (Starlink's first hops included) and say so in the README.
- [ ] **Step 4: Write the README** (findings, decisions taken, files captured) and commit.

```bash
git add docs/superpowers/spikes/2026-11-13-geotrace tests/fixtures/net/traceroute tests/fixtures/net/ping6
git commit -m "docs: GeoTrace spikes S1-S3 findings and command captures"
```

---

### Task 1: SDK 2.1, `network:internet`, tolerant catalog, `maxminddb`

**Files:**
- Modify: `src/netview/application/plugins/manifest.py` (`SDK_VERSION`, `Permission`)
- Modify: `src/netview/application/plugins/plugin_json.py` (`PluginJson`, `parse_plugin_json`, `parse_index`, `installable`)
- Modify: `src/netview/presentation/web/static/js/settings/plugins-tab.js` (`PERMISSION_LABELS`) and any other place manifest permissions are labelled (grep the static JS for `network:control`)
- Modify: `docs/plugin-permissions.md` (one line in the manifest-permissions list naming `network:internet`)
- Modify: `pyproject.toml`, `uv.lock` (`maxminddb>=2.6` via `uv add`)
- Modify: tests pinning the current SDK version: `tests/unit/test_sdk_exports.py:33`, `tests/integration/test_cli_serve.py:134`
- Test: `tests/unit/application/test_plugin_json_tolerant.py`, `tests/js/plugins-tab-labels.test.mjs`

**Interfaces:**
- Produces: `Permission.NETWORK_INTERNET`; `PluginJson.unsupported: tuple[str, ...]` (default `()`; the unknown values seen, as `"permissions:network:foo"` style strings); `parse_plugin_json(data, *, lenient: bool = False) -> PluginJson`; `parse_index` now lenient per entry; `installable()` returns `"Needs a newer netview"` when `pj.unsupported` is non-empty.

- [ ] **Step 1: Write the failing tests**

```python
def test_unknown_permission_in_index_keeps_the_list(): ...
    # index with two entries; second lists "network:teleport"
    # -> parse_index returns 2 entries; second.plugin.unsupported == ("permissions:network:teleport",)
    # -> installable(second.plugin, "2.1", lambda n: True) == "Needs a newer netview"
def test_unknown_capability_and_plugin_type_are_unsupported_not_fatal(): ...
def test_malformed_entry_is_dropped_and_logged(caplog): ...
    # entry without guid -> list has the other entries; caplog has one warning naming the path
def test_local_plugin_json_stays_strict(): ...
    # parse_plugin_json(data_with_unknown_permission) (lenient=False) raises ValidationError
def test_network_internet_is_known(): ...
    # parse_plugin_json with "network:internet" -> unsupported == ()
def test_duplicate_guid_still_rejects_the_index(): ...
def test_sdk_version_is_2_1(): assert SDK_VERSION == "2.1"
```

`tests/js/plugins-tab-labels.test.mjs`: `PERMISSION_LABELS["network:internet"] === "Connects to the internet"`.

- [ ] **Step 2: Run them to verify they fail** — `uv run pytest tests/unit/application/test_plugin_json_tolerant.py -q` and `npm test`; expected FAIL.
- [ ] **Step 3: Implement.** In lenient mode, `_str_list` collects unknown values instead of raising, and so does the `plugin_type` check. `parse_index` wraps each entry in `try/except ValidationError`, logs `plugin index: skipped entry %r: %s` at warning level, and continues. A duplicate guid among the parsed entries still fails the whole index (unchanged). Bump `SDK_VERSION`, add the permission and label, update the two version-pinning tests, and `uv add "maxminddb>=2.6"`.
- [ ] **Step 4: Run the gate** — expected all green.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): SDK 2.1 with network:internet, tolerant plugin catalog, maxminddb"`

---

### Task 2: Plugin files folder (`ctx.files_dir`)

**Files:**
- Modify: `src/netview/application/plugins/context.py` (`PluginIdentity.files_dir: Path`, `PluginContext.files_dir: Path` protocol attribute, docstring "created on first access")
- Modify: `src/netview/infrastructure/db/engine.py` (add `plugin_files_dir(data_dir: Path, guid: str) -> Path` = `data_dir / "plugin-data" / guid`)
- Modify: `src/netview/infrastructure/plugins/host.py` (build `PluginIdentity` with `files_dir`; `_delete_data` also removes the folder with `shutil.rmtree`, catching `OSError` into the existing error message)
- Modify: `src/netview/infrastructure/plugins/context.py` (`DefaultPluginContext.files_dir` property that creates the folder on first access)
- Modify: `src/netview/sdk/testing/fakes.py` (`FakePluginContext(..., files_dir: Path | None = None)`; the property creates `tempfile.mkdtemp()` when none is given)
- Test: `tests/unit/infrastructure/test_plugin_files_dir.py`, `tests/integration/plugins/test_uninstall_removes_files_dir.py`

**Interfaces:**
- Produces: `ctx.files_dir -> Path` (exists after first access); `plugin_files_dir(data_dir, guid) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
def test_files_dir_is_beside_the_db_and_created_lazily(tmp_path): ...
    # identity.files_dir == tmp_path/"plugin-data"/guid; not exists before access; exists after ctx.files_dir
def test_uninstall_removes_files_dir(tmp_path): ...
    # write files_dir/"a/b.bin"; uninstall the folder plugin -> folder gone, <guid>.db gone
def test_uninstall_reports_undeletable_files(monkeypatch, tmp_path): ...
    # monkeypatch shutil.rmtree to raise PermissionError -> returned message starts "its saved data was not fully deleted"
def test_fake_context_gives_a_real_folder(): ...
```

- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement** as in Files. Use the uninstall test pattern already in `tests/integration/plugins/` (the plugin-identity work) as the template for the folder-plugin uninstall.
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit** — `git commit -m "feat(core): per-plugin files folder, removed on uninstall"`

---

### Task 3: IPv6 ping

**Files:**
- Modify: `src/netview/application/ports/network.py` (`PingResult.ttl: int | None`)
- Modify: `src/netview/infrastructure/net/common.py` (`valid_ip(value: object) -> bool` for v4 or v6; `parse_ping_output(output: str, require_ttl: bool = True)`)
- Modify: `src/netview/infrastructure/net/windows.py` (`ping_command(ip, timeout_ms)` adds `-6` for IPv6 literals)
- Modify: `src/netview/infrastructure/net/linux.py` (`ping_command` adds `-6` for IPv6; `macos_ping_command` uses `ping6` for IPv6)
- Modify: `src/netview/infrastructure/net/tools.py` (`ping` accepts `valid_ip`; IPv6 parses with `require_ttl=False`)
- Modify: every caller mypy flags for `ttl: int | None` (expected none to need logic changes: `Sighting.ttl` and inspection already accept `None`)
- Test: `tests/unit/infrastructure/test_ping6.py`

**Interfaces:**
- Produces: `NetworkTools.ping(ip)` works for IPv6 literals; `PingResult(rtt_ms, ttl=None)` for IPv6 replies without a TTL.

- [ ] **Step 1: Write the failing tests** (using Task 0's `ping6_*` fixtures)

```python
def test_windows_ipv6_reply_has_rtt_and_no_ttl(): # ping6_win_reply.txt -> PingResult(rtt_ms=<value in file>, ttl=None)
def test_windows_ipv6_unreachable_is_none(): # ping6_win_unreachable.txt -> None
def test_linux_ipv6_reply_parses(): # ping6_linux_reply.txt -> rtt from file
def test_ipv4_without_ttl_is_still_none(): # existing IPv4 rule unchanged
def test_ping_command_adds_dash_6_only_for_ipv6(): # windows and linux
def test_ping_refuses_host_names(): # SystemNetworkTools().ping("example.com") is None, no command run (monkeypatch common.run to fail the test if called)
```

- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.** For `require_ttl=False`, a reply means `TIME_RE` matched; the TTL is taken when present.
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit** — `git commit -m "feat(core): ping IPv6 literals"`

---

### Task 4: `NetworkTools.traceroute`

**Files:**
- Modify: `src/netview/application/ports/network.py` (new dataclasses and the protocol method)
- Modify: `src/netview/infrastructure/net/common.py` (`run_lines(cmd: list[str], timeout: float, on_line: Callable[[str], None]) -> bool`: `Popen` with the same no-window flags as `run`, decode each stdout line with `locale.getpreferredencoding(False)` and `errors="replace"`, kill on timeout, return `False` if the command could not start or timed out)
- Create: `src/netview/infrastructure/net/traceroute.py` (commands and line parsers for both systems)
- Modify: `src/netview/infrastructure/net/tools.py` (`SystemNetworkTools.traceroute`)
- Modify: `src/netview/sdk/__init__.py` (export `TraceHop`, `TraceResult`)
- Modify: `src/netview/sdk/testing/fakes.py` (`FakeNetworkTools(traces: dict[str, TraceResult] | None = None)`; `traceroute` replays the hops through `on_hop`)
- Test: `tests/unit/infrastructure/test_traceroute_parsers.py`, `tests/unit/infrastructure/test_traceroute_tools.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class TraceHop:
    n: int
    ip: str | None                      # None for "* * *"
    rtts_ms: tuple[float | None, ...]   # up to 3; None for a probe that timed out

@dataclass(frozen=True)
class TraceResult:
    target: str
    hops: tuple[TraceHop, ...]
    reached: bool                       # last hop's ip == target
    error: str | None = None            # plain words: "traceroute is not installed", "not an IP address", "timed out"

class NetworkTools(Protocol):
    def traceroute(self, ip: str, max_hops: int = 30, probe_timeout_ms: int = 1000,
                   on_hop: Callable[[TraceHop], None] | None = None) -> TraceResult: ...
```

- In `traceroute.py`: `windows_command(ip, max_hops, timeout_ms) -> list[str]` (`TRACERT.EXE -d -h N -w T` plus `-4`/`-6`); `linux_command(ip, max_hops, timeout_ms) -> list[str]` (`traceroute -n -m N -w S -q 3`, plus `-6` for IPv6; `S = max(1, round(T/1000))`); `tracepath_command(ip, max_hops) -> list[str]` (`tracepath -n -m N`, plus `-6`); `parse_windows_line(line) -> TraceHop | None`; `parse_traceroute_line(line) -> TraceHop | None`; `parse_tracepath_line(line) -> TraceHop | None` (keeps the best RTT per hop number; `?:` and `[LOCALHOST]` rows ignored).

- [ ] **Step 1: Write the failing tests** (Task 0 fixtures; every parser is fed the whole file line by line)

```python
def test_tracert_reached_hops_and_rtts(): # hop count, first hop "192.168.1.1", "<1 ms" -> 0.5, last ip == 1.1.1.1
def test_tracert_silent_tail_marks_hops_none(): # trailing rows ip None, rtts (None, None, None)
def test_tracert_unreachable_target_not_reached(): # reached False
def test_tracert_ipv6_rows_parse(): # IPv6 hop ips kept verbatim
def test_traceroute_multi_ip_row_takes_first_ip_and_three_rtts(): # Review Focus 3
def test_tracepath_rows_and_localhost_ignored():
def test_header_and_footer_lines_are_ignored(): # "Tracing route to", "Trace complete.", "traceroute to" -> None
def test_traceroute_refuses_host_names_and_runs_nothing(monkeypatch): # error == "not an IP address"
def test_limits_are_clamped(): # max_hops=500 -> 64 in the command; probe_timeout_ms=1 -> 100
def test_silent_destination_returns_within_timeout(monkeypatch): # fake run_lines feeding 30 silent rows -> 30 hops, reached False (Review Focus 2)
def test_on_hop_called_in_order(monkeypatch):
def test_linux_falls_back_to_tracepath_then_reports_missing(monkeypatch): # shutil.which -> None for traceroute; then for both -> error "traceroute is not installed"
```

- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.** Parsers read numbers and IPs only: a row starts with a hop number; RTT tokens are `<1`, `N` or `N.N` followed by `ms` (Windows separates them with spaces; Linux writes `0.512 ms`); `*` is a timed-out probe. IPs are recognised with `ipaddress` on each whitespace token (strip `()` and `[]`). Words in any language are ignored. On Windows, a `<1 ms` RTT is recorded as `0.5`, matching `parse_ping_output`.
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit** — `git commit -m "feat(core): NetworkTools.traceroute for Windows and Linux"`

---

### Task 5: Part 1 wrap-up

- [ ] **Step 1:** Update `docs/superpowers/deferred.md` with anything parked during this part, and add an SDK 2.1 line wherever the SDK history is kept (search `SDK 1.5` in `docs/` to find the place).
- [ ] **Step 2:** Run the full gate once more and record the counts (pytest, npm) in the commit message.
- [ ] **Step 3: Commit** — `git commit -m "docs: SDK 2.1 notes for GeoTrace part 1"`
