# Deferred items

The plan 1 and 1b items were all handled in plan 2.

## From the GSM7248 plugin, phase 1 (2026-11-10)

- Keep the plugin's SNMP secrets in the OS keyring instead of the settings store.
- Mask secrets nested in sub-models, lists or dicts, and SecretBytes. The host masks only top-level `SecretStr` fields and refuses to load a plugin whose settings schema has a secret anywhere else (`settings_codec.unsupported_secrets`).
- Replace `walk_basic.txt` with a scrubbed walk captured from the real switch.
- Confirm the NETGEAR CPU and memory OIDs if Task 3 left them as `None`.
- The core cannot clear a source's stale hints, so hints from a removed or renamed device linger (see Task 6).
- STP port **role** (Designated or Backup) needs the NETGEAR MSTP private MIB, so phase 1 does not show it.
- Check the switch setup commands in `docs/gsm7248-setup.md` against NETGEAR's *GSM7248 CLI Command Reference* and remove the "(check against the CLI reference)" marks.
- Core traffic ledger keyed by (ip, source) with per-source metric series, so the switch can also feed `Capability.TRAFFIC` without clobbering Starlink's per-device entries.

## From the plugin gallery (2026-11-11)

- "Update available" on an Installed card when the catalog has a newer version.
- Plugin icons from `plugin.json` (cards show a monogram tile today).
- A restart button (netview runs under `uv run netview serve`).
- Pin the catalog `ref` to a release tag once the repo has releases (it has none yet).
- After the branch is merged and pushed: one real install from `github.com/Cadtastic/NetView` `main` into a throwaway data dir.
- The repo has no LICENSE file, so `plugin.json` files carry no `license`. Add both once a license is chosen.

## From auth stage 1 (2026-11-12)

Later stages of `specs/2026-11-12-netview-auth-admin-design.md`, each to get its own plan:

- **Stage 2:** HTTPS (NetView-made or company certificate, Admin → HTTPS certificate), the wider Host allowlist, the public address in Admin → General, and `trusted_proxies`. Until `trusted_proxies` exists, everyone behind one shared proxy or NAT address shares that address's lockout count.
- **Stage 3:** sign-in with Microsoft, Google, GitHub and generic OpenID Connect, with per-provider allow-lists.
- **Stage 4:** the audit-log plugin (the `AuditSink` port and `ctx.audit` already exist and do nothing yet), the core's audit calls, GSM7248 declaring `console` with the server-local rule, and a route-by-route check of the existing plugins for a `GET` that changes something.

Smaller follow-ups found while building stage 1:

- The Admin page loads its data before the forced password change finishes, so the raw "password change required" message shows behind the dialog until it reloads.
- The lockout counts live in memory, so a restart clears them. Acceptable for one process; revisit if NetView ever runs as several.
- IPv6 password spraying (many usernames) from one /64 is bounded only by the /64 backstop (250 per window). Lowering it would let one host lock out a whole LAN /64; revisit with real deployments.

## From plugin identity and uninstall (2026-11-12)

Uninstall from the gallery is done (see `specs/2026-11-12-plugin-identity-and-uninstall-design.md`). Left for later:

- Admin → Roles and Users list the permissions of an uninstalled plugin as raw guid ids (`<guid>.view`); label them from the catalog entry when one exists.
- Available cards show no type chip (`AvailableOut` has no `plugin_type`, though index entries carry it).
- A card that lost a guid conflict, or a stopped "Uninstall didn't finish" card, shows a disabled, checked "On" switch; "Not loaded" would read better.
- `set_enabled` and `update_settings` don't take the host lock, so a request racing an uninstall with "delete data" can re-save the plugin's state row.
- A job already running when its plugin is uninstalled can still hold a unit of work opened before the stop.
- No test pins the three copies of the legacy id → guid map (migration 0006, `legacy.LEGACY_PLUGIN_GUIDS`, the manifests) to each other.
- Catalog and install match known guids from loaded cards only; a folder in `<data dir>/plugins` with a `plugin.json` but no `__init__.py` is refused only when the install job runs.
- The 0006 migration skips (rather than logs) report sections whose `plugin_id` it doesn't know, and its downgrade can hit a unique-key clash in the rare case where both old and new keys existed.
- A legacy `alembic_version_<id>` table with no row blocks that plugin's data move on every start.
- Smaller test and wording polish noted during review (duplicate tests, a few stale comments).

## From the UI updates (2026-11-14)

Reviewed and judged safe to leave for later (`specs/2026-11-12-ui-updates-design.md`):

- **Dashboard layout reads:** if the first `getLayout()` fails after a layout-changed re-fetch has already succeeded, the failure overwrites the good result. A re-fetch that started before a save can also apply an older layout. After a failed first read, editing comes back only on remount or a Settings reset; there is no retry.
- **Save button focus:** the dashboard toolbar is rebuilt when a save starts or ends, so keyboard focus leaves the Save button. Group by changes lose focus the same way.
- **Resetting before plugins load:** Reset → Save compares against the layout captured when Reset was pressed. If a plugin's cards appear in between, Save stores a copy instead of deleting.
- **Edit-tool labels:** for tiles without a title, the edit tools read "Plugin: id" (for example "Health: gateway").
- **Untested dashboard code:** grid hide/re-show identity, collapse persistence, and the edit-mode DOM (cross-group refusal, decorate, nudge focus) have no tests.
- **Blade layout:**
  - Group headings have no accessible name in rail mode.
  - The root crumb is styled as a link but does nothing.
  - Esc works only while focus is inside the child blade.
  - Toggling a group during a search changes the stored state without showing it.
- **Admin:**
  - Rename replaces the role editor instead of sitting on top of it.
  - A Roles page error isn't cleared after a successful reload.
  - A forbidden `/admin/<section>` URL isn't rewritten to the section actually shown.
  - The child-blade setup code is repeated across users, roles and default-dashboard.
- **Settings:**
  - The plugin child blade is 520px wide, not the spec's 420px; this looks deliberate, for plugin forms.
  - A failed uninstall's message is wiped by the redraw that follows (this predates the blade layout).
  - The monogram is gone from the plugin header.
- **Small backend tidy-ups:**
  - `DefaultLayoutIn` has no `extra="forbid"`.
  - Roles are sorted case-sensitively.
  - `"core.dashboard"` is written out in two places.
  - The 422 layout test asserts on `str(body)`.
  - `CORE_TABLES` in `test_migrate.py` doesn't list `user_dashboard_layouts`.
- **Body-limit middleware:** the request cap replays a partial body when the client disconnects.

## From GeoTrace part 1 (SDK 2.1) (2026-11-26)

- **SDK version clash:** the unmerged local branch `feature/opnsense-plugin` also sets SDK 2.1; whichever of the two merges to main second renumbers to 2.2 (`SDK_VERSION`, plugin `sdk_version` ranges, version tests).
- Linux traceroute/tracepath fixtures (`tests/fixtures/net/traceroute/*linux*`) and the IPv6 success fixtures (`tracert_win_ipv6.txt`, `tests/fixtures/net/ping6/ping6_win_reply.txt`, `ping6_linux_reply.txt`) are synthesized (marked `# edited`); replace them with real captures (Proxmox host; a LAN with an IPv6 route).
- This LAN has no IPv6 route today (ULA only), so IPv6 targets will fail until OPNsense provides IPv6.
- Plugin index parse warnings mix `plugin.json:` and `plugin index:` prefixes.
- The "unsupported" order of catalog entries can change after a cache round trip (only whether any are unsupported is read).
- `files_dir` has no closed guard, so it could recreate the folder after uninstall; read-only files are reported as not removed (no `onexc` retry); `FakePluginContext` leaks temp dirs; no test for the `RuntimeError` when `files_dir` is `None`; the undeletable-folder test doesn't assert the `.db` and state are still removed.
- `is_ipv6` is just `':' in value` with no docstring; no test for the Windows "Destination host unreachable" reply; end-to-end IPv6 ping is tested only on win32; macOS `ping6` is bounded only by the subprocess timeout.
- The `ping6` retry also runs after a hung `ping -6` (up to twice the timeout) and is keyed on `not require_ttl` rather than `is_ipv6`.
- Linux traceroute timeout uses the clamped ms, not the rounded-up `-w` seconds, so macOS serial probes may be cut off.
- A finished traceroute with no useful output gives `error=None` (the UI wants plain words); a timeout before any hop is reported as "could not be run"; there is a timer race on a completed run; the fake says "not installed" for an unknown target.
- `on_hop` exceptions propagate despite the "Never raises" docstring.
- The `run_lines` kill test needs the child to print within 0.5 s (raise to 2 s if flaky); hop IPs parsed from output keep their `%scope` text (display only).

## From GeoTrace (2026-11-27)

- MaxMind GeoLite2 and RIPE IPmap as location sources the administrator sets up with their own account details (planned later; Settings > Location data shows them as "coming later").
- Publish the Cesium bundle (`geotrace-cesium-1.144.0.zip`, built by `plugins/geotrace/tools/build_cesium_bundle.py`) as a release asset and pin `BUNDLE_URL`, `BUNDLE_SHA256` and `BUNDLE_BYTES` in `plugins/geotrace/bundle.py`. Until then the globe cannot load.
- Replace the synthesized Linux traceroute, tracepath and ping6 output fixtures with real captures.
- SDK 2.1 clash: the unmerged `feature/opnsense-plugin` branch also sets SDK 2.1. Whichever of the two merges second renumbers to 2.2.
