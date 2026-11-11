# GSM7248 plugin, phase 1 (read-only monitoring): implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A built-in NetView plugin, `gsm7248`, that reads the NETGEAR GSM7248 over SNMP. It shows the switch, its ports, VLANs, spanning tree, LAGs, per-port traffic and which NetView device is on which port, and raises events when any of that changes.

**Architecture:**
- A new core `SnmpClient` port, with a pysnmp adapter, reaches plugins as `ctx.snmp` (SDK 1.1).
- Core plugin settings gain secret fields, masked everywhere outside storage.
- The plugin is layered inside:
  - pure `model/` and `analysis.py`, plus `mibs.py` decoders;
  - then `collector.py`, `storage.py` and `service.py`, which do the input and output;
  - then `routes.py` and `static/` for the API and the UI.
- Tasks 1–8 need only `main`. Task 9 waits for plan 2 (parity) to be merged and this branch to be rebased.

**Tech Stack:** Python 3.11+, pysnmp ≥7.1 (lextudio, asyncio API), FastAPI, SQLAlchemy 2 and Alembic (a per-plugin branch), pydantic v2 `SecretStr`, plain-JS ES modules, pytest, `node --test` through `npm test`.

**Spec:** `docs/superpowers/specs/2026-11-10-gsm7248-plugin-design.md`. Parent spec: `docs/superpowers/specs/2026-11-10-netview-design.md`, especially §7 and §13.

## Global Constraints

- Clean Architecture. The import-linter contracts in `pyproject.toml` must keep passing.
- Plugin code imports only `netview.sdk`, the stdlib, `pydantic`, `fastapi`, `sqlalchemy` and, in migrations only, `alembic`. Never `netview.application`, `netview.infrastructure` or other plugins.
- The plugin's claim source is `SOURCE = "GSM7248"` for hints, types and names. That keeps it apart from future SNMP plugins, such as the iDRAC or APs, because hints are replaced per `(key, source)`. The `switch_id` is the constant `"gsm7248"` in phase 1, since there is a single switch.
- `pysnmp` is imported only in `src/netview/infrastructure/net/snmp.py`.
- The plugin id is `gsm7248`. Every table is prefixed `gsm7248_`. The API is under `/api/v1/plugins/gsm7248/` and static files under `/plugins/gsm7248/static/`.
- `SDK_VERSION` goes from 1.0 to `1.1`. Existing plugins declaring `>=1.0,<2` keep loading.
- The switch address is a setting with default `192.168.1.4`. No IP, community or key is ever a constant in code.
- Secrets (SNMP community, v3 auth and privacy keys) never appear in an API response, a log line, an event, an exception message or the DOM. The mask string is `********`.
- Requests to one SNMP target are serialised: at most 1 in flight.
- Never write nicknames. Claims go only through `ctx.core.claim`, and events only through `ctx.core.add_event(EventKind.PLUGIN, text, ip)`.
- Name claims use source `"GSM7248"` and rank `8`.
- UI rules:
  - theme tokens only, no hard-coded colours;
  - CSP-safe: no inline script and no inline event handlers;
  - state is never shown by colour alone;
  - works at 375 px with no page-level horizontal scroll.
- mypy strict covers `domain`, `application` and `sdk`. The plugin must pass `mypy src` too.
- Checks that must be green at the end of every task:
  - `uv run pytest -q`
  - `uv run ruff check .`
  - `uv run ruff format --check src tests` (not `.`, because ruff also reformats code blocks in Markdown)
  - `uv run mypy src`
  - `uv run lint-imports`
  - `npm test`
- Commit only on the branch `feature/gsm7248-plugin`, in the worktree `R:/source/claude projects/HomeLab/netview-gsm7248`. Never touch `R:/source/claude projects/HomeLab/netview`, which is the plan-2 checkout, or `HomeLab/network/**`.

## Review Focus

1. **A secret survives a round trip.** If a user opens Settings and saves without retyping the community, the stored community is kept, not replaced by `********` or emptied. Owned by Task 1 (`test_patch_with_mask_keeps_secret`, `test_omitted_secret_keeps_secret`, and the JS `secret field left blank is omitted`).
2. **The switch is unreachable or credentials are wrong.** That means one event (not one per poll), backoff, a tile that says "unreachable", an API that still answers from the last snapshot, and an error message with no secret in it. Owned by Task 6 (`test_unreachable_emits_one_event_and_backs_off`, `test_auth_error_message_has_no_secret`).
3. **Counters reset or wrap.** A reboot, a counter clear, or a 32-bit wrap on a port without HC counters must never chart a negative or a huge spike. Owned by Task 4 (`test_counter_reset_returns_none`, `test_32bit_wrap`, `test_reboot_detected_from_uptime`).
4. **A restart, or the first polls, repeat events.** Restarting NetView must not re-announce every MAC as new or every link as up. Nor may the first bridge poll arriving after the first status poll. Owned by Tasks 4, 5 and 6 (`test_first_bridge_poll_after_status_emits_nothing`, `test_snapshot_round_trip`, `test_restart_does_not_repeat_events`).
5. **Proxmox guests flood the MAC table.** Five or more MACs on 0/5 must not be attributed per-device traffic, and guest MACs ageing out must not create events. Owned by Task 4 (`test_multi_mac_port_not_single_device`, `test_mac_gone_only_for_known_devices`).

---

## File structure

```
src/netview/
  application/ports/snmp.py                 # NEW  SnmpClient port, SnmpTarget, SnmpV2c, SnmpV3, errors, Oid, parse_oid
  application/plugins/context.py            # MOD  PluginContext gains `snmp: SnmpClient`
  application/plugins/manifest.py           # MOD  SDK_VERSION = "1.1"
  infrastructure/net/snmp.py                # NEW  PysnmpClient adapter
  infrastructure/plugins/context.py         # MOD  DefaultPluginContext takes and exposes snmp
  infrastructure/plugins/settings_codec.py  # NEW  secret-aware dump and merge helpers
  infrastructure/plugins/host.py            # MOD  uses settings_codec for storage, display and PATCH
  bootstrap.py                              # MOD  builds PysnmpClient and passes it to the context factory
  sdk/__init__.py                           # MOD  re-exports the SNMP names
  sdk/testing/fakes.py                      # MOD  FakeSnmpClient, FakeCore, FakePluginContext
  sdk/testing/contract.py                   # MOD  _FakeContext gains snmp
  sdk/testing/snmpwalk.py                   # NEW  parse net-snmp `snmpwalk -On` text into rows
  presentation/web/static/js/settings/schema-form.js   # MOD  "secret" field kind
  plugins/builtin/gsm7248/
    __init__.py
    plugin.py  settings.py  mibs.py  analysis.py  collector.py  service.py  storage.py  routes.py
    model/__init__.py  switch.py  port.py  mac.py  vlan.py  snapshot.py  codec.py
    migrations/versions/0001_initial.py      # run by the core's shared alembic env (infrastructure/db/migrate.py)
    static/ui.js  static/page.js  static/port-grid.js  static/gsm7248.css
docs/gsm7248-setup.md                        # NEW  switch-side SNMP runbook
tests/
  fixtures/gsm7248/walk_basic.txt            # NEW  synthetic walk (layout of HomeLab/docs/hardware/gsm7248.md)
  unit/infrastructure/test_settings_codec.py
  unit/application/test_snmp_port.py
  integration/net/test_pysnmp_client.py  integration/net/snmp_responder.py
  unit/plugins/gsm7248/test_mibs.py  test_analysis.py  test_codec.py  test_service.py
  integration/plugins/gsm7248/test_storage.py  test_api.py  test_plugin_load.py
  js/gsm7248-ui.test.mjs
pyproject.toml                               # MOD  pysnmp dependency, entry point, package data for migrations
```

---

### Task 1: Secret settings in the core

**Files:**
- Create: `src/netview/infrastructure/plugins/settings_codec.py`
- Modify: `src/netview/infrastructure/plugins/host.py:163-186`, `host.py:280-300` (`_load` and `update_settings`)
- Modify: `src/netview/presentation/web/static/js/settings/schema-form.js` (field kinds, around lines 49–130)
- Create: `tests/integration/plugins/sample_plugins/secretive.py`, a sample plugin with `key: SecretStr | None = None`
- Test: `tests/unit/infrastructure/test_settings_codec.py`, `tests/integration/plugins/test_host.py` (add cases, using the `env` fixture from `tests/integration/plugins/conftest.py`), `tests/js/schema-form.test.mjs` (add cases). `tests/integration/api/test_plugins_api.py` uses `StubPluginAdmin`, so it never runs the real host. Don't put masking tests there.

**Interfaces:**
- Produces:
  - `MASK: Final = "********"`
  - `dump_for_storage(model: BaseModel) -> dict[str, Any]`: JSON-safe, with `SecretStr` values revealed.
  - `dump_for_display(model: BaseModel) -> dict[str, Any]`: JSON-safe. A set secret becomes `MASK` and an unset one (None) becomes `None`.
  - `merge_patch(stored: dict[str, Any], patch: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]`: for a secret field, a patch value of `MASK`, `""` or a missing key keeps `stored`. An explicit `None` clears it.
  - `mask_raw(raw: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]`: masks the secret keys of an **unvalidated** dict. It is used for disabled and failed plugins, whose settings never go through `model_validate`.
  - `safe_validation_message(exc: pydantic.ValidationError) -> str`: built from `exc.errors(include_input=False)` (location and message only), so no input value can echo a secret.
  - The JSON schema of a `SecretStr` field already carries `"format": "password", "writeOnly": true` from pydantic. schema-form maps that to kind `"secret"`.
- `PluginInfo.settings`, which the API returns, always holds `dump_for_display` output. `plugin_state.settings`, the DB copy, always holds `dump_for_storage` output. `ctx.settings` is the validated model holding the real `SecretStr`.

- [ ] **Step 1: Write the failing unit tests** in `test_settings_codec.py`, using a test model `class M(BaseModel): host: str = "h"; key: SecretStr | None = None`:
  - `test_storage_reveals_secret`: `dump_for_storage(M(key="s3"))["key"] == "s3"`
  - `test_display_masks_secret`: `dump_for_display(M(key="s3"))["key"] == "********"`, and `dump_for_display(M())["key"] is None`
  - `test_patch_with_mask_keeps_secret`: `merge_patch({"host":"h","key":"s3"}, {"key":"********","host":"x"}, M) == {"host":"x","key":"s3"}`
  - `test_omitted_secret_keeps_secret`: `merge_patch({"key":"s3"}, {"host":"y"}, M)["key"] == "s3"`
  - `test_blank_secret_keeps_secret`: `merge_patch({"key":"s3"}, {"key":""}, M)["key"] == "s3"`
  - `test_none_clears_secret`: `merge_patch({"key":"s3"}, {"key":None}, M)["key"] is None`
  - `test_nested_and_optional_detection`: the codec finds `SecretStr | None` fields from `model.model_fields` annotations. Top-level fields are enough.
- [ ] **Step 2: Run** `uv run pytest tests/unit/infrastructure/test_settings_codec.py -q`. Expected: FAIL, ImportError.
- [ ] **Step 3: Implement `settings_codec.py`.** Detect secret fields with `typing.get_args` on the annotation, so both `SecretStr` and `SecretStr | None` count. The display and storage functions build on `model.model_dump(mode="json")` and then overwrite the secret keys.
- [ ] **Step 4: Run the test again.** Expected: PASS.
- [ ] **Step 5: Write the failing host tests** in `tests/integration/plugins/test_host.py`. Pass `SecretivePlugin` to `env.host([...])`; sample plugins are passed as classes, not registered.
  - `test_get_plugin_masks_secret`: after `host.update_settings("secretive", {"key": "s3cr3t"})`, `host.get("secretive").settings["key"] == "********"`, and `"s3cr3t" not in PluginOut.model_validate(info).model_dump_json()`.
  - `test_patch_mask_round_trip_keeps_secret`: after `update_settings` with `key: "********"`, the record's live `ctx.settings.key.get_secret_value() == "s3cr3t"`, and the stored `plugin_state` still holds `"s3cr3t"`.
  - `test_settings_schema_marks_password`: `settings_schema["properties"]["key"]` contains `"writeOnly": True`. Follow `anyOf` if present.
  - `test_disabled_plugin_masks_secret`: seed the state as disabled with `{"key": "s3cr3t"}`; `info.settings["key"] == "********"`.
  - `test_invalid_stored_settings_error_has_no_secret`: seed `{"key": 12345, "level": "not-an-int"}`, so the plugin fails to load; `"12345"` is in neither `info.error` nor any captured log record.
- [ ] **Step 6: Change `host.py`:**
  - In `_load`:
    - The line `info.settings = dict(state.settings)` (host.py:174) becomes `info.settings = mask_raw(state.settings, settings_model)` when there is a model.
    - After successful validation, set `info.settings = dump_for_display(settings)`.
    - `raise ValueError(f"invalid stored settings: {safe_validation_message(exc)}")`.
  - In `update_settings`:
    - `merged = merge_patch(<stored settings read from plugin_state in the same uow>, values, model)`. The merge must start from the **stored**, revealed settings, not from `info.settings`, which is masked.
    - Validate, store `dump_for_storage(new)`, and set `info.settings = dump_for_display(new)`.
    - Raise `ValidationError(safe_validation_message(exc))`.
- [ ] **Step 7: Run** `uv run pytest tests/integration/plugins/test_host.py -q`. Expected: PASS.
- [ ] **Step 8: Write the failing JS tests** in `tests/js/schema-form.test.mjs`:
  - `secret field renders password input`: for a schema property `{type:"string", format:"password", writeOnly:true}`, or the same inside `anyOf` with `null`, the HTML contains `type="password"` and `autocomplete="new-password"`, and the value attribute is empty.
  - `secret field shows set state`: when the current value is `"********"`, the field's description or placeholder says `set`; when it is `null`, it says `not set`.
  - `secret field left blank is omitted`: reading the form with the password input empty gives an object **without** that key.
- [ ] **Step 9: Implement the `"secret"` kind in `schema-form.js`.** Detect `writeOnly === true || format === "password"` before the generic `"string"` kind. Render `<input type="password" autocomplete="new-password" value="" placeholder="set"|"not set">`, and drop the key from the result when the input is empty.
- [ ] **Step 10: Run** `npm test` and the full check list. Expected: everything passes.
- [ ] **Step 11: Commit.** `git commit -m "feat(core): secret plugin settings, masked outside storage"`

---

### Task 2: SNMP port, pysnmp adapter, `ctx.snmp`, SDK 1.1

**Files:**
- Create: `src/netview/application/ports/snmp.py`, `src/netview/infrastructure/net/snmp.py`, `src/netview/sdk/testing/snmpwalk.py`
- Modify: `src/netview/application/plugins/context.py`, `src/netview/application/plugins/manifest.py` (`SDK_VERSION`), `src/netview/infrastructure/plugins/context.py`, `src/netview/bootstrap.py:142-145`, `src/netview/sdk/__init__.py`, `src/netview/sdk/testing/fakes.py`, `pyproject.toml` (`pysnmp>=7.1,<8` in `dependencies`)
- Test: `tests/unit/application/test_snmp_port.py`, `tests/unit/sdk/test_snmpwalk.py`, `tests/integration/net/snmp_responder.py`, `tests/integration/net/test_pysnmp_client.py`

**Interfaces:**
- Produces, in `application/ports/snmp.py` and re-exported from `netview.sdk`:

  ```python
  Oid = tuple[int, ...]
  SnmpValue = int | str | bytes | Oid | None
  # int: Integer, Counter32/64, Gauge32 and TimeTicks (hundredths of a second)
  # str: IpAddress, as a dotted quad
  # bytes: OctetString, raw
  # Oid: an OBJECT IDENTIFIER value
  # None: noSuchObject, noSuchInstance or endOfMibView


  @dataclass(frozen=True)
  class SnmpV2c:
      community: str


  @dataclass(frozen=True)
  class SnmpV3:
      user: str
      auth_protocol: Literal["none", "md5", "sha"]
      auth_key: str | None
      priv_protocol: Literal["none", "des", "aes128"]
      priv_key: str | None


  @dataclass(frozen=True)
  class SnmpTarget:
      host: str
      credentials: SnmpV2c | SnmpV3
      port: int = 161
      timeout_s: float = 2.0
      retries: int = 1


  class SnmpError(Exception): ...


  class SnmpTimeout(SnmpError): ...


  class SnmpAuthError(SnmpError): ...


  class SnmpClient(Protocol):
      def get(self, target: SnmpTarget, oids: Sequence[Oid]) -> dict[Oid, SnmpValue]: ...
      def walk(
          self, target: SnmpTarget, prefix: Oid, max_rows: int = 10_000
      ) -> list[tuple[Oid, SnmpValue]]: ...


  def parse_oid(text: str) -> Oid: ...  # accepts "1.3.6" and ".1.3.6"
  ```

  - `SnmpV2c` and `SnmpV3` define `__repr__` without the secret, as `SnmpV2c(community=***)`.
  - Exception messages never include credentials.
- `PluginContext` gains `snmp: SnmpClient`.
- `FakeSnmpClient(rows: Sequence[tuple[Oid, SnmpValue]])`, with `FakeSnmpClient.from_walk_file(path: Path)`:
  - `get` returns None for a missing OID;
  - `walk` returns the rows under the prefix in OID order;
  - `fail_with: SnmpError | None` makes every call raise;
  - `calls: list[tuple[str, Oid]]` records each call.
- More fakes in `sdk/testing/fakes.py`, which Task 6 needs:
  - `FakeCore`:
    - `devices_list: list[DeviceView]`, served by `devices()`;
    - it records `claims: list[NameClaim | TypeClaim | Hint]` from `claim()`, and `events: list[tuple[EventKind, str, str | None]]` from `add_event()`.
  - `FakePluginContext(settings, *, snmp: SnmpClient, core: FakeCore, uow_factory=None, clock=None)`, which meets the `PluginContext` protocol:
    - `net` is a stub whose `local_ip()` returns `"192.168.1.95"` and `default_gateway(ip)` returns `"192.168.1.1"`;
    - `vendors.vendor(mac)` returns `""`;
    - `clock` is a settable fake clock.
  - `sdk/testing/contract.py` `_FakeContext` gains `snmp = FakeSnmpClient([])`.
- `parse_snmpwalk(text: str) -> list[tuple[Oid, SnmpValue]]` reads net-snmp `-On` output. It handles `STRING:` (quoted, as UTF-8 bytes), `Hex-STRING:` (bytes), `INTEGER:` (including `name(3)` forms), `Counter32:`, `Counter64:`, `Gauge32:`, `Timeticks: (n)`, `OID:`, `IpAddress:`, and `""`.
- Adapter: `PysnmpClient(max_in_flight_per_host: int = 1)`.
  - It runs one private asyncio event loop on a daemon thread, and its sync methods submit coroutines with `run_coroutine_threadsafe(...).result(timeout=...)`.
  - `walk` uses GETBULK (`max_repetitions=25`) for v2c and v3.
  - It keeps one `threading.Semaphore` per host.
  - `close()` stops the loop. Bootstrap calls it on shutdown.

- [ ] **Step 1: Write the failing tests.**
  - `test_snmp_port.py`:
    - `test_parse_oid_leading_dot`: `parse_oid(".1.3.6.1") == (1,3,6,1)`
    - `test_parse_oid_rejects_text`: `parse_oid("a.b")` raises ValueError
    - `test_credentials_repr_hides_secret`: `"comS3cret" not in repr(SnmpV2c("comS3cret"))`, and both `"authS3cret"` and `"privS3cret"` are absent from `repr(SnmpV3("u","sha","authS3cret","des","privS3cret"))`
  - `test_snmpwalk.py`: one test per value form listed above, each with a one-line fixture, plus `test_fake_walk_prefix_order` and `test_fake_get_missing_is_none`.
- [ ] **Step 2: Run them.** Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** `ports/snmp.py`, `sdk/testing/snmpwalk.py`, `FakeSnmpClient`, `FakeCore`, `FakePluginContext`, the `_FakeContext.snmp` addition, and the re-exports in `netview.sdk`: `Oid`, `SnmpValue`, `SnmpTarget`, `SnmpV2c`, `SnmpV3`, `SnmpError`, `SnmpTimeout`, `SnmpAuthError`, `SnmpClient`, `parse_oid`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Write the failing adapter tests.**
  - `snmp_responder.py` is a pytest fixture that starts a pysnmp command responder on `127.0.0.1` with a free UDP port. It serves:
    - v2c community `public`;
    - a v3 user `nv` with SHA and DES, keys `authkey123`/`privkey123`;
    - sysDescr, sysUpTime, five `ifDescr` rows and a Counter64 `ifHCInOctets.1`.
  - `test_pysnmp_client.py` tests:
    - `test_get_v2c_sysdescr`;
    - `test_walk_v2c_ifdescr_returns_five_rows_in_order`;
    - `test_get_v3_authpriv`;
    - `test_counter64_is_int`;
    - `test_wrong_community_times_out_as_SnmpTimeout`: v2c ignores bad communities;
    - `test_wrong_v3_key_is_SnmpAuthError`;
    - `test_missing_oid_is_none`;
    - `test_walk_stops_at_prefix_end`: the responder also serves `ifType` rows after `ifDescr`, and walking `ifDescr` returns only the `ifDescr` rows;
    - `test_timeout_releases_slot`: once a call to an unresponsive port has timed out, the next call to that host starts at once and is not blocked behind the abandoned request;
    - `test_requests_to_one_host_are_serialised`: start four `walk` calls in threads, and track the peak concurrency in a wrapped responder callback or with a counter in the adapter. The peak must be 1.

  If a pysnmp responder proves impractical on Windows, mark these tests `@pytest.mark.snmp` and skip them with a clear reason. **Don't drop them.** Say so in the task report.
- [ ] **Step 6: Implement `PysnmpClient`** with `pysnmp.hlapi.v3arch.asyncio`. The pieces are `SnmpEngine` (one per client), `ContextData`, `ObjectType`, `ObjectIdentity`, `get_cmd`, `bulk_walk_cmd`, `UdpTransportTarget.create`, `CommunityData`, `UsmUserData`, and `usmHMACSHAAuthProtocol`, `usmHMACMD5AuthProtocol`, `usmDESPrivProtocol`, `usmAesCfb128Protocol`, `usmNoAuthProtocol` and `usmNoPrivProtocol`.
  - **Walks must stop at the prefix.** Call `bulk_walk_cmd(..., lexicographicMode=False, maxRows=max_rows)`. pysnmp defaults to `lexicographicMode=True`, which walks to the end of the MIB, and the switch has about 2 MB free.
  - **Map `errorIndication` by class, not by substring:**
    - `pysnmp.proto.errind.RequestTimedOut` → `SnmpTimeout`;
    - `WrongDigest`, `UnknownUserName`, `DecryptionError`, `UnsupportedSecurityLevel` and `UnknownSecurityName` → `SnmpAuthError`;
    - anything else → `SnmpError(str(errorIndication))`.

    A non-zero `errorStatus` → `SnmpError(errorStatus.prettyPrint())`.
  - **Convert values, subclasses first:**
    - `IpAddress` (a subclass of `OctetString`) → dotted str;
    - `Counter32`, `Counter64`, `Gauge32`, `Unsigned32` and `TimeTicks` (subclasses of `Integer`) → int;
    - then `Integer` → int;
    - `OctetString` → bytes (`.asOctets()`);
    - `ObjectIdentifier` → `Oid`;
    - `NoSuchObject`, `NoSuchInstance` and `EndOfMibView` → None.
  - **Timeouts:** when `.result(timeout)` expires, call `future.cancel()` and wait for the cancellation before releasing the per-host semaphore. Otherwise an abandoned coroutine keeps talking to the switch and breaks the "1 in flight" rule. The overall timeout is `timeout_s * (retries + 1) + 1`.
- [ ] **Step 7: Wire it up:**
  - `DefaultPluginContext(..., snmp: SnmpClient)`;
  - in bootstrap, `snmp = PysnmpClient()`, passed in `context_factory` and closed on shutdown, next to the scheduler stop;
  - `SDK_VERSION = "1.1"`;
  - `Container` (`bootstrap.py:67-77`) gains `snmp: PysnmpClient`, closed in the lifespan shutdown (`bootstrap.py:223-226`);
  - update every call site that builds `DefaultPluginContext`: `tests/integration/plugins/conftest.py:53` and `tests/integration/plugins/test_host_review.py:61`. Run `grep -rn "DefaultPluginContext(" src tests` to find any others;
  - update `tests/integration/test_cli_serve.py:35` so it expects `"1.1"`.
- [ ] **Step 8: Run** the full check list. Expected: all pass, and `uv run lint-imports` keeps every contract.
- [ ] **Step 9: Commit.** `git commit -m "feat(core): SNMP client port and pysnmp adapter, exposed to plugins as ctx.snmp (SDK 1.1)"`

---

### Task 3: Plugin model, codec, MIB decoders and walk fixture

**Files:**
- Create: `src/netview/plugins/builtin/gsm7248/__init__.py`, `model/{__init__,switch,port,mac,vlan,snapshot,codec}.py`, `mibs.py`
- Create: `tests/fixtures/gsm7248/walk_basic.txt`
- Test: `tests/unit/plugins/gsm7248/test_mibs.py`, `tests/unit/plugins/gsm7248/test_codec.py`

**Interfaces:**
- Produces model types: frozen dataclasses with `slots=True`, re-exported from `model/__init__.py`.
  - In `switch.py`:
    - `SwitchInfo(sys_name: str, sys_descr: str, object_id: str, uptime_cs: int, mac: str | None)`. It comes from the **status** group. `mac` is `dot1dBaseBridgeAddress`.
    - `Inventory(model: str | None, serial: str | None, firmware: str | None)`. It comes from the **topology** group (ENTITY-MIB).
    - `Health(cpu_percent: float | None, mem_free_kb: int | None, mem_total_kb: int | None)`
  - In `port.py`:
    - `Duplex = Literal["full", "half", "unknown"]`
    - `PortKind = Literal["ethernet", "lag", "other"]`
    - `Port(if_index: int, name: str, alias: str, kind: PortKind, admin_up: bool, oper_up: bool, speed_mbps: int | None, duplex: Duplex, last_change_cs: int)`. It comes from the **status** group. There is no PVID here: PVIDs live in `Snapshot.pvids` (topology) and are joined in at read time.
    - `PortCounters(if_index: int, t_ms: int, hc: bool, in_octets: int, out_octets: int, in_ucast: int, out_ucast: int, in_mcast: int, out_mcast: int, in_bcast: int, out_bcast: int, in_errors: int, out_errors: int, in_discards: int, out_discards: int)`
    - `PortRates(if_index: int, t_ms: int, in_bps: float, out_bps: float, in_err_ps: float, out_err_ps: float, in_disc_ps: float, out_disc_ps: float, util_percent: float | None)`
  - In `mac.py`: `MacEntry(mac: str, vlan: int, if_index: int | None, status: Literal["learned", "self", "mgmt", "other"])`. `mac` is lower-case and colon-separated.
  - In `vlan.py`:
    - `Vlan(vid: int, name: str, egress: frozenset[int], untagged: frozenset[int])`, where the sets hold ifIndex values;
    - `StpState = Literal["disabled","blocking","listening","learning","forwarding","broken"]`;
    - `StpPort(if_index: int, state: StpState)`;
    - `LagGroup(if_index: int, name: str, members: frozenset[int])`.
  - In `snapshot.py`:
    - `PollGroup = Literal["status", "bridge", "topology"]`
    - `GROUP_FIELDS: Mapping[PollGroup, tuple[str, ...]]`:
      - `status` owns `("info", "health", "ports")`;
      - `bridge` owns `("macs",)`;
      - `topology` owns `("inventory", "vlans", "pvids", "stp", "lags")`.
    - `Snapshot(t_ms: int, groups: frozenset[PollGroup], info: SwitchInfo | None, health: Health | None, inventory: Inventory | None, ports: tuple[Port, ...], macs: tuple[MacEntry, ...], vlans: tuple[Vlan, ...], pvids: tuple[tuple[int, int], ...], stp: tuple[StpPort, ...], lags: tuple[LagGroup, ...])`. `groups` says which groups' fields hold real data. **An empty tuple in a group that was polled is real data**, such as an empty MAC table. It never means "not polled".
    - Methods: `port(if_index) -> Port | None`, `port_by_name(name) -> Port | None`, `pvid(if_index) -> int | None`.
    - Reachability is not part of the snapshot. The service tracks it (Task 6).
  - In `codec.py`: `snapshot_to_json(s: Snapshot) -> str` and `snapshot_from_json(text: str) -> Snapshot`, with a `"schema": "netview.gsm7248.snapshot/1"` key.
- Produces decoders in `mibs.py`. Each takes `Sequence[tuple[Oid, SnmpValue]]` (walk rows) and is pure. The module holds OID constants for each table, named after the MIB objects:
  - `SYS_DESCR`, `SYS_OBJECT_ID`, `SYS_UPTIME`, `SYS_NAME`, `DOT1D_BASE_BRIDGE_ADDRESS` (`1.3.6.1.2.1.17.1.1.0`);
  - `IF_TABLE`, `IF_X_TABLE`;
  - `DOT1D_BASE_PORT_IFINDEX`, `DOT1D_STP_PORT_STATE`;
  - `DOT1Q_TP_FDB_PORT`, `DOT1Q_TP_FDB_STATUS`, `DOT1Q_VLAN_STATIC_NAME`, `DOT1Q_VLAN_CURRENT_EGRESS`, `DOT1Q_VLAN_CURRENT_UNTAGGED`, `DOT1Q_PVID`;
  - `DOT1D_TP_FDB_PORT` (the fallback);
  - `DOT3_STATS_DUPLEX`;
  - `DOT3AD_AGG_PORT_ATTACHED`;
  - `ENT_PHYSICAL_TABLE`.

  The functions:
  - `decode_system(rows) -> SwitchInfo`. `rows` are the GET results for the system scalars plus `DOT1D_BASE_BRIDGE_ADDRESS`, a 6-byte MAC formatted as lower-case with colons.
  - `decode_ports(if_rows, ifx_rows, duplex_rows) -> list[Port]`. The name comes from `ifName`, falling back to `ifDescr`. kind is `ethernet` for ifType 6, `lag` for ifType 161, `other` otherwise.
  - `decode_counters(if_rows, ifx_rows, t_ms) -> list[PortCounters]`. It prefers the `ifHC*` 64-bit columns, sets `hc=False` when they are absent, and uses 32-bit `ifIn/OutOctets` in that case.
  - `decode_bridge_ports(rows) -> dict[int, int]`, mapping bridge port to ifIndex.
  - `decode_portlist(octets: bytes) -> frozenset[int]`, giving bridge port numbers with bit 1 as the MSB of the first byte.
  - `decode_fdb(port_rows, status_rows, bridge_ports, fdb_to_vlan: Mapping[int, int] | None = None) -> list[MacEntry]`. Indexes are `(fdbId, m1..m6)`. When `fdb_to_vlan` is None, the fdbId is the VLAN, which is the IVL behaviour of FASTPATH.
  - `decode_fdb_dot1d(port_rows, bridge_ports) -> list[MacEntry]`, with VLAN set to 1. It is the fallback when Q-BRIDGE returns nothing.
  - `decode_vlans(name_rows, egress_rows, untagged_rows, bridge_ports) -> list[Vlan]`. Current-table indexes are `(timeMark, vid)`; ignore the timeMark.
  - `decode_pvids(rows, bridge_ports) -> dict[int, int]`, mapping ifIndex to PVID.
  - `decode_stp(rows, bridge_ports) -> list[StpPort]`. Values 1–6 map to disabled, blocking, listening, learning, forwarding, broken.
  - `decode_lags(rows, ports: Sequence[Port]) -> list[LagGroup]`
  - `decode_entity(rows) -> Inventory`, built from the chassis row (entPhysicalClass 3).
  - `decode_health(rows) -> Health`. NETGEAR private OIDs for CPU and memory go in constants `NG_CPU_UTIL` and `NG_MEM_FREE`/`NG_MEM_TOTAL`, **taken from the NETGEAR-SWITCHING-MIB text for 6.3.x**: download it from NETGEAR's support page for the GSM7248 and cite the URL and object names in a comment. If the OIDs cannot be confirmed, leave them `None`; `decode_health` then returns all-None fields, and the task report says so. **Never guess an OID.**

- [ ] **Step 1: Write `walk_basic.txt`** in net-snmp `-On` format. It is a hand-built model of the switch on 2026-11-09 from `HomeLab/docs/hardware/gsm7248.md`:
  - sysObjectID `.1.3.6.1.4.1.4526.100.2.1`, sysName empty, sysDescr `GSM7248 L2 Managed Gigabit Switch`;
  - ifIndex 1–48 named `0/1`…`0/48` (ifType 6), plus LAG `1/1` with ifIndex 49 (ifType 161) and the management interface `3/1`;
  - oper up on 0/5, 0/7, 0/9, 0/11 and 0/13 at 1000 Mb/s full duplex;
  - bridge ports 1–48 mapping to ifIndex 1–48;
  - STP forwarding on 0/5 and 0/11 and blocking on 0/7, 0/9 and 0/13;
  - VLAN 1 "default" with every port untagged, PVID 1;
  - in the FDB, `b8:ca:3a:67:7d:ef` plus five `bc:24:11:…` MACs on 0/5 and the switch's own `00:1b:2f:c2:dc:75` as status self (4);
  - Counter64 octets for the up ports;
  - an ENTITY chassis row with serial `TEST-SERIAL-0001`, a placeholder rather than the real serial, and firmware `6.3.3.7`.

  The header comment says it is synthetic and must be replaced with a scrubbed real walk later.
- [ ] **Step 2: Write the failing tests** in `test_mibs.py`. Each loads the fixture through `parse_snmpwalk`:
  - `test_system_info`: `object_id == "1.3.6.1.4.1.4526.100.2.1"` and `mac == "00:1b:2f:c2:dc:75"`
  - `test_entity_inventory`: `decode_entity(...).firmware == "6.3.3.7"`
  - `test_ports_names_and_state`: 50 ports; `port_by_name("0/5").oper_up` is true; `port_by_name("0/1").oper_up` is false; `speed_mbps == 1000` and `duplex == "full"` on 0/5
  - `test_portlist_msb_first`: `decode_portlist(bytes([0b1000_0000, 0b0000_0001])) == frozenset({1, 16})`
  - `test_fdb_maps_to_ifindex_and_vlan`: six learned MACs on ifIndex 5, VLAN 1, and the switch MAC with status `"self"`
  - `test_fdb_dot1d_fallback`
  - `test_stp_states`: 0/7 is blocking and 0/5 is forwarding
  - `test_vlan_membership`: VLAN 1 untagged contains ifIndex 1–48
  - `test_counters_prefer_hc`, and `test_counters_32bit_when_no_hc`, which drops the ifHC rows
  - `test_health_absent_oids_returns_none_fields`
  - `test_decoders_ignore_unexpected_rows`: an extra unknown OID under a table doesn't raise
- [ ] **Step 3: Write `test_codec.py`:** `test_snapshot_round_trip` (equality after `snapshot_from_json(snapshot_to_json(s))`) and `test_codec_rejects_unknown_schema`.
- [ ] **Step 4: Run them.** Expected: FAIL.
- [ ] **Step 5: Implement** `model/` and `mibs.py`. Index parsing: the suffix after a table-column OID is the row index; for FDB the suffix is `(fdbId, 6 MAC octets)`.
- [ ] **Step 6: Run the tests and the full check list.** Expected: PASS.
- [ ] **Step 7: Commit.** `git commit -m "feat(gsm7248): switch model, snapshot codec and MIB decoders"`

---

### Task 4: Analysis rules

**Files:**
- Create: `src/netview/plugins/builtin/gsm7248/analysis.py`
- Test: `tests/unit/plugins/gsm7248/test_analysis.py`

**Interfaces:**
- Consumes the model types from Task 3.
- Produces:
  - `compute_rates(prev: PortCounters, cur: PortCounters, speed_mbps: int | None) -> PortRates | None`:
    - None when `cur.t_ms <= prev.t_ms`, or when any counter went backwards on an HC counter (a reset);
    - for 32-bit (`hc=False`), one wrap at 2**32 is assumed when the delta is negative. **However,** it returns None when the resulting rate is above `1.1 × speed_mbps × 1e6` bit/s, or, when the speed is unknown, when the wrapped delta is above `2**31` octets. That is a reset, not a wrap;
    - `util_percent = max(in_bps, out_bps) / (speed_mbps * 1e6) * 100`, or None when the speed is unknown or 0.
  - `rebooted(prev: SwitchInfo | None, cur: SwitchInfo) -> bool`, true when `cur.uptime_cs < prev.uptime_cs`.
  - `detect_uplinks(snapshot: Snapshot, gateway_mac: str | None, configured: frozenset[str], mac_threshold: int) -> frozenset[int]`, returning ifIndex values. A port is an uplink if:
    - its name is in `configured`, or
    - its count of learned MACs is greater than `mac_threshold`, or
    - the gateway's MAC is learned on it.
  - `Attachment(mac: str, if_index: int, port_name: str, vlan: int, via_uplink: bool, device_key: str | None)`, a frozen dataclass.
  - `attribute(snapshot: Snapshot, uplinks: frozenset[int], device_keys_by_mac: Mapping[str, str]) -> list[Attachment]`. It covers learned MACs only and skips `self` and `mgmt`.
  - `single_device_ports(attachments: Sequence[Attachment]) -> dict[int, str]`, mapping ifIndex to device_key. It covers non-uplink ports with **exactly one** learned MAC, and that MAC must belong to a known device.
  - `ChangeKind(StrEnum)`: `LINK_UP`, `LINK_DOWN`, `ADMIN_CHANGED`, `MAC_NEW`, `MAC_MOVED`, `MAC_GONE`, `STP_CHANGED`, `REBOOTED`, `LOW_MEMORY`, `UNREACHABLE`, `REACHABLE`.
  - `Change(kind: ChangeKind, text: str, if_index: int | None = None, mac: str | None = None)`, frozen.
  - `diff(prev: Snapshot | None, cur: Snapshot, *, known_macs: frozenset[str], seen_macs: frozenset[str], uplinks: frozenset[int], low_memory_kb: int) -> list[Change]`:
    - When `prev` is None, it returns `[]`.
    - **It compares a group only when that group is in both `prev.groups` and `cur.groups`.** A group's first appearance is a baseline, not news. This is what stops the first bridge poll, arriving after the first status poll, from announcing every MAC.
    - `MAC_NEW` is produced for a MAC that is not in `seen_macs` (never seen on this switch before, per `gsm7248_mac_locations`) and that is learned on a non-uplink port. It covers any MAC, known device or not, as spec §6.4 says. Using "never seen before", not "absent from the previous poll", keeps idle Proxmox guests whose entries age out and come back from repeating it.
    - `MAC_GONE` is produced only for MACs in `known_macs`.
    - `MAC_MOVED` is produced for any MAC whose port changed, except a move onto or off a port in `uplinks`.
    - `REBOOTED` is produced when both snapshots have `info` and `rebooted(prev.info, cur.info)`.
    - `UNREACHABLE` and `REACHABLE` are produced by the service, not by `diff`. The kinds and their texts live here so they stay in one place.
- Exact text, used verbatim by later tasks and tests:
  - `f"GSM7248 port {name} link up at {speed} Mb/s"`
  - `f"GSM7248 port {name} link down"`
  - `f"GSM7248 port {name} {'enabled' if up else 'disabled'}"`
  - `f"{mac} appeared on GSM7248 port {name} (VLAN {vid})"`
  - `f"{mac} moved from GSM7248 port {old} to {new}"`
  - `f"{mac} left GSM7248 port {name}"`
  - `f"GSM7248 port {name} spanning tree {old} → {new}"`
  - `"GSM7248 restarted"`
  - `f"GSM7248 memory low: {free} KB free"`
  - `"GSM7248 is not answering SNMP"`
  - `"GSM7248 is answering SNMP again"`
- Also produces `merge_snapshot(base: Snapshot | None, part: Snapshot) -> Snapshot`:
  - For each group in `part.groups`, exactly that group's `GROUP_FIELDS` are taken from `part`, **including empty ones**. Every other field is kept from `base`.
  - The result's `groups` is `base.groups | part.groups`, and its `t_ms` is `part.t_ms`.

- [ ] **Step 1: Write the failing tests:**
  - `test_rates_basic`: 15 s apart, with in going up by 18,750,000 octets, gives `in_bps == 10_000_000`
  - `test_util_percent`: 10 Mb/s on a 1000 Mb/s port gives `util_percent == 1.0`
  - `test_counter_reset_returns_none`: an HC counter that went down gives None
  - `test_32bit_wrap`: prev `2**32 - 1000`, cur `500`, gives a delta of 1500 octets
  - `test_32bit_reset_is_not_a_spike`: on a 1000 Mb/s port, prev `3_000_000_000` and cur `10` over 15 s gives None
  - `test_same_timestamp_returns_none`
  - `test_reboot_detected_from_uptime`
  - `test_uplink_by_threshold`: 9 MACs with threshold 8 marks the port as an uplink
  - `test_uplink_by_gateway_mac`
  - `test_uplink_configured`
  - `test_attribute_marks_via_uplink`
  - `test_multi_mac_port_not_single_device`: 0/5 with six MACs isn't in `single_device_ports`
  - `test_single_device_port`: 0/3 with one known MAC maps to that device key
  - `test_first_snapshot_no_changes`
  - `test_link_down_and_up_text`, using the exact strings above
  - `test_mac_gone_only_for_known_devices`
  - `test_mac_new_only_when_never_seen`: a MAC that is in `seen_macs` but absent from `prev` gives no `MAC_NEW`
  - `test_mac_new_not_on_uplink`
  - `test_mac_moved`
  - `test_mac_move_via_uplink_ignored`
  - `test_stp_change`
  - `test_low_memory_once`: below the threshold in prev and cur gives no second event; crossing from above to below gives one
  - `test_first_bridge_poll_after_status_emits_nothing`: prev has `groups={"status"}` and cur, the merge, has `{"status","bridge"}` with six known MACs; the diff gives `[]`
  - `test_status_poll_keeps_pvid_and_firmware`: merging a status-only part into a base with topology keeps `pvids` and `inventory`
  - `test_mac_table_can_become_empty`: merging a bridge part with `macs=()` empties the MACs, and the diff reports `MAC_GONE` for the known MACs
  - `test_merge_snapshot_keeps_base_fields`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `analysis.py`.** Every function is pure.
- [ ] **Step 4: Run the tests and the full check list.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(gsm7248): rates, uplink detection, device attribution and change detection"`

---

### Task 5: Plugin storage and migrations

**Files:**
- Create: `src/netview/plugins/builtin/gsm7248/storage.py` and `migrations/versions/0001_initial.py` only, with `revision = "gsm7248_0001"` and `down_revision = None`. The core's shared Alembic env (`infrastructure/db/migrate.py:14-30`) runs it, the way `tests/integration/plugins/sample_plugins/good_versions/0001_good.py` is run.
- Modify: `pyproject.toml` (package data, so the plugin's `migrations/**` ships in the wheel, next to the existing static rules)
- Test: `tests/integration/plugins/gsm7248/test_storage.py`

**Interfaces:**
- Consumes `PluginUnitOfWork` (`ctx.unit_of_work()`), `StorageSpec`, and the model and codec from Task 3.
- Produces:
  - `metadata: sa.MetaData` with these tables:
    - `gsm7248_port_samples`:
      - PK (`switch_id` str, `if_index` int, `resolution` str with values "raw" or "5m", `t_ms` int);
      - columns `in_octets`, `out_octets` (BigInteger), and `in_bps`, `out_bps`, `in_err_ps`, `out_err_ps`, `in_disc_ps`, `out_disc_ps`, `util_percent` (Float, nullable).
    - `gsm7248_mac_locations`:
      - PK (`switch_id`, `mac`, `vlan`, `if_index`);
      - columns `first_ms`, `last_ms`;
      - an index on `(switch_id, mac)`.
    - `gsm7248_snapshots`: PK `switch_id`, plus `t_ms` and `body` (Text, codec JSON).
  - `storage_spec() -> StorageSpec`, returning `StorageSpec(metadata, Path(__file__).parent / "migrations" / "versions")`.
  - `class SwitchStore` with constructor `SwitchStore(uow_factory: Callable[[], PluginUnitOfWork], switch_id: str)` and these methods:
    - `add_samples(rates: Sequence[PortRates], counters: Mapping[int, PortCounters]) -> None`
    - `samples(if_index: int, from_ms: int, to_ms: int, resolution: Literal["raw","5m"]) -> list[PortRates]`
    - `rollup_and_prune(now_ms: int, raw_keep_ms: int, rollup_keep_ms: int) -> int`. It averages raw rows older than one bucket into 5-minute rows (the bucket start is `t_ms // 300_000 * 300_000`), deletes raw rows older than `raw_keep_ms` and rollups older than `rollup_keep_ms`, and returns the number of rows deleted. It is idempotent.
    - `touch_macs(attachments: Sequence[Attachment], t_ms: int) -> None`, which inserts or updates `last_ms`.
    - `seen_macs() -> frozenset[str]`, every MAC ever recorded for this switch. It feeds `diff(seen_macs=...)`.
    - `mac_history(*, mac: str | None = None, if_index: int | None = None, limit: int = 200) -> list[dict[str, Any]]`
    - `save_snapshot(s: Snapshot) -> None` and `load_snapshot() -> Snapshot | None`
  - `switch_id` is the constant `"gsm7248"` in phase 1 (see Global Constraints). The column exists so that support for more than one switch can be added later.

- [ ] **Step 1: Write the failing tests** against a temp SQLite DB. The plugin class doesn't exist until Task 6, so don't load it through `PluginHost`:
  - Migrate with `upgrade_plugin(engine, "gsm7248", storage_spec().versions_dir)`.
  - Get the unit of work from `DefaultPluginContext("gsm7248", None, engine, ...)` the way `tests/integration/plugins/conftest.py:53` builds one, so the per-plugin authorizer is live.

  The tests:
  - `test_migration_creates_prefixed_tables`
  - `test_snapshot_round_trip`
  - `test_samples_query_range`
  - `test_rollup_averages_and_prunes`: 20 raw rows over 10 minutes give 2 rollup rows with the right means; raw rows past the retention are gone; running it twice changes nothing
  - `test_touch_macs_updates_last_seen`
  - `test_mac_history_by_port`
  - `test_cannot_write_core_tables`: an INSERT into `devices` through the plugin's session is refused by the authorizer. This is a regression guard.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `storage.py` and the migration.** Use SQLAlchemy Core statements on `uow.session`, and commit through `uow.commit()`.
- [ ] **Step 4: Run the tests and the full check list.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(gsm7248): storage for port samples, MAC locations and snapshots"`

---

### Task 6: Settings, collector, service, jobs, plugin wiring and API

**Files:**
- Create: `src/netview/plugins/builtin/gsm7248/{settings,collector,service,routes,plugin}.py`
- Modify: `pyproject.toml` (entry point `gsm7248 = "netview.plugins.builtin.gsm7248.plugin:Gsm7248Plugin"`)
- Test: `tests/integration/plugins/gsm7248/test_service.py`, `tests/integration/plugins/gsm7248/test_api.py`, `tests/integration/plugins/gsm7248/test_plugin_load.py`. The plugin also has to pass `netview.sdk.testing.contract.check_plugin(Gsm7248Plugin)`.

**Interfaces:**
- `Gsm7248Settings(BaseModel)` has these fields, with exact defaults:

  | Field | Default |
  |---|---|
  | `host: str` | `"192.168.1.4"` |
  | `snmp_version: Literal["2c","3"]` | `"3"` |
  | `community: SecretStr \| None` | `None` |
  | `v3_user: str` | `""` |
  | `v3_auth_protocol: Literal["none","md5","sha"]` | `"sha"` |
  | `v3_auth_key: SecretStr \| None` | `None` |
  | `v3_priv_protocol: Literal["none","des","aes128"]` | `"des"` |
  | `v3_priv_key: SecretStr \| None` | `None` |
  | `timeout_s: float` | `Field(2.0, ge=0.5, le=10)` |
  | `retries: int` | `Field(1, ge=0, le=3)` |
  | `counters_interval_s: int` | `Field(15, ge=5, le=300)` |
  | `status_interval_s: int` | `Field(30, ge=10, le=600)` |
  | `bridge_interval_s: int` | `Field(60, ge=15, le=900)` |
  | `topology_interval_s: int` | `Field(300, ge=60, le=3600)` |
  | `uplink_ports: list[str]` | `[]` |
  | `uplink_mac_threshold: int` | `Field(8, ge=2, le=1000)` |
  | `raw_retention_h: int` | `Field(24, ge=1, le=168)` |
  | `rollup_retention_d: int` | `Field(30, ge=1, le=365)` |
  | `low_memory_kb: int` | `Field(1024, ge=0)` |

  Every field has a `description=`, which the settings form shows. The model also has `def target(self) -> SnmpTarget | None`, which returns None when the credentials for the chosen version are incomplete.
- `Collector(snmp: SnmpClient)` has one method per poll group. Each takes a `SnmpTarget` and `t_ms`, and returns a partial `Snapshot` (plus the counters for `counters`):
  - `counters(target, t_ms, if_indexes: Collection[int]) -> list[PortCounters]`. It walks only the ifX columns it needs and filters to linked ports.
  - `status(target, t_ms) -> Snapshot`, with `groups={"status"}`. It covers ports, system plus bridge address, and health.
  - `bridge(target, t_ms) -> Snapshot`, with `groups={"bridge"}`. It covers MACs. Q-BRIDGE comes first, and `dot1d` is the fallback when it is empty.
  - `topology(target, t_ms) -> Snapshot`, with `groups={"topology"}`. It covers VLANs, PVIDs, STP, LAGs and inventory.
  - The bridge-port-to-ifIndex map is walked in `bridge` and `topology` and cached on the collector between polls.
- `Gsm7248Service(ctx: PluginContext, store_factory: Callable[[str], SwitchStore], collector: Collector)` has these job methods, each catching `SnmpError`:
  - `poll_counters()`, `poll_status()`, `poll_bridge()`, `poll_topology()`;
  - `prune()`, run hourly;
  - `poll_all() -> bool`, which returns False if a poll is already running; the route turns that into a 409;
  - `test_connection(target: SnmpTarget) -> dict[str, str]`, which returns `{"ok": "true", "sys_descr": ...}` or `{"ok": "false", "error": <type name>: <message>}`.

  Read models for the routes:
  - `summary() -> dict[str, Any]`
  - `ports() -> list[dict[str, Any]]`
  - `port(name: str) -> dict[str, Any] | None`
  - `samples(name, from_ms, to_ms, step) -> list[dict]`
  - `macs() -> list[dict]`
  - `vlans() -> list[dict]`

  Behaviour:
  - **Concurrency:** the scheduler runs sync jobs on a 32-thread pool (`infrastructure/scheduler.py:61`), so the four poll jobs can overlap.
    - The service holds one `threading.Lock` around **each whole poll**: SNMP, merge, diff, save and claims. The job methods take it with a blocking acquire.
    - `poll_all()` takes it with `acquire(blocking=False)` and returns False when it is held. The route turns that into a 409.
  - It holds the merged current `Snapshot` (seeded from `store.load_snapshot()` at setup), the last counters per ifIndex, the last rates, and a reachability flag.
  - **Uplink inputs:**
    - `gw_ip = ctx.net.default_gateway(ctx.net.local_ip())`;
    - `gateway_mac` is the `mac` of the `ctx.core.devices()` entry whose `ip == gw_ip`, or None;
    - `configured` is `frozenset(settings.uplink_ports)`.
  - After each status, bridge or topology poll it does the following, in order:
    1. `merged = merge_snapshot(current, part)`.
    2. `uplinks = detect_uplinks(merged, ...)`.
    3. `changes = diff(current, merged, known_macs=..., seen_macs=store.seen_macs(), uplinks=uplinks, low_memory_kb=...)`. Each change becomes `ctx.core.add_event(EventKind.PLUGIN, change.text, ip)`, where `ip` is the device's IP when `change.mac` belongs to a NetView device.
    4. Save `merged` and make it `current`.
    5. On a `bridge` or `topology` poll, run `attribute(merged, uplinks, {d.mac: d.key for d in ctx.core.devices() if d.mac})`, then `store.touch_macs`. For each attached known device, claim `Hint(key, f"on GSM7248 port {port} (VLAN {vid})", SOURCE)`, or `Hint(key, f"via GSM7248 uplink {port}", SOURCE)` when it is behind an uplink.
    6. On a `status` poll with `info` set, find the NetView device whose MAC is `info.mac`, or whose IP equals `settings.host`, and claim:
       - `NameClaim(key, info.sys_name or "GSM7248", SOURCE, 8, now)`
       - `TypeClaim(key, "switch", "SNMP sysObjectID 1.3.6.1.4.1.4526", SOURCE)`
       - `Hint(key, f"NETGEAR {inventory.model or 'GSM7248'} firmware {inventory.firmware or '?'}", SOURCE)`, once `inventory` is known.

       Claims go out only when the value changed since the last claim, to avoid write churn.
  - **Known gap, recorded in `deferred.md` by Task 8:** core hints are replaced per `(key, source)` only when a new hint arrives (`application/usecases/identity.py:37-39`). A device that leaves the switch keeps its last "on GSM7248 port …" hint until the core can clear a source's hints.
  - **Rates:** on a counters poll, compute rates against the previous counters for each port. The rates for the whole poll are dropped when the last status poll detected a reboot. The rates and counters are stored with `store.add_samples`.
  - **Unknown MACs:** in `macs()`, the vendor of a MAC with no NetView device comes from `ctx.vendors.vendor(mac)`.
  - **Unreachable:** on `SnmpTimeout` or `SnmpAuthError` it marks the switch unreachable and emits the `UNREACHABLE` text **once**. It backs off each group's next run by doubling up to 300 s: the job returns at once while `now < next_allowed`. On the next success it emits `REACHABLE` and resets the backoff.
  - Error text that reaches logs, events or the API is `type(exc).__name__` plus the message. The message comes from the adapter, so it is secret-free (Task 2).
  - **Live settings:** `on_settings_changed` rebuilds the target. The host restarts the jobs.
- `Gsm7248Plugin(Plugin)`:
  - `manifest`: id `gsm7248`, name `"NETGEAR GSM7248"`, version `0.1.0`, description `"Ports, VLANs, spanning tree, traffic and device-to-port mapping for the GSM7248 switch over SNMP"`, `sdk_version=">=1.1,<2"`, capabilities `{API, WEB_UI, STORAGE, JOBS}`, permissions `{DEVICES_READ, NAMES_WRITE, TYPES_WRITE, STORAGE_OWN, API, UI, NETWORK_PROBE}`. Use the exact `Permission` member names in `manifest.py`.
  - `jobs()` returns `counters`, `status`, `bridge` and `topology` at the settings intervals, plus `prune` every 3600 s.
    - `initial_delay_s` is 2, 5, 8 and 11 s, so the first polls don't land on the switch at once.
    - Timeouts are 2× the interval, capped at 120 s.
    - When `settings.target()` is None, `jobs()` returns only `prune`, and the summary says `"not configured"`.
- Routes (`build_router(service) -> APIRouter`):
  - `GET /summary`;
  - `GET /ports`;
  - `GET /ports/{name}`, where the name is URL-encoded (`0%2F5`) and a miss is a 404;
  - `GET /ports/{name}/samples?from_ms&to_ms&resolution=raw|5m`;
  - `GET /macs`;
  - `GET /vlans`;
  - `POST /poll` starts `poll_all` on a background thread and returns 202, or 409 with `{"detail": "poll already running"}`. Check the lock first with a `try_start` helper, so the 409 is decided before returning;
  - all routes are plain `def`, not `async def`, because the SNMP client blocks;
  - `POST /test` takes body `{}`. It uses the stored settings (the client never sends secrets back) and returns `test_connection`.

  The `/summary` JSON:

  ```
  {configured, reachable, last_poll_ms, last_error,
   switch: {name, model, firmware, serial, mac, uptime_s},
   health: {cpu_percent, mem_free_kb, mem_total_kb},
   ports: {total, up, uplinks},
   throughput_bps: {in, out}}
  ```

  Each entry from `/ports`:

  ```
  {if_index, name, alias, kind, admin_up, oper_up, speed_mbps, duplex, pvid (from Snapshot.pvid),
   vlans: {untagged: [vid], tagged: [vid]},
   stp_state, lag, uplink, rates: PortRates | null,
   devices: [{mac, vlan, device_key, display_name, ip, vendor}]}
  ```

- [ ] **Step 1: Write the failing service tests.** Setup:
  - `FakeSnmpClient.from_walk_file(walk_basic.txt)`;
  - `FakePluginContext` and `FakeCore` from Task 2, with devices for `b8:ca:3a:67:7d:ef` (Proxmox) and the switch MAC at `192.168.1.4`;
  - a real `SwitchStore` on a temp SQLite DB, migrated the way Task 5's tests do it. These are integration-style tests: put them in `tests/integration/plugins/gsm7248/test_service.py` rather than under `unit/`.

  The tests:
  - `test_status_poll_claims_switch_name_type_hint`: name `"GSM7248"` with rank 8, and a `TypeClaim` with type `"switch"` and source `"GSM7248"`
  - `test_concurrent_polls_are_serialised`: `poll_status` and `poll_bridge` started on two threads at once both finish, and the saved snapshot has both groups
  - `test_poll_all_returns_false_while_running`
  - `test_bridge_poll_hints_device_port`: `"on GSM7248 port 0/5 (VLAN 1)"` for the Proxmox device
  - `test_counters_then_rates`: two polls 15 s apart with modified counter rows give non-None rates for 0/5
  - `test_unreachable_emits_one_event_and_backs_off`: with `fail_with=SnmpTimeout(...)`, three polls give exactly one `"GSM7248 is not answering SNMP"` event, and the third poll makes no SNMP call (the backoff); clearing the failure and moving the clock past the backoff gives one `"…again"` event
  - `test_auth_error_message_has_no_secret`: with settings community `"s3cr3t"` and `SnmpAuthError`, `"s3cr3t"` appears in no event, no `summary()["last_error"]` and no captured log record
  - `test_restart_does_not_repeat_events`: poll everything, build a new service on the same store, poll again with the same data, and get zero new events
  - `test_not_configured_has_only_prune_job`
  - `test_claims_not_resent_when_unchanged`
- [ ] **Step 2: Write the failing API and plugin-load tests:**
  - `test_plugin_loads_and_migrates`: the plugin's state is `"active"` through `GET /api/v1/plugins`
  - `test_summary_not_configured`
  - `test_ports_endpoint_shape`: inject the fake SNMP client in the test's context factory
  - `test_port_by_encoded_name`
  - `test_unknown_port_404`
  - `test_poll_conflict_409`
  - `test_poll_requires_x_netview_header`, which returns 403 like the other unsafe routes
  - `test_test_route_never_returns_secret`
  - `test_settings_api_masks_community`
- [ ] **Step 3: Run them.** Expected: FAIL.
- [ ] **Step 4: Implement** settings, collector, service, routes and plugin, and register the entry point.
- [ ] **Step 5: Run the tests and the full check list.** Expected: PASS.
- [ ] **Step 6: Commit.** `git commit -m "feat(gsm7248): SNMP polling jobs, events, identity claims and API"`

---

### Task 7: Web UI: tile, Switch page, port grid, Devices column, test button

**Files:**
- Create: `src/netview/plugins/builtin/gsm7248/static/{ui.js,page.js,port-grid.js,gsm7248.css}`
- Modify: `plugin.py`, where `ui()` returns `UiContribution(static_dir=..., module="ui.js")`
- Test: `tests/js/gsm7248-ui.test.mjs`

**Interfaces:**
- Consumes the slot API in `presentation/web/static/js/slots.js:44-52`: `ui.slot`, `ui.apiGet`, `ui.apiSend(method, path, body)`, `ui.apiBase`, `ui.util` and `ui.requestRender`. Use `apiSend` for unsafe calls, because it sends the `X-Netview` header; there is no `apiPost`. The slot spec shapes on `main` are:
  - `page`: `{id, title, mount(el, ctx) -> {update(state), destroy()}}`, from `main.js:45-64`. The route is `/p/gsm7248/<id>`.
  - `settings.section`: `{title, render(body, {pluginId, apiBase, apiGet, apiSend, util})}`, from `settings/plugins-tab.js:158-170`. It exists on `main`.
  - `devices.column`: `{id, label, sub?, sortKey, groupKey?, text(d) | render(d)}`, as `pages/devices.js` `pluginColumn` shows.
- Produces these pure, exported, testable functions in `port-grid.js`. The module is self-contained, with no imports from core files, so `node --test` can import it on its own:
  - `faceplateLayout(ports) -> {top: Port[], bottom: Port[], extra: Port[]}`. Ethernet `0/1`–`0/48` go odd-top and even-bottom in port order; `extra` holds the combo, LAG and other kinds.
  - `portCellHtml(port, esc) -> string`. Its classes are `port up|down|disabled|blocking` plus `uplink`. Its visible text has the port number, the speed short form (`1G`, `100M`, `10M`, `—`) and a symbol: `▲` up, `▼` down, `⦸` admin-disabled, `⏸` STP blocking. Its `title` says the full state in words. It includes a utilisation bar `<span class="util" style="--u:NN%">`.
  - `portSortKey(name) -> number`, giving `slot * 1000 + port` (`"0/2"` → 2, `"1/1"` → 1001). The result must be a number, because `table-model.js` falls back to string comparison when types are mixed. An empty name gives `Infinity`.
  - Rates are shown with the core's `ui.util.fmtRate` (`"12.3 Mbit/s"`), not a formatter of the plugin's own, so units match the rest of netview.
- UI pieces:
  - **Dashboard tile** (`dashboard.tile`): key "Switch". The value is `"{up}<small>of 48 ports up</small>"`, and the sub-line is `"↓ {in}  ↑ {out}, CPU {n}%"`. Spec §13.3 rules out middle dots. When unreachable, the value is "Unreachable" with the `bad` state class plus an icon and the word. When not configured, it says "Set up in Settings".
  - **Page** (`page` slot, nav label "Switch"):
    - a header with name, model, firmware, uptime and a **Poll now** button;
    - the faceplate grid inside a `.faceplate-scroll` container (`overflow-x: auto`);
    - the port detail panel, opened by click or by Enter/Space on a focused port cell. Cells are `<button>`s. It shows the port fields, the attached devices with their display names, and the MAC history from `/ports/{name}`.
    - sections for VLANs, the MAC table (with a text filter; unknown MACs get an "unknown" badge and the OUI vendor), spanning tree, LAGs and inventory.
    - The page refetches `/summary` and `/ports` on each SSE state render, at most once per 10 s, and on a 15 s timer while the page is visible (`document.visibilityState`).
  - **Devices column** (`devices.column`): id `port`, label "Switch port". `text(d)` gives the port name, `"via 0/11"` for an uplink, or `""`. `sortKey` is `portSortKey`, and `groupKey` is the port name. The column reads from a MAC-to-attachment map, refreshed from `/macs` with the same throttling.
  - **Settings section** (`settings.section`, titled "Connection"): a **Test connection** button that calls `apiSend("POST", apiBase + "/test", {})` and shows `sys_descr` or the error inline. It never reads or sends secret fields.
- CSS in `gsm7248.css` uses theme tokens only: `--ok`, `--bad`, `--warn`, `--idle`, `--surface*`, `--border*` and `--text*`. Cells are at least 32 px so they work as touch targets.

- [ ] **Step 1: Write the failing JS tests:**
  - `faceplate odd top even bottom`: `top[0].name === "0/1"`, `bottom[0].name === "0/2"`, and `top.length === 24`
  - `faceplate extras`: the LAG `1/1` lands in `extra`
  - `cell shows state without colour`: a down port's HTML contains `▼` and a title holding `link down`; a blocking port contains `⏸`
  - `cell escapes alias`: an alias of `<img onerror=x>` is escaped
  - `portSortKey numeric`: `portSortKey("0/2") < portSortKey("0/10")`, `portSortKey("0/48") < portSortKey("1/1")`, and `typeof portSortKey("0/5") === "number"`
- [ ] **Step 2: Run** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement** the static files.
- [ ] **Step 4: Run** `npm test` and the full check list. Expected: PASS.
- [ ] **Step 5: Browser check.** The controller does this directly, not a subagent, per the user's NetView memory rule.
  1. Run the `netview` launch configuration, with port 8766 and the data dir `HomeLab/network/netview-dev`, from **this worktree**. Add a temporary launch entry `netview-gsm7248` that points `uv --directory` at the worktree, on port 8767, with data dir `C:/…/scratchpad/netview-gsm7248-dev`. Don't use the shared netview-dev DB.
  2. With no SNMP access configured, check that the tile says "Set up in Settings", the Switch page renders without errors, and the Settings tab shows masked password inputs.
  3. Check at 1280 px and at 375 px that the faceplate scrolls inside its container and the page does not.
  4. Check two themes.
- [ ] **Step 6: Commit.** `git commit -m "feat(gsm7248): dashboard tile, Switch page with faceplate, Devices column"`

---

### Task 8: Switch setup runbook and live check

**Files:**
- Create: `docs/gsm7248-setup.md`
- Modify: `docs/superpowers/deferred.md`. Add:
  - secrets in the OS keyring;
  - replacing `walk_basic.txt` with a scrubbed real walk;
  - confirming the NETGEAR CPU and memory OIDs if Task 3 left them None;
  - the core can't clear a source's stale hints (see Task 6);
  - STP port **role** (Designated or Backup), which needs the NETGEAR MSTP private MIB.

**Steps:**

- [ ] **Step 1: Write the runbook.** These are console commands for 6.3.3.7, typed by the user at the `#` prompt over `screen /dev/ttyS0 38400` from Proxmox, as `HomeLab/docs/hardware/gsm7248.md` describes. Check every command against NETGEAR's *GSM7248 CLI Command Reference* for software 6.x and cite the document. It covers:
  1. `show snmpcommunity`, to see the defaults;
  2. removing or disabling the `private` read-write community;
  3. **SNMPv3 (recommended):** create a read-only user `netview` with SHA authentication and DES privacy, whatever 6.3.3.7 supports;
  4. **v2c alternative:** a read-only community restricted to the laptop's IP. Note that the laptop's IP is DHCP today, so this needs a reservation, or v3;
  5. `copy system:running-config nvram:startup-config`;
  6. checking from the laptop: NetView Settings, then Switch, then Test connection.

  Keep commands short: the iDRAC HTML5 console drops `\` and `;`. Never put a real password or community in the document; use `<your-auth-passphrase>`. Say plainly that SNMP secrets go only into NetView's Settings dialog, **never** into a `[plugins.gsm7248]` section of `netview.toml`, which is a plain-text seed file.
- [ ] **Step 2: Hand-off note for the controller.** The live check needs the user to run the runbook on the switch and enter the credentials in NetView Settings **themselves**. Claude never types a password into a form. Then:
  1. Run the worktree preview from Task 7.
  2. Check that the tile shows 5 ports up, 0/5 lists the Proxmox MAC, 0/7, 0/9 and 0/13 show blocking, and per-port rates move.
  3. Record what differs from `walk_basic.txt` and fix the decoders if real rows differ. A decoder fix comes with a test using the real row shape.
- [ ] **Step 3: Commit.** `git commit -m "docs(gsm7248): switch-side SNMP setup runbook and deferred items"`

---

### Task 9: Port traffic chart and device report section

*Rewritten on 2026-11-11 against plan 2's merged code (the merge is `babab6d`). The earlier outline is replaced.*

**Decision: no `Capability.TRAFFIC`.**
- `TrafficLedger` in `application/usecases/traffic.py` keeps one entry per IP. It computes each rate from the previous counters, whatever source sent them.
- The metrics series `traffic.down.<ip>` and `traffic.up.<ip>` are shared by every source.
- The Starlink UI finds its rows with `state.traffic` filtered on `source === "starlink"`.
- So if the switch and the Starlink router both reported a wired device, its rates would be diffed across two counters, and Starlink's entry would vanish from its own UI.
- Per-device traffic therefore comes from this plugin's own per-port samples. A multi-source ledger goes in `deferred.md`.

**Files:**
- Create: `src/netview/plugins/builtin/gsm7248/static/report.js` (pure model plus the DOM drawing) and `tests/js/gsm7248-report.test.mjs`.
- Modify: `static/port-grid.js`, `static/page.js`, `static/ui.js`, `tests/js/gsm7248-ui.test.mjs` and `docs/superpowers/deferred.md`.
- No Python changes are expected. The routes `/ports/{name}` and `/ports/{name}/samples` already return what is needed.

**Interfaces:**
- Consumes:
  - `ui.util.lineChart(el, {label, series, fmt, height})`, where `series` is `[{name, color, points: [[t_ms, value|null]]}]`, plus `ui.util.fmtRate`, `ui.util.fmtAgo` and `ui.util.esc`;
  - `ui.slot("report.live-section", {id, draw(el, {ip, device, state})})`. It is redrawn on **every** state update, so it must not fetch on every draw;
  - `ui.requestRender()`;
  - `store.attachment(mac)`, which returns `{port, via}` or null (ui.js);
  - `GET {apiBase}/ports/{name}` (a port entry with `devices`, `speed_mbps`, `duplex`, `oper_up`, `vlans`, `rates`, `mac_history`) and `GET {apiBase}/ports/{name}/samples`. The samples response is a list of `{if_index, t_ms, in_bps, out_bps, ...}` for the last hour.
- Produces, in `port-grid.js` (pure):
  - `portChartSeries(samples) -> [{name: "In", color: "--series-1", points}, {name: "Out", color: "--series-2", points}]`, in that fixed order. The points are `[t_ms, in_bps]` and `[t_ms, out_bps]`.
- Produces, in `report.js` (pure):
  - `reportModel(attachment, detail, samples) -> null | {heading, tiles: [{k, v}], note, series | null, chartTitle}`.
  - `null` when `attachment` is null.
  - Via an uplink: heading `"Switch port"`, no tiles, `series: null`, and the note `"Seen by the GSM7248 through uplink port <port>; the device is on another switch or access point."`.
  - Direct: the tiles are Port, VLAN, Link (`"1G full"` style via `speedShort`, or `"link down"`), Download now (the port's `out_bps`, since the switch sends it to the device) and Upload now (`in_bps`). A First seen here tile comes from `mac_history` for the device's MAC.
  - A port with exactly one device gets `series` = Download (`--series-1`, points from `out_bps`) then Upload (`--series-2`, from `in_bps`), and the chart title `"<ip>'s traffic on switch port <port>, last hour"`.
  - A port with more than one device gets `series: null` and the note `"Port <port> is shared by <n> devices, so its traffic is not this device's alone."`.
  - `detail` or `samples` may still be `null` (loading). The model then shows the port tile, and the other tiles show `"–"`.
- Produces, in `report.js` (DOM):
  - `drawReport(el, model, lineChart, fmtRate)`. All text goes in through `textContent`, as the Starlink plugin's `drawLive` does. A `null` model empties `el`.

- [ ] **Step 1: Write the failing JS tests**
  - `portChartSeries keeps In then Out`.
  - `reportModel: null without an attachment`.
  - `reportModel: uplink gives only the note`.
  - `reportModel: single-device port charts Download from out_bps then Upload from in_bps`.
  - `reportModel: shared port has no series and says shared by 3 devices`.
  - `reportModel: loading detail shows dashes`.
  - `drawReport escapes a hostile port name`: the model text contains `<img src=x onerror=1>` and the element ends with no `img`. Use the DOM shim the existing JS tests use; if there is none, test the model and not the DOM.
- [ ] **Step 2: Run `npm test`.** The new tests fail.
- [ ] **Step 3: Implement `portChartSeries`, `reportModel` and `drawReport`.**
- [ ] **Step 4: Port panel chart (`page.js`).**
  - Below the port detail fields, add a chart box drawn with `ui.util.lineChart` from `portChartSeries(samples)`, with `fmt = fmtRate` and the label `"Port <name> traffic, last hour"`.
  - Fetch the samples when a port is selected, and again with the existing detail refresh, at most once every 15 s per port.
  - A stale answer for a previously selected port is dropped, using the existing `detailSeq` pattern.
- [ ] **Step 5: Report section (`ui.js`).**
  - Register `ui.slot("report.live-section", {id: "gsm7248-port", draw})`.
  - `draw` finds the attachment with `store.attachment(device && device.mac)` and reads a per-port cache `{detail, samples, at, loading}`.
  - When the cache entry is missing or older than 15 s and nothing is in flight, `draw` starts one fetch of both URLs for that port. When they finish it updates the cache and calls `ui.requestRender()`.
  - `draw` itself never awaits and never fetches more than once per port per 15 s, however often it is called.
  - Draw with `drawReport(el, reportModel(...), ui.util.lineChart, ui.util.fmtRate)`.
  - Test: `report draw fetches once per port per 15 s`. Call `draw` 50 times with a fake `apiGet` and a fake clock; expect 2 requests, the port and its samples.
- [ ] **Step 6: Events.**
  - Check that `EventKind.PLUGIN` events from the plugin show in the core Events card, which already has the label `plugin: "Plugin"`. No code change is expected.
  - If they do not show, report it under concerns; do not change the core.
- [ ] **Step 7: `deferred.md`.** Add: "Core traffic ledger keyed by (ip, source) with per-source metric series, so the switch can also feed `Capability.TRAFFIC` without clobbering Starlink's per-device entries."
- [ ] **Step 8: Run the full check list and commit** `feat(gsm7248): port traffic chart and device report section`.

**Review focus for this task:**
- A fetch storm from `report.live-section` redraws: SSE state updates arrive every few seconds.
- Escaping of port names, VLAN names and device names.
- A device whose MAC moves to another port while the report is open.
- Download and upload not swapped: port out means device download.
- A report for a device the switch has never seen draws nothing and makes no requests.

---

## Execution notes for the controller

- Tasks run strictly in order, 1 to 8, then 9 once its gate is met. Each depends on the interfaces of the one before it.
- After each task, a mechanical checker runs the full check list and diffs the files against the task's **Files** list. Before the next task starts, an independent reviewer reads only that task's diff, the task text and the spec section it implements.
- Task 2's adapter tests are the riskiest, because of the pysnmp responder on Windows. Accept the `@pytest.mark.snmp` skip only with the reason written in the task report. The live check in Task 8 then becomes their real coverage.
- Never run `uv` commands against the `netview` checkout. Windows locks the `.venv` exe while the plan-2 session and its preview server use it. Everything runs from the worktree, which has its own `.venv`.
- Never type credentials into NetView or the switch. The user does that.
