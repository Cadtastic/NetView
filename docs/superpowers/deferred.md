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

- Uninstall a folder plugin (remove its folder on the next start; decide what happens to its tables and settings).
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
