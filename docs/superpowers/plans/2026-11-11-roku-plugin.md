# netview Roku plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A netview plugin `roku`, kept outside the core in `plugins/roku/` (a sibling of `src/`) and loaded as a local plugin folder, never as a built-in, that finds Roku TVs, keeps an editable saved list, and gives each TV a remote-control tab plus a cheat-sheet Commands view, with the nav tab disabled while no TV is saved.

**Architecture:** A local plugin folder `plugins/roku/` at the repo root, loaded by netview's existing folder discovery (`AppSettings.plugin_dirs`, module name `netview_local_plugins.roku`, `plugin_class` in `__init__.py`), in the Starlink/GSM7248 code shape: pure modules (ECP client and parsers, allow-lists, address rule, document parsing, merge) under a `RokuService` that owns the saved list (plugin table `roku_tvs`), an in-memory status cache, scans and commands, exposed by a FastAPI router and two jobs. The UI is plain ES modules in the plugin's `static/` registering a `page` slot and a `settings.section` slot. Four small core changes land first as SDK 1.4.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy + Alembic (per-plugin branch), pydantic settings, stdlib urllib/xml; plain JS ES modules, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-11-roku-plugin-design.md`. Approved mockup: `HomeLab/mockups/roku-plugin-mockup.html`. Cheat-sheet source: `docs/superpowers/reference/roku-ecp-cheat-sheet.html`.

## Global Constraints

- **Not a built-in (user's instruction, 2026-11-11).** All plugin code, static files, migrations and tests live under `plugins/roku/` at the repo root, a sibling of `src/`. Nothing goes in `src/netview/plugins/builtin/`, no entry point in `pyproject.toml`, and the wheel does not include it. netview loads it from a plugin folder: `plugins/roku/__init__.py` sets `plugin_class = RokuPlugin`; at runtime the package is `netview_local_plugins.roku`.
- Inside the plugin, modules import each other relatively (`from .ecp import ...`) and the core only through `netview.sdk` (plus stdlib, fastapi, pydantic, sqlalchemy, alembic in migrations). import-linter cannot see code outside `src/`, so an AST test (`plugins/roku/tests/unit/test_roku_imports.py`, Task 2) enforces this rule.
- Plugin tests live in `plugins/roku/tests/` (`unit/`, `integration/`, `fixtures/`, `js/`). Python test files are named `test_roku_*.py` (the repo's test folders have no `__init__.py`, so basenames must be unique). `plugins/roku/tests/conftest.py` loads the plugin exactly as netview does (`discover_plugin_classes(extra_dirs=[<repo>/plugins])`) so tests import `netview_local_plugins.roku.<module>`; API tests hand the app that already-loaded class by monkeypatching `netview.bootstrap.discover_plugin_classes` (the pattern in `tests/integration/plugins/test_inspection_plugin.py`) rather than letting it re-import the folder.
- Gate command for every task: `uv run pytest -q && npm test && uv run ruff check src tests plugins && uv run mypy src plugins/roku && uv run lint-imports`.
- Plugin id `roku`, name `Roku`, version `0.1.0`, `sdk_version=">=1.4,<2"`. Tables prefixed `roku_`; Alembic revision ids prefixed `roku_`.
- Permissions: `storage:own`, `api`, `ui`, `network:probe`, `network:control`. Capabilities: `STORAGE`, `API`, `WEB_UI`.
- ECP: port 8060, plain HTTP, no proxy (proxy-less urllib opener), default request timeout 2 s, response cap 262144 bytes, XML containing `<!DOCTYPE` or `<!ENTITY` in its first 4096 bytes is refused.
- Saved addresses: private IPv4 only (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16). Loopback, link-local, multicast, public refused. Not limited to netview's subnet.
- No API endpoint accepts a host or URL; TVs are addressed by saved `id`.
- Error wording (spec 6.1), exactly: 403 → `This TV's Network access setting (Limited) refuses commands`; 404 → `The TV doesn't know that key or app`; timeout/refused → `The TV isn't answering. It may be fully powered off or have a new address.`; identity mismatch → `A different Roku, {name}, now answers at this address. Run a scan in Settings.`
- Disabled-tab tooltip, exactly: `No Roku TVs found yet. Click to open Roku settings and scan.`
- Limited callout path, exactly: `Settings › System › Advanced system settings › Control by mobile apps › Network access › Default`.
- Document schema id `netview.roku/tvs@1`. Accepted merge schema ids: `ketiv.network-tools/roku-scan@1` and `roku-scan@1`.
- UI: no inline `<script>`, theme tokens only in `roku.css` (the TV drawing in `tv.js` is the one fixed-colour exception), every `localStorage` access in try/catch. Keys: `netview.roku.tv`, `netview.roku.view`, `netview.roku.shell`.
- `static/find_rokus.py` is byte-identical to `R:\source\scripts\network-tools\scripts\find_rokus.py`, ASCII-only, and neither script copy has a line exactly `EOF` or `'@`.
- Python tests never send to 127.0.0.1 through the saved list (the address rule forbids it); use the fake transport. Only the urllib transport's own test uses a local `http.server`.

## Review Focus

1. **Typing non-ASCII or URL-special text** (`a b&é/+`): each character must arrive as one `Lit_` keypress, UTF-8 percent-encoded (`Lit_%C3%A9`, `Lit_%26`, `Lit_%20`). Test in Task 2.
2. **Pasting everything the script printed** (JSON plus the stderr summary line, or a `>>>` prompt before it): the editor must extract the JSON and ignore extra lines, as the cheat sheet does. Test in Task 3.
3. **A replace document with duplicate `id`, `ip` or non-empty `serial`**: refused with a message naming the entry, nothing saved. Test in Task 3.
4. **A TV that stops answering mid-session** (pulled plug): a button press returns the "isn't answering" message within the request timeout, never hangs the API, and the tab shows Not answering on the next poll. Test in Task 5.
5. **A held direction key when the pointer leaves the button or the window loses focus**: a `keyup` must still be sent. Test in Task 8.

---

### Task 1: Core changes, SDK 1.4

**Files:**
- Modify: `src/netview/application/plugins/manifest.py` (`SDK_VERSION = "1.4"`, `Permission.NETWORK_CONTROL = "network:control"`)
- Modify: `src/netview/presentation/web/static/js/settings/plugins-tab.js:52` (label `"network:control": "Sends commands to devices on your network"`)
- Modify: `src/netview/application/ports/probes.py:73`, `src/netview/infrastructure/net/probes.py:219`, `src/netview/sdk/testing/fakes.py:407` (`ssdp_search(self, target: str | None = None, timeout_s: float = 2.5, st: str = "ssdp:all")`)
- Modify: `src/netview/presentation/web/static/js/nav.js` (`navItems`), `src/netview/presentation/web/static/js/main.js` (`routes()`, the `host.setRenderer` callback)
- Modify: `src/netview/presentation/web/static/js/slots.js` (header comment: document `page {id, title, mount(el, ctx), unavailable?() -> string|null}`)
- Test: `tests/unit/test_sdk_exports.py`, `tests/js/nav.test.mjs`, `tests/unit/infrastructure/` (the existing probes adapter test file; add there), `tests/unit/application/test_fakes_probes.py`

**Interfaces:**
- Produces: `Permission.NETWORK_CONTROL`; `ServiceProbes.ssdp_search(target=None, timeout_s=2.5, st="ssdp:all") -> list[SsdpEntry]` sending `ST: {st}`; JS `navItems(routes, plugins, active)` where a route may carry `unavailable: () => string | null`; route items gain nothing new (still `{path,label,on,disabled,pluginId,title}`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_sdk_exports.py (rename the existing version test)
def test_sdk_version_is_1_4() -> None:
    assert sdk.SDK_VERSION == "1.4"

def test_network_control_permission() -> None:
    assert sdk.Permission.NETWORK_CONTROL.value == "network:control"
```

```python
# probes adapter test (use the adapter's existing fake socket pattern in that file)
def test_ssdp_search_sends_the_given_search_target(...) -> None:
    probes.ssdp_search(st="roku:ecp", timeout_s=0.01)
    assert b"\r\nST: roku:ecp\r\n" in sent_messages[0]

def test_ssdp_search_defaults_to_ssdp_all(...) -> None:
    probes.ssdp_search(timeout_s=0.01)
    assert b"\r\nST: ssdp:all\r\n" in sent_messages[0]
```

```js
// tests/js/nav.test.mjs
test("navItems disables a page whose unavailable() returns a reason, with that reason as its title", () => {
  const routes = [...ROUTES, { path: "/p/roku/tvs", label: "Roku", pluginId: "roku",
    unavailable: () => "No Roku TVs found yet. Click to open Roku settings and scan." }];
  const items = navItems(routes, [plugin(), plugin({ id: "roku", name: "Roku" })], "/p/roku/tvs");
  assert.equal(items[3].disabled, true);
  assert.equal(items[3].on, false);
  assert.equal(items[3].title, "No Roku TVs found yet. Click to open Roku settings and scan.");
});

test("navItems keeps a page enabled when unavailable() returns null, and needsSetup still wins", () => {
  const routes = [{ path: "/p/gsm7248/switch", label: "Switch", pluginId: "gsm7248", unavailable: () => null }];
  assert.equal(navItems(routes, [plugin()], "/p/gsm7248/switch")[0].disabled, false);
  assert.match(navItems(routes, [plugin({ configured: false })], "/")[0].title, /needs configuring/);
});

test("navItems treats a throwing unavailable() as available", () => {
  const routes = [{ path: "/p/x/y", label: "Y", pluginId: "x", unavailable: () => { throw new Error("boom"); } }];
  assert.equal(navItems(routes, [], "/p/x/y")[0].disabled, false);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_sdk_exports.py -q` and `npm test`
Expected: FAIL (version is 1.3; no `NETWORK_CONTROL`; nav items not disabled).

- [ ] **Step 3: Implement**

- `navItems`: `disabled = needsSetup(info) || reason != null` where `reason` is `r.unavailable?.()` (wrapped in try/catch → null); `title` is the setup hint when `needsSetup`, else `reason`. Disabled tabs keep `data-setup` so a click opens that plugin's settings (existing behaviour).
- `main.js routes()`: pass `unavailable: spec.unavailable` through to the route.
- `host.setRenderer` callback in `main.js`: call `renderNav(current.route.path)`; if the current route is now disabled per `navItems`, call `route()` (it falls back); otherwise redraw the page as today.
- `ssdp_search`: put `st` into the `ST:` line; keep `target` semantics unchanged. Fake accepts and ignores `st`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q && npm test`
Expected: all pass (existing callers of `ssdp_search` unchanged).

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat(sdk): 1.4 - page unavailable() gating, network:control permission, SSDP search target"
```

---

### Task 2: ECP client, allow-lists and the address rule

**Files:**
- Create: `plugins/roku/__init__.py` (until Task 6 it only holds a docstring; Task 6 adds `plugin_class`), `plugins/roku/ecp.py`, `keys.py`, `addresses.py`
- Create: `plugins/roku/tests/conftest.py` (loads the repo's `plugins/` folder through `discover_plugin_classes(extra_dirs=[...])` once per session so `netview_local_plugins.roku` is importable; exposes `PLUGINS_DIR` and `ROKU_DIR`), `plugins/roku/tests/unit/test_roku_imports.py`
- Modify: `pyproject.toml` (`[tool.pytest.ini_options] testpaths = ["tests", "plugins"]`), `package.json` (test script also runs `"plugins/*/tests/js/*.test.mjs"`)
- Create: `plugins/roku/tests/fixtures/device-info-on.xml`, `device-info-standby.xml`, `device-info-limited.xml`, `active-app-youtube.xml`, `active-app-home.xml`, `apps.xml`, `not-roku.xml`, `doctype.xml`
- Test: `plugins/roku/tests/unit/test_roku_ecp.py`, `test_keys.py`, `test_addresses.py`

**Interfaces:**
- Produces (`ecp.py`):
  - `@dataclass(frozen=True) EcpResponse(status: int, headers: Mapping[str, str], body: bytes)`
  - `Transport = Callable[[str, str, float], EcpResponse]` (method, url, timeout_s); raises `OSError` on timeout/refused
  - `urllib_transport(method: str, url: str, timeout_s: float) -> EcpResponse` (proxy-less opener; returns non-2xx as `EcpResponse`, not exceptions; reads at most 262144 bytes)
  - `@dataclass(frozen=True) DeviceInfo(serial, name, model, location, tv: bool, mode: str, power_raw: str)` with property `power -> Literal["on","standby","unknown"]` (`PowerOn` → on; `DisplayOff`, `Ready`, `Headless`, `Suspend` → standby; else unknown)
  - `@dataclass(frozen=True) ActiveApp(id: str | None, name: str, screensaver: str | None)`; Home is `id=None, name="Home"`
  - `@dataclass(frozen=True) App(id: str, name: str, type: str)`
  - `parse_device_info(body: bytes) -> DeviceInfo | None`, `parse_active_app(body: bytes) -> ActiveApp | None`, `parse_apps(body: bytes) -> list[App] | None` (None = not that document or unsafe XML)
  - `class EcpError(Exception)` with `status: int | None` (None = no answer) and `message: str` (the Global Constraints wording for 403/404/None; `f"The TV answered {status}"` otherwise)
  - `class EcpClient(transport: Transport, timeout_s: float)`: `device_info(ip) -> DeviceInfo` (a 4xx whose `Server` header contains "roku" returns `DeviceInfo` with empty fields, as the script's `blank()`), `active_app(ip) -> ActiveApp`, `apps(ip) -> list[App]`, `icon(ip, app_id) -> tuple[bytes, str]` (body, content type), `post(ip, path) -> None`. All raise `EcpError` on non-2xx or `OSError`.
- Produces (`keys.py`): `KEYS: frozenset[str]` (spec 6.1 list), `key_path(key: str, action: Literal["press","down","up"] = "press") -> str` → `/keypress/Home`, `/keydown/Right`, `/keyup/Right`; `app_path(app: str) -> str` → `/launch/12`; `text_paths(text: str) -> list[str]`; all raise `ValueError` on anything outside the allow-list. Text: 1 to 100 characters.
- Produces (`addresses.py`): `is_allowed_ip(ip: str) -> bool`.

- [ ] **Step 1: Write the fixtures and failing tests**

Fixtures follow real ECP shapes: `device-info` root with `serial-number`, `user-device-name`, `friendly-device-name`, `default-device-name`, `model-name`, `user-device-location`, `is-tv`, `ecp-setting-mode`, `power-mode`; `active-app` with `<app id="837" type="appl" version="2.21">YouTube</app>`; home is `<app>Roku</app>`; `apps` with three `<app id=… type=…>` entries including one `tvinput.hdmi1`.

```python
def test_parse_device_info_on():
    d = parse_device_info(read("device-info-on.xml"))
    assert (d.serial, d.name, d.model, d.tv, d.mode, d.power) == ("X01234567890", "Living Room TV", "TCL 55S455", True, "default", "on")

def test_parse_device_info_name_falls_back_to_friendly_then_default(): ...
def test_parse_device_info_standby_and_limited():  # power == "standby", mode == "limited"
def test_parse_refuses_doctype_and_other_roots():
    assert parse_device_info(read("doctype.xml")) is None
    assert parse_device_info(read("not-roku.xml")) is None
def test_parse_active_app_youtube_and_home():
    assert parse_active_app(read("active-app-youtube.xml")) == ActiveApp("837", "YouTube", None)
    assert parse_active_app(read("active-app-home.xml")).name == "Home"
def test_parse_apps_keeps_ids_names_types(): ...

@pytest.mark.parametrize("status,msg", [(403, "This TV's Network access setting (Limited) refuses commands"),
                                        (404, "The TV doesn't know that key or app")])
def test_client_post_maps_status_to_message(status, msg): ...
def test_client_post_maps_oserror_to_not_answering():
    # transport raises TimeoutError -> EcpError(status=None, message="The TV isn't answering. It may be fully powered off or have a new address.")
def test_client_builds_url_on_port_8060():  # fake transport records "POST", "http://192.168.1.60:8060/keypress/Home"
def test_device_info_4xx_with_roku_server_header_is_blank_roku(): ...
def test_urllib_transport_against_local_server_returns_status_and_body():  # http.server on 127.0.0.1:0, GET 200 and POST 404
```

```python
def test_key_paths():
    assert key_path("Home") == "/keypress/Home"
    assert key_path("Right", "down") == "/keydown/Right"
    assert key_path("Lit_a") == "/keypress/Lit_a"

@pytest.mark.parametrize("bad", ["home", "Home/../x", "Lit_", "Lit_ab", "PowerOn?x=1", ""])
def test_key_path_refuses(bad): ...

def test_app_paths():
    assert app_path("12") == "/launch/12"
    assert app_path("tvinput.hdmi4") == "/launch/tvinput.hdmi4"
    assert app_path("tvinput.dtv") == "/launch/tvinput.dtv"
@pytest.mark.parametrize("bad", ["tvinput.hdmi5", "12a", "12345678901", "../x", ""])
def test_app_path_refuses(bad): ...

def test_text_paths_encode_each_character():  # Review Focus 1
    assert text_paths("a b&é/+") == ["/keypress/Lit_a", "/keypress/Lit_%20", "/keypress/Lit_b",
        "/keypress/Lit_%26", "/keypress/Lit_%C3%A9", "/keypress/Lit_%2F", "/keypress/Lit_%2B"]
def test_text_paths_refuse_empty_and_over_100(): ...
```

```python
@pytest.mark.parametrize("ip", ["10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.1.60"])
def test_private_allowed(ip): assert is_allowed_ip(ip)
@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.1.1", "224.0.0.1", "8.8.8.8", "172.32.0.1", "192.168.1", "x", "::1"])
def test_others_refused(ip): assert not is_allowed_ip(ip)
```

Import-rule test:

```python
def test_plugin_imports_only_the_sdk_and_allowed_libraries():
    # AST-walk every .py under plugins/roku except tests/; each absolute import's top-level name must be
    # in sys.stdlib_module_names or {"fastapi", "pydantic", "sqlalchemy", "alembic"}, or be exactly
    # "netview.sdk" / start with "netview.sdk."; relative imports are allowed.
    assert offenders == []
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest plugins/roku/tests/unit -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `ecp.py`, `keys.py`, `addresses.py` to the interfaces. Percent-encode with `urllib.parse.quote(ch, safe="")` on the UTF-8 character.
- [ ] **Step 4: Run** `uv run pytest plugins/roku/tests/unit -q` → PASS; the gate command (Global Constraints) → clean.
- [ ] **Step 5: Commit** `feat(roku): ECP client, command allow-lists, private-address rule`

---

### Task 3: Saved list - storage, document and merge

**Files:**
- Create: `plugins/roku/model.py`, `storage.py`, `document.py`, `merge.py`, `migrations/versions/0001_initial.py`
- Test: `plugins/roku/tests/unit/test_roku_document.py`, `test_merge.py`, `plugins/roku/tests/integration/test_roku_storage.py`

**Interfaces:**
- Produces (`model.py`):
  - `@dataclass SavedTv(id: str, serial: str, ip: str, name: str, label: str, model: str, location: str, tv: bool, found_by: str, first_seen: str, last_seen: str)` with property `title -> str` (`label or name or ip`)
  - `@dataclass(frozen=True) ScanHit(ip: str, serial: str, name: str, model: str, location: str, tv: bool, found_by: str)`
  - `FIELDS: tuple[str, ...]` = the SavedTv field names in that order
- Produces (`storage.py`): `metadata`, table `roku_tvs` (columns: the SavedTv fields with `id` primary key, plus `position: int`), `storage_spec() -> StorageSpec`, `class TvStore(uow_factory: Callable[[], PluginUnitOfWork])` with `load() -> list[SavedTv]` (ordered by position) and `replace(tvs: list[SavedTv]) -> None` (one transaction, positions = list order). Migration revision `roku_0001`, `down_revision = None`, `branch_labels = None` (copy the header of `gsm7248/migrations/versions/0001_initial.py`; the host manages the per-plugin branch).
- Produces (`document.py`):
  - `SCHEMA = "netview.roku/tvs@1"`
  - `to_document(tvs: list[SavedTv]) -> dict` → `{"schema": SCHEMA, "tvs": [asdict(tv) ...]}`
  - `@dataclass(frozen=True) Replace(tvs: list[dict])`, `MergeHits(hits: list[ScanHit])`, `MergeIps(ips: list[str])`
  - `parse_document(text: str) -> Replace | MergeHits | MergeIps`, raising `DocumentError(message: str)`
  - `validate_replace(entries: list[dict], new_id: Callable[[], str]) -> list[SavedTv]` raising `DocumentError`
- Produces (`merge.py`): `@dataclass(frozen=True) MergeResult(tvs: list[SavedTv], added: int, updated: int)`; `merge(saved: list[SavedTv], hits: list[ScanHit], now_iso: str, new_id: Callable[[], str]) -> MergeResult`

Parse rules (spec 5.2): try `json.loads(text)`; failing that, `json.JSONDecoder().raw_decode` from the first `{` or `[`, ignoring text before and after (Review Focus 2). Object with `schema == SCHEMA` → `Replace(obj["tvs"])`. Object whose schema is `ketiv.network-tools/roku-scan@1` or `roku-scan@1` → `MergeHits` from `devices`. A JSON array of objects with `ip` (the PowerShell output) → `MergeHits`. Hits carry `serial=""` when absent and `found_by` from the entry or `"manual"`. Non-JSON text where every non-blank line is an IPv4 → `MergeIps`. Every address must pass `is_allowed_ip`, else `DocumentError(f"{ip} is not a private address")`. Anything else → `DocumentError("Not a TV list, scan output or list of addresses")`.

Replace validation: `ip` required; unknown keys → `DocumentError(f"Unknown field '{k}' in TV {n}")` (n is 1-based); duplicate `id`, `ip`, or non-empty `serial` → `DocumentError(f"TV {n} repeats the {field} of TV {m}")`; missing `id` gets `new_id()`; missing optional strings default to `""`, `tv` to `True`; `first_seen`/`last_seen` default to the save time (passed in by the service). `label` at most 60 characters.

Merge rules: match by serial when both non-empty, else by ip; matched → update ip, name, model, location, tv, found_by, last_seen (never label, id, order, first_seen); unmatched → append with new id, first_seen = last_seen = now_iso; nothing removed. When a hit's ip is held by a different saved TV, the matched TV takes it and the other keeps its old ip (spec 5.2 rule 5).

- [ ] **Step 1: Write the failing tests**

```python
def test_merge_matches_by_serial_and_keeps_label_and_order():
    saved = [tv(id="a", serial="S1", ip="192.168.1.60", label="Lounge"), tv(id="b", serial="S2", ip="192.168.1.61")]
    r = merge(saved, [hit(serial="S1", ip="192.168.1.70", name="New name")], NOW, ids())
    assert [t.id for t in r.tvs] == ["a", "b"] and r.tvs[0].ip == "192.168.1.70"
    assert r.tvs[0].label == "Lounge" and r.tvs[0].name == "New name" and (r.added, r.updated) == (0, 1)
def test_merge_matches_by_ip_when_serial_missing(): ...
def test_merge_appends_new_and_never_removes(): ...
def test_merge_address_reshuffle_moves_ip_to_serial_match_other_keeps_old(): ...

def test_parse_replace_document(): ...
def test_parse_find_rokus_output_both_schema_ids(): ...
def test_parse_powershell_array(): ...
def test_parse_ip_lines(): assert parse_document("192.168.1.60\n\n192.168.1.61\n") == MergeIps(["192.168.1.60", "192.168.1.61"])
def test_parse_ignores_text_around_json():  # Review Focus 2
    text = '>>> ran\n{"schema": "roku-scan@1", "devices": [{"ip": "192.168.1.60"}]}\nFound 1 Roku device (subnet ...).'
    assert isinstance(parse_document(text), MergeHits)
def test_parse_refuses_public_address(): ...
def test_parse_refuses_garbage(): ...
def test_replace_refuses_unknown_field(): ...  # message "Unknown field 'power' in TV 1"
@pytest.mark.parametrize("field", ["id", "ip", "serial"])
def test_replace_refuses_duplicates(field): ...  # Review Focus 3; message "TV 2 repeats the {field} of TV 1"
def test_replace_assigns_missing_ids(): ...
def test_to_document_round_trips(): ...
```

```python
# plugins/roku/tests/integration/test_roku_storage.py - use the HostEnv/uow fixtures from tests/integration/plugins/conftest.py
def test_replace_then_load_keeps_order_and_fields(): ...
def test_replace_removes_rows_not_in_the_new_list(): ...
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** the four modules and the migration.
- [ ] **Step 4: Run** `uv run pytest plugins/roku/tests/unit plugins/roku/tests/integration -q` → PASS.
- [ ] **Step 5: Commit** `feat(roku): saved TV list - storage, JSON document and scan merge`

---

### Task 4: Discovery scan

**Files:**
- Create: `plugins/roku/discovery.py`
- Test: `plugins/roku/tests/unit/test_roku_discovery.py`

**Interfaces:**
- Consumes: `EcpClient.device_info`, `ScanHit`, `ServiceProbes.ssdp_search(st=...)`.
- Produces: `@dataclass(frozen=True) ScanResult(hits: list[ScanHit], subnet: str | None, by_ssdp: int, by_sweep: int, duration_s: float)`; `scan(probes: ServiceProbes, ecp: EcpClient, subnet: str | None, timeout_s: float, workers: int = 128, clock: Callable[[], float] = time.monotonic) -> ScanResult`; `MAX_SWEEP = 1024`.

Behaviour: SSDP (`st="roku:ecp"`, `timeout_s`) runs on a thread while the sweep GETs device-info for every host of `subnet` through a bounded pool; a subnet with more than `MAX_SWEEP` addresses is not swept (SSDP still runs); SSDP addresses come from `SsdpEntry.location` matching `http://<ip>:8060`; an SSDP-only address is fetched once; addresses failing `is_allowed_ip` are dropped; `found_by` is `ssdp`, `sweep` or `ssdp+sweep`; hits sorted by IP.

- [ ] **Step 1: Failing tests** with a fake probes object and a fake transport answering device-info for chosen IPs:

```python
def test_scan_combines_ssdp_and_sweep_found_by(): ...      # .60 both, .61 sweep only, .62 ssdp only
def test_scan_sends_roku_search_target(): ...              # fake records st == "roku:ecp"
def test_scan_skips_sweep_above_1024_addresses(): ...      # "192.168.0.0/21": no device-info calls except SSDP ones
def test_scan_sweeps_a_22(): ...                           # "192.168.0.0/22" is swept
def test_scan_ignores_non_roku_answers_and_public_ssdp_locations(): ...
def test_scan_counts_and_duration(): ...
```

- [ ] **Step 2: Run, verify fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(roku): built-in scan (SSDP roku:ecp plus port 8060 sweep)`

---

### Task 5: RokuService - status, identity, commands, scans, document saves

**Files:**
- Create: `plugins/roku/service.py`, `settings.py`
- Test: `plugins/roku/tests/unit/test_roku_service.py`, `test_roku_settings.py`

**Interfaces:**
- Consumes: Tasks 2-4.
- Produces (`settings.py`): `RokuSettings(BaseModel)`: `auto_scan: Literal["never","startup","startup_and_every"] = "startup_and_every"`, `scan_every_h: int = Field(6, ge=1, le=168)`, `scan_timeout_s: float = Field(2, ge=0.5, le=10)`, `status_interval_s: int = Field(10, ge=5, le=300)`, `request_timeout_s: float = Field(2, ge=0.5, le=10)`; titles and descriptions in plain words; `scan_every_h` has `show_when={"auto_scan": "startup_and_every"}` via `setting_group("Scanning", ...)`; the other two scan fields in group "Scanning", the status/request fields in group "Live status". No required fields.
- Produces (`service.py`): `class RokuService(ctx: PluginContext, store: TvStore, ecp: EcpClient, scanner: Callable[..., ScanResult] = scan)`:
  - `list_tvs() -> dict` → `{"tvs": [tv_view...], "scan": scan_state()}` where `tv_view = asdict(saved) | {"title": ..., "status": {...}}` and status = `{reachable: bool, power: "on"|"standby"|"unknown", mode: str, active_app: {"id","name"}|None, apps: [{"id","name","type"}]|None, apps_refused: bool, wrong_device: str|None, checked_at_ms: int|None, error: str}`. A TV never polled has `reachable=False, error=""`.
  - `document() -> dict`; `save_document(text: str) -> dict` → `{"message": "Saved: 3 TVs"}` or `{"message": "Merged: 1 added, 2 updated", "skipped": [...]}`; for `MergeIps` it fetches device-info per address and lists the ones that did not answer as a Roku under `skipped` with message suffix `Skipped (no Roku answered): 192.168.1.9`. Raises `DocumentError`.
  - `start_scan() -> bool` (False if one is running; runs `run_scan` on a daemon thread); `run_scan() -> None` (also the job); `scan_state() -> dict` → `{running, started_ms, finished_ms, found, by_ssdp, by_sweep, duration_s, error}`. Subnet = `ctx.core.host().subnet`.
  - `poll_status() -> None` (the job): every saved TV, at most 8 at once; device-info; identity check; active-app when on; apps when never read or older than 3600 s and not refused; a 403 on apps sets `apps_refused`.
  - `refresh(tv_id: str) -> None`
  - `send_key(tv_id: str, key: str, action: str = "press") -> None`, `launch(tv_id: str, app: str) -> None`, `type_text(tv_id: str, text: str) -> None`, `icon(tv_id: str, app_id: str) -> tuple[bytes, str]`
  - Errors: `UnknownTv(tv_id)` (→ 404), `ValueError` from allow-lists (→ 422), `CommandError(status_code: int, message: str)`: 409 for wrong device, 502 for `EcpError` with its message.
  - After a successful command, schedule a status re-read of that TV ~1 s later (`threading.Timer`, daemon).
  - Identity (spec 5.4): a saved TV with empty `serial` adopts the first non-empty serial seen and the store is updated; a mismatch sets `wrong_device` to the answering TV's name and `reachable=False`; a command refuses with 409 and the exact mismatch message unless identity was confirmed within `2 * status_interval_s`; when older, the service re-reads device-info first and sends only on a match.
  - `settings_changed(settings: RokuSettings) -> None` rebuilds the client timeout.

- [ ] **Step 1: Failing tests** (fake transport keyed by IP with switchable power/mode/serial/answering; `FakeClock`; an in-memory `TvStore` stand-in or the real one on the integration fixtures):

```python
def test_poll_marks_on_tv_with_app_and_apps(): ...
def test_poll_standby_skips_active_app(): ...
def test_poll_limited_sets_apps_refused(): ...
def test_poll_unanswering_tv_is_not_reachable_with_message(): ...
def test_serial_adopted_and_saved_when_missing(): ...
def test_wrong_device_blocks_status_and_commands():
    # saved serial S1, TV at that ip now answers S2 named "Bedroom TV"
    with pytest.raises(CommandError) as e: service.send_key(tv_id, "PowerOff")
    assert e.value.status_code == 409
    assert e.value.message == "A different Roku, Bedroom TV, now answers at this address. Run a scan in Settings."
    assert transport.posts == []
def test_stale_identity_is_rechecked_before_a_command(): ...
def test_send_key_posts_allowed_path_and_schedules_refresh(): ...
def test_send_key_to_unanswering_tv_returns_message_quickly():  # Review Focus 4: transport raises TimeoutError; CommandError 502 with the "isn't answering" message
def test_type_text_posts_one_keypress_per_character_in_order(): ...
def test_unknown_tv_raises(): ...
def test_save_document_replace_and_merge_messages(): ...
def test_save_ip_list_reports_skipped(): ...
def test_scan_merges_hits_and_second_scan_while_running_is_refused(): ...
def test_settings_defaults_and_bounds(): ...
```

- [ ] **Step 2: Run, verify fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run** `uv run pytest plugins/roku/tests/unit -q` → PASS.
- [ ] **Step 5: Commit** `feat(roku): service - live status, identity check, commands, scans, document saves`

---

### Task 6: Plugin wiring and API

**Files:**
- Create: `plugins/roku/plugin.py`, `routes.py`, `static/ui.js` (stub: `export default function register(ui) {}` until Task 7)
- Modify: `plugins/roku/__init__.py` (`from .plugin import RokuPlugin` and `plugin_class = RokuPlugin`). **No entry point in `pyproject.toml`.**
- Modify (core): `src/netview/presentation/cli.py` — `serve` (and `scan`, if it loads plugins) gains a repeatable `--plugin-dir PATH` option that appends to `AppSettings.plugin_dirs`; test it next to the existing CLI tests
- Test: `plugins/roku/tests/integration/test_roku_api.py`

**Interfaces:**
- Consumes: `RokuService`, `TvStore`, `storage_spec()`, `EcpClient(urllib_transport, ...)`.
- Produces: `RokuPlugin`, exported as `plugin_class` (manifest per Global Constraints; `setup` builds the service; `router()` returns an empty `APIRouter` before setup, like GSM7248; `jobs()` → `status` every `status_interval_s` (initial delay 3 s, timeout `min(2 * interval, 60)`), and `scan` per `auto_scan`: `never` none; `startup` interval `10**9` s, initial delay 5 s; `startup_and_every` interval `scan_every_h * 3600`, initial delay 5 s; scan timeout 120 s). `build_router(service) -> APIRouter`, plain `def` routes (ECP calls block):

| Route | Result |
|---|---|
| `GET /tvs` | `service.list_tvs()` |
| `GET /tvs/document` | `service.document()` |
| `PUT /tvs/document` | body `{"text": str}`; 200 `{"message", "skipped"?}`; `DocumentError` → 422 `{"error": message}` |
| `POST /scan` | 202 `{"started": true}`; 409 `{"error": "scan already running"}` |
| `GET /scan` | `service.scan_state()` |
| `POST /tvs/{id}/key/{key}?action=press|down|up` | 200 `{"ok": true}` |
| `POST /tvs/{id}/launch/{app}` | 200 `{"ok": true}` |
| `POST /tvs/{id}/text` | body `{"text": str}` |
| `POST /tvs/{id}/refresh` | 202 |
| `GET /tvs/{id}/icon/{app}` | image bytes with the TV's content type; cached in memory (builder picks size/lifetime) |
| `GET /scripts/find_rokus.py`, `GET /scripts/find_rokus.ps1` | `text/plain; charset=utf-8` from `static/` (files arrive in Task 7; 404 until then) |

Errors: `UnknownTv` → 404 `{"error": "Unknown TV"}`; `ValueError` → 422 `{"error": str(e)}`; `CommandError` → its status with `{"error": message}`.

- [ ] **Step 1: Failing tests** using the `make_client` pattern from `tests/integration/plugins/gsm7248/test_api.py`, with `netview.bootstrap.discover_plugin_classes` monkeypatched to return `[DiscoveredPlugin("folder:roku", RokuPlugin, None)]` (the conftest-loaded class), `netview_local_plugins.roku.plugin.urllib_transport` monkeypatched to a fake transport, and `FakeServiceProbes`:

```python
def test_folder_discovery_finds_roku_without_error():  # discover_plugin_classes(extra_dirs=[PLUGINS_DIR]) -> a roku entry, error None
def test_roku_is_not_an_entry_point():  # no entry point named roku in group netview.plugins
def test_plugin_loads_with_permissions():  # state active; permissions include "network:control"
def test_empty_list_then_put_document_then_list(): ...
def test_put_document_error_is_422_with_message(): ...
def test_scan_202_then_409_while_running(): ...
def test_key_press_reaches_tv_and_bad_key_is_422(): ...
def test_launch_and_text(): ...
def test_command_to_limited_tv_is_502_with_limited_message(): ...
def test_unknown_tv_is_404(): ...
def test_writes_need_the_netview_header(): ...   # no X-Netview → refused as for other plugins
def test_jobs_follow_auto_scan_setting(): ...    # RecordingScheduler: never → no "scan" job
```

- [ ] **Step 2: Run, verify fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run** the gate command (Global Constraints) → PASS/clean.
- [ ] **Step 5: Commit** `feat(roku): plugin wiring, jobs and API`

---

### Task 7: UI store, nav gating and Settings › Roku

**Files:**
- Create: `plugins/roku/static/store.js`, `settings.js`, `roku.css`, `find_rokus.py` (copy of the library file), `find_rokus.ps1` (from the `src-ps` block of the reference cheat sheet)
- Modify: `static/ui.js`
- Test: `plugins/roku/tests/js/roku-store.test.mjs`, `plugins/roku/tests/js/roku-settings.test.mjs`, `plugins/roku/tests/unit/test_roku_script_copies.py`

**Interfaces:**
- Produces (`store.js`): `createStore(ui, { now = Date.now, setTimer = setTimeout }) -> { get(): {tvs, scan} | null, load(): Promise, unavailable(): string | null, subscribe(fn): unsubscribe }`. `load()` GETs `${ui.apiBase}/tvs`; when the result's TV count goes 0↔non-0 it calls `ui.requestRender()`; while the list is empty it re-loads every 30 s. `unavailable()` returns the exact tooltip from Global Constraints when loaded and empty, `null` otherwise (and `null` before the first load completes, so the tab is not flashed off).
- Produces (`settings.js`): `renderRokuSettings(body, {apiBase, apiGet, apiSend, util}, store)` drawing three sections in this order: **Scan** (last-scan summary `Last scan {time}: {n} found ({a} by SSDP and address check, {b} by address check only). Took {s} s.` or `No scan yet.`; **Scan for TVs now** button disabled while running, polling `GET scan` every 1 s until done, then `store.load()`), **Saved TVs** (textarea with `JSON.stringify(document, null, 2)`, Save → `PUT tvs/document` showing the server's message or error inline, Revert, Download as `tvs.json`; one-sentence explanation of replace vs merge and that scans never remove or rename), **Run the scan yourself** (Windows / macOS-Linux switch; library command `python R:\source\scripts\network-tools\scripts\find_rokus.py --out rokus.json` or `python3 find_rokus.py --out rokus.json`; options line; paste-in wrappers built from `GET scripts/find_rokus.py`: Windows `@'\n{script}\n'@ | python -`, macOS/Linux `python3 - <<'EOF'\n{script}\nEOF`; a details block with the PowerShell-only script from `GET scripts/find_rokus.ps1`; each with Copy; closing line `Paste what it prints into Saved TVs above and press Save.`). Pure helpers exported for tests: `scanSummary(scan) -> string`, `pasteWrapper(os, script) -> string`.
- `ui.js` registers `ui.slot("settings.section", { title: "Roku", render })` and the `page` slot (page body arrives in Task 8; until then `mount` shows an empty card) with `unavailable: () => store.unavailable()`.

- [ ] **Step 1: Failing tests**

```js
test("unavailable() is null before load, the tooltip when empty, null with TVs", async () => { ... });
test("store re-loads every 30 s only while empty and requests a render when emptiness flips", async () => { ... });
test("scanSummary wording", () => {
  assert.equal(scanSummary({ finished_ms: null }), "No scan yet.");
  assert.match(scanSummary({ finished_ms: 1, found: 3, by_ssdp: 2, by_sweep: 3, duration_s: 4.6 }), /3 found .* Took 4\.6 s\./);
});
test("pasteWrapper wraps for each OS", () => {
  assert.equal(pasteWrapper("win", "x"), "@'\nx\n'@ | python -");
  assert.equal(pasteWrapper("unix", "x"), "python3 - <<'EOF'\nx\nEOF");
});
```

```python
LIB = Path(r"R:\source\scripts\network-tools\scripts\find_rokus.py")
STATIC = ROKU_DIR / "static"
def test_python_copy_is_identical_to_library():
    if not LIB.exists(): pytest.skip("shared scripts library not on this machine")
    assert (STATIC / "find_rokus.py").read_bytes() == LIB.read_bytes()
@pytest.mark.parametrize("name", ["find_rokus.py", "find_rokus.ps1"])
def test_copies_are_ascii_and_paste_safe(name):
    text = (STATIC / name).read_bytes().decode("ascii")
    assert not any(line in ("EOF", "'@") for line in text.splitlines())
```

- [ ] **Step 2: Run, verify fail.** - [ ] **Step 3: Implement.** Style with existing classes (`.card`, `.seg`, `.note`, `.err`/`.err.ok`, `button.primary`, `button.small`) and `roku.css` for the rest (tokens only); load `roku.css` the way GSM7248's `ui.js` loads `gsm7248.css`.
- [ ] **Step 4: Run** `npm test && uv run pytest plugins/roku/tests/unit -q` → PASS.
- [ ] **Step 5: Add the project to the library script** — in `R:\source\scripts\scripts.json`, append to `find_rokus.py`'s `projects`: `"HomeLab netview - Roku plugin (netview/plugins/roku) manual scan and bundled copy (2026-11-11)"`; set its `"updated"` to `2026-11-11`; confirm the file is valid JSON (`python -c "import json;json.load(open(r'R:\source\scripts\scripts.json'))"`). This edit is outside the netview repo and is not committed there.
- [ ] **Step 6: Commit** `feat(roku): UI store with nav gating, Settings › Roku, manual scan scripts`

---

### Task 8: Roku page - tabs, toggle, TV drawing, Control view

**Files:**
- Create: `static/tv.js`, `static/page.js`, `static/control.js`
- Modify: `static/ui.js`, `static/roku.css`
- Test: `plugins/roku/tests/js/roku-tv.test.mjs`, `plugins/roku/tests/js/roku-control.test.mjs`

**Interfaces:**
- Consumes: `createStore` (Task 7), the API (Task 6).
- Produces:
  - `tv.js`: `tvSvg({ on: boolean, name: string }) -> string`, ported from `tvSvg()` in `HomeLab/mockups/roku-plugin-mockup.html` (keep its drawing and colours; feet `#3c3f46`; gradient ids prefixed `rk-`; `role="img"`, `aria-label="{name} is on"` / `"{name} is off"`; red standby light only when off).
  - `page.js`: `createPage(ui, store) -> {id: "tvs", title: "Roku", mount(el, ctx) -> {update, destroy}}`; tab row `.tabs` (one `[role=tab]` per TV, label `title`, dot class `on` | `lim` | none, tooltip `ip · state · Network access: X`) and `.seg` **Control | Commands** right-justified on the same line; remembers TV id and view in `localStorage` (`netview.roku.tv`, `netview.roku.view`), default view `control`; re-loads the store every 5 s while mounted and on `update`; on mount and on selecting a tab it sends `POST tvs/{id}/refresh` so apps and status are fresh when the Control view opens (spec 5.4).
  - `control.js`: `renderControl(el, tv, api)`; pure exports `keyForEvent(e) -> string | null` and `createHold(send, target) -> {down(key), up()}`.

Control view content and behaviour: spec 7.1 exactly (TV card with drawing and facts; Remote card; Apps card using `GET tvs/{id}/icon/{app}` images and the running app outlined; when `apps_refused`, a note and the cheat sheet's common-apps list, disabled; Type text card; Limited callout with the exact path and all controls disabled; Not answering and wrong-device notes with controls disabled; for `tv: false` hide power and input buttons). Commands go through `ui.apiSend("POST", ...)`; each press shows `toast` (import from `/static/js/toast.js`) with `Sent {Key} to {title}` or the server's error with kind `bad`. Power button: label `Off` and key `PowerOff` when on, `On` and `PowerOn` otherwise.

`keyForEvent`: ignore when `e.target` is an input/textarea/select or has modifier keys; `ArrowUp/Down/Left/Right` → `Up/Down/Left/Right`; `Enter` → `Select`; `Backspace` and `Escape` → `Back`; `h`/`H` → `Home`; ` ` → `Play`; else null.

`createHold`: `down(key)` sends `key/{key}?action=down`; `up()` sends `?action=up` for the held key once (idempotent); the page wires `up()` to `pointerup`, `pointerleave`, `pointercancel` on the button and to `window` `blur`. Holdable keys: Up, Down, Left, Right, Rev, Fwd; a short click on them still sends one keypress (down within 300 ms then up → send `press` instead of down/up).

- [ ] **Step 1: Failing tests**

```js
test("tvSvg on and off", () => {
  const on = tvSvg({ on: true, name: "Living Room TV" }), off = tvSvg({ on: false, name: "Living Room TV" });
  assert.match(on, /aria-label="Living Room TV is on"/); assert.match(off, /is off/);
  assert.match(on, /HOME/); assert.doesNotMatch(off, /HOME/);
  assert.match(off, /#e0463a/); assert.doesNotMatch(on, /#e0463a/);
});
test("keyForEvent maps keys and ignores text fields and modifiers", () => { ... });
test("hold sends keyup on leave and on blur, once", () => {   // Review Focus 5
  const sent = []; const h = createHold((k, a) => sent.push([k, a]), fakeTimers);
  h.down("Right"); fakeTimers.advance(400); h.up(); h.up();
  assert.deepEqual(sent, [["Right", "down"], ["Right", "up"]]);
});
test("a quick click on a holdable key sends one press", () => { ... });
test("tab dot classes and tooltip text", () => { ... });   // export a pure tabsHtml(tvs, selectedId) from page.js
```

- [ ] **Step 2: Run, verify fail.** - [ ] **Step 3: Implement.** Layout per the mockup (`.rk-grid` two columns, one column under 900 px; no sideways scroll at 375 px).
- [ ] **Step 4: Run** `npm test` → PASS.
- [ ] **Step 5: Commit** `feat(roku): Roku page with TV tabs, Control view and TV drawing`

---

### Task 9: Commands view (cheat sheet)

**Files:**
- Create: `static/cheatsheet-data.js` (the `READ`, `CONTROL`, `KEYS`, `APPS`, `RECIPES` data from `docs/superpowers/reference/roku-ecp-cheat-sheet.html`, verbatim in content; `RECIPES` entries that use `readField` become `{t, read: [path, tag]}`), `static/commands.js`
- Modify: `static/page.js`, `static/roku.css`
- Test: `plugins/roku/tests/js/roku-commands.test.mjs`

**Interfaces:**
- Produces: `buildCommand(shell: "ps"|"cmd"|"curl", method: "GET"|"POST", url: string, out?: string) -> string` and `readField(shell, url, tag) -> string`, both behaving exactly as `build()` and `readField()` in the reference cheat sheet; `renderCommands(el, tv, { shell, onShell })`.

Content per spec 7.2: bar with **Commands for** PowerShell / Command Prompt / macOS-Linux (default `ps` when `navigator.platform` matches `/win/i`, else `curl`; remembered in `netview.roku.shell`), `Every command targets {title} at {ip}:8060`, section links; sections Recipes, Read state, Control, Remote keys (click a key to show its command; the type-text builder producing one `Lit_` line per character), App IDs (this TV's `status.apps` when present, else `APPS`), Network access settings table, What the responses mean. Every command has Copy; on clipboard failure select the text and toast `Copy is blocked here. The command is selected; press Ctrl+C.` Limited TVs show a one-line 403 callout.

- [ ] **Step 1: Failing tests** — assert byte-equal output against strings taken from the reference file for each shell:

```js
const U = "http://192.168.1.60:8060";
test("POST commands per shell", () => {
  assert.equal(buildCommand("ps", "POST", U + "/keypress/Home"), '(Invoke-WebRequest "http://192.168.1.60:8060/keypress/Home" -Method Post -UseBasicParsing).StatusCode');
  assert.equal(buildCommand("curl", "POST", U + "/keypress/Home"), 'curl -X POST "http://192.168.1.60:8060/keypress/Home"');
  assert.equal(buildCommand("cmd", "POST", U + "/keypress/Home"), 'curl -X POST "http://192.168.1.60:8060/keypress/Home"');
});
test("GET with and without output file per shell", () => { ... });
test("readField per shell", () => { ... });       // grep/sed, findstr, Select-Xml forms from the reference
test("data matches the reference key groups and app ids", () => { ... });  // e.g. KEYS has 8 groups incl. "Antenna channels"; APPS has Netflix "12"
```

- [ ] **Step 2: Run, verify fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run** `npm test` → PASS.
- [ ] **Step 5: Commit** `feat(roku): Commands view - the ECP cheat sheet for the selected TV`

---

### Task 10: Whole-branch checks, browser pass, live check (orchestrator, not a subagent)

- [ ] **Step 1:** the gate command (Global Constraints) → all clean.
- [ ] **Step 2: Browser pass against a fake.** Start netview with `--plugin-dir <worktree>/plugins` on a scratch data dir with the plugin's `urllib_transport` swapped for a fake serving the Task 2 fixtures for 192.168.1.60 (on, Default), .61 (standby), .62 (Limited) (a small `serve_fake_roku.py` in the session scratchpad; never the real `netview-dev` data dir). Check, with screenshots: tab disabled with empty list and its click opening Settings › Roku; paste the fixture scan output, Save, tab enables without reload; Control view for each TV state; Power toggles the drawing after the status re-read; Commands view for each shell; Graphite and Daylight themes; 375 px width; keyboard control; hold-to-scroll sends down/up.
- [ ] **Step 3: Live check on the real TVs** (needs the user's OK in chat before any command is sent): run the scan from Settings against the real LAN, confirm both TVs appear, then with permission press Home and Vol− once on one TV.
- [ ] **Step 4:** After merge, add `--plugin-dir R:/source/claude projects/HomeLab/netview/plugins` to the `netview` entry in `HomeLab/.claude/launch.json` (with the user's OK), and update the netview memory file with what shipped.
