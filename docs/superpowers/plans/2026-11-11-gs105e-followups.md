# GS105E plugin: phase 1 follow-ups

Branch `fix/gs105e-followups`, cut from `feature/gs105e-plugin` at 6f4cfdb. These are the items the phase 1 reviews deferred as
bounded or minor ("fix soon after merge", "Final: parked"). Each one gets a test that fails before the fix.

Anti-goals still hold: never lock the user out of the switch, never retry a refused password, never hammer the switch, never
leak the password. Tests use the fake switch and the fake clock; nothing contacts 192.168.1.3.

Gates: `uv run pytest -q`, `npm test`, `uv run ruff check plugins/gs105e`, `uv run ruff format --check plugins/gs105e`,
`uv run mypy src plugins`.

## Part A: `plugins/gs105e/service.py` (tests in `tests/integration/test_gs105e_service.py`)

A1. Rates during a login backoff. `_back_off_login` clears `self._rates` when it backs off (the branch where the session is
logged out), so a cross-group login backoff never shows the last throughput as live for up to 300 s.

A2. Poll now after a failed login. `_run_all` stops after any group that leaves the session not logged in
(`self._session is None or not self._session.logged_in`), as well as when `_run` returns False. A malformed login reply then
costs one login POST per press, not three.

A3. Pause and rates. `pause()` clears `_rates` outside the poll lock, so a counters poll already past its last request can
write rates back after the pause. Also clear `_rates` in `_settle()` when a pause is active (the locked end of every poll), so
the rates are blank once the running poll finishes.

A4. A new wrong password is tried once. `ctx.settings` is live before `settings_changed()` runs, so a poll can log in with the
new password, be refused (`_stopped = True`), and then `settings_changed()` clears `_stopped` and the next poll tries the same
password again. Fix: when a poll's login is refused, remember the refused connection key (host, port, password) that the
session actually used (`self._session_key[:3]`), as `self._refused_key`. `settings_changed()` keeps `_stopped` True (and does
not emit anything new) when the new connection key equals `_refused_key`; any other key clears it as today. A successful
`test_connection()` clears `_refused_key`. Test: set a wrong password on the live settings, poll (one refused login POST),
call `settings_changed()`, poll again: no second login POST, `login` reads "failed". A different password after that is tried.

A5. Closed flag. `shutdown()` sets `self._closed = True` first, then logs out as today. While closed: `poll_block_reason()`
returns a new `SHUT_DOWN = "shut down"` reason (checked first), so jobs and Poll now do nothing; `_guarded_fetch` raises
`_Interrupted` for any request except LOGOUT, so a poll running across shutdown stops before its next request;
`test_connection()` returns `{"ok": "false", "error": "shut down"}`. Test: after `shutdown()`, the poll methods and
`start_poll_all()` send no request to the fake switch.

A6. Connection change resets per-switch state. When `settings_changed()` sees a new host or port (not only a new password),
`_apply_reset` also sets `_current = None`, `_claimed = {}`, `_crc_alerted = {}` (record which kind of change happened, for
example `self._pending_switch_change`). A password-only change keeps them, so config diffs on the same switch keep working.
`diff(None, ...)` returns no changes, so the first poll of the new switch is a quiet baseline. Test: poll switch A, change
the host to a switch whose config differs, poll: no config-change events; a claim is made for the new switch.

A7. Stale outcomes after a settings change. `_run_poll` already ignores an `AuthFailed` from an older generation. Apply the
same generation check to every outcome: `Unreachable`, `UnsupportedSwitch`, `PageChanged`, the generic `Exception`, and
success. When `generation != self._generation`, record nothing (no error, no backoff, no reachable/unreachable event, no
`_last_poll_ms`) and return True. Test: a poll that fails Unreachable after `settings_changed()` moved to a new host (simulate
by changing settings from inside the fake fetch, or by calling `settings_changed()` between the step and the outcome) emits
no unreachable/reachable pair.

A8. `test_connection()` settles. Wrap the locked body in `try/finally` that calls `self._settle()` (replacing the success
path's own pause check), so a pause or connection change that arrived during a long failing test is honoured at once. Add the
generation check there too: an `AuthFailed` sets `_stopped` only when the generation did not change during the test. Test: a
pause set during a failing test leaves the session logged out when `test_connection()` returns.

A9. Summary fields for the UI (Part C uses them):
- `throughput_bps` is `None` when there are no live rates (`not self._rates`), otherwise `{"in": ..., "out": ...}` as today.
  Update the two existing tests that expect `{"in": 0, "out": 0}`.
- add `pause_remaining_ms`: `paused_until_ms - now` while a pause runs, else `None`. Keep `paused_until_ms`. Add it to the
  summary keys test.

Keep service.py readable; do not grow it far past its current size (add small helpers rather than repeating code).

## Part B: `pages.py`, `routes.py`, `storage.py` (tests in `test_gs105e_pages.py`, `test_gs105e_api.py`, `test_gs105e_storage.py`)

B1. Unknown rate-limit code. In `parse_qos`, a code not in `_RATE_KBPS` raises `rate.fail(f"unknown rate code {code}")`
(a `PageChanged`) instead of reading as "no limit". Code 1 stays "no limit" (None).

B2. Unknown linked speed. In `parse_port_status`, the linked-speed value "No Speed" reads as `None` (link down); any value
not in `_LINK_MBPS` and not "No Speed" raises `page.fail(f"unknown linked speed {text!r}")`. Tests for both with the fixture
edited in the test (string replace on the fixture HTML).

B3. Port with no data yet. `GET /ports/{n}` for a valid port (1..5) with no data answers 503 with detail
`"no data for port {n} yet"`; an out-of-range port stays 404 `"unknown port {n}"`. Test both in `test_gs105e_api.py`.

B4. Rollup grace. `rollup_and_prune` rolls up a bucket only once `bucket + BUCKET_MS + ROLLUP_GRACE_MS <= now_ms`, with
`ROLLUP_GRACE_MS = 120_000` (the longest poll job timeout), so a sample stamped just before a bucket boundary but written
after the boundary is still in the mean. Update existing rollup tests whose `now` sits right at a boundary; add a test: a
sample stamped `boundary - 1` and written after a rollup call at `boundary + 1` is included in that bucket's rollup.

## Part C: UI (`static/page.js`, `static/port-grid.js`, `static/report.js`; tests in `tests/js/`)

C1. Pause countdown on server time. The summary now carries `pause_remaining_ms` (A9). When a summary arrives, the page
records the local end of the pause as `Date.now() + pause_remaining_ms` (null when not paused), and the countdown label and
the "pause ran out, fetch once" check use that local end, never `paused_until_ms` against the browser clock. Make the pure
part testable: for example `pauseLabel(untilLocal, now)` plus `localPauseEnd(summary, receivedAt)`. Test: with a summary whose
`paused_until_ms` is an hour in the browser's past but `pause_remaining_ms` is 5 min, the label reads "Paused for 5 min" and
the expiry check is false.

C2. Throughput dash. `reportModel` shows the dash when `throughput_bps` is null (it already does for a falsy value; add a
test). Anywhere else that renders `throughput_bps` does the same.

C3. Faceplate aria for a non-member. `membershipWords("")` returns "not a member of the shown VLAN" (so `portWords` turns it
into "not a member of VLAN 10"); `null`/`undefined` (not read) stays silent. Test in the faceplate tests.

## Review round (two Opus reviewers, split by files: Part A; Parts B and C)

All plan items were confirmed. Three minor findings were fixed:

- A refusal now stops polling when the refused key equals the live settings (`_refusal_is_current`), not when the
  generation is unchanged. `settings_changed()` can land while the login POST with the new password is in flight; the
  generation check then dropped the refusal and the next poll sent the same password again.
- `_settle()` also logs out once the service is closed, so a poll that outlives `shutdown()`'s 10 s wait still gives the
  switch's login back.
- The store stamps `receivedAt` when data arrives; the page counts a pause down from that, not from when it first sees the
  summary (a summary fetched by the dashboard tile before the page mounted).
