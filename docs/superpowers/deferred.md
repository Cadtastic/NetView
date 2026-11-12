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
