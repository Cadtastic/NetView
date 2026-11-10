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
