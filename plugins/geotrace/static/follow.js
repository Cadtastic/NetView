// A small hand-off between blades: "Trace now" in the Targets blade tells the target's Route blade which run to follow.
const pending = new Map(); // target id -> trace id (waiting for a Route blade to take it)
const listeners = new Map(); // target id -> Set<fn(traceId)>

/** Ask the Route blade of `targetId` to follow `traceId`; held until a blade for that target takes it. */
export function follow(targetId, traceId) {
  const subs = listeners.get(targetId);
  if (subs && subs.size) for (const fn of [...subs]) fn(traceId);
  else pending.set(targetId, traceId);
}

/** The trace id waiting for `targetId`, once. */
export function take(targetId) {
  const id = pending.get(targetId);
  pending.delete(targetId);
  return id;
}

/** fn(traceId) is called for every follow(targetId, …) while subscribed. Returns the unsubscribe function. */
export function subscribe(targetId, fn) {
  if (!listeners.has(targetId)) listeners.set(targetId, new Set());
  listeners.get(targetId).add(fn);
  return () => listeners.get(targetId)?.delete(fn);
}
