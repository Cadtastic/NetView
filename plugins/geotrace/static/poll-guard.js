// Rules for polling one trace by id (pure, unit-tested): stop on 404, give up after a few other errors, and
// refuse an answer that belongs to another trace.
export const MAX_POLL_FAILURES = 5;
export const GONE_TEXT = "This trace is no longer available.";
export const LOST_TEXT = "Lost contact with NetView.";

/**
 * createPollGuard({maxFailures}) -> {failed(err), ok()}.
 * failed(err) -> "gone" (a 404: stop and say GONE_TEXT), "retry" (try again next tick) or "stop" (too many errors in a row).
 * ok() forgets earlier errors.
 */
export function createPollGuard({ maxFailures = MAX_POLL_FAILURES } = {}) {
  let failures = 0;
  return {
    failed(err) {
      if (err && err.status === 404) return "gone";
      failures += 1;
      return failures >= maxFailures ? "stop" : "retry";
    },
    ok() {
      failures = 0;
    },
  };
}

/** Route: a polled trace is ours only if it belongs to this blade's target. */
export function isTargetTrace(next, targetId) {
  return next != null && next.target_id === targetId;
}

/** Trace once: ours only if it is a one-off, and (after the first answer) has the same start time. */
export function isOnceTrace(next, first) {
  if (next == null || next.trigger !== "once") return false;
  return first == null || next.started_ms === first.started_ms;
}
