# Deferred items (carry into plan 2)

These are from the final review and re-review of plan 1 and plan 1b (2026-11-10). None of them blocks the merge.

- `DELETE /api/v1/devices/self` isn't refused on the server; only the UI hides the button. Add a `SELF_KEY` guard in `usecases/forget.py`.
- The plugin write fence covers INSERT, UPDATE and DELETE, but not DDL. Add DROP, ALTER and CREATE on non-prefixed tables to the authorizer's denied actions (`infrastructure/db/engine.py`).
- A timed-out plugin `setup()` thread can call `ctx.subscribe()` after the context is closed. Add a `_closed` flag that makes `subscribe` do nothing (`infrastructure/plugins/context.py`).
- `CoreFacade.record_sightings` bypasses the no-network guard, which lives only in `RunScan`. Move the guard into `RecordSightings`, or document it.
- `/state` still loads types and hints once per device. Bulk-load them like claims.
- Conflict de-duplication is held in memory, so it resets on restart.
- `type_claims.updated_ms` is always 0. Fill it in or drop it.
- The real LAN captures in `tests/fixtures/net/` must be scrubbed before the repository is published.

## From the GSM7248 plugin, phase 1 (2026-11-10)

- Keep the plugin's SNMP secrets in the OS keyring instead of the settings store.
- Replace `walk_basic.txt` with a scrubbed walk captured from the real switch.
- Confirm the NETGEAR CPU and memory OIDs if Task 3 left them as `None`.
- The core cannot clear a source's stale hints, so hints from a removed or renamed device linger (see Task 6).
- STP port **role** (Designated or Backup) needs the NETGEAR MSTP private MIB, so phase 1 does not show it.
- Check the switch setup commands in `docs/gsm7248-setup.md` against NETGEAR's *GSM7248 CLI Command Reference* and remove the "(check against the CLI reference)" marks.
