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
