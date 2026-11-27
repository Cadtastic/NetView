// Globe drawing keys (pure, unit-tested). A drawing is stored under a key, not a bare trace id, so two blades can draw the same trace.
export const CMP_NEW = "cmp-new";
export const CMP_OLD = "cmp-old";
export const COMPARE_KEYS = [CMP_NEW, CMP_OLD];

/** The Route blade's drawing for a target. */
export const routeDrawKey = (targetId) => `route:${targetId}`;

/** Whether a drawing under `key` shows when the globe is focused on `focus` (null = no focus, everything shows). */
export function isShown(key, focus) {
  return focus == null || focus.has(key);
}

/** The key a drawing is stored under: the one asked for, else the trace id. */
export const drawKey = (trace, key) => (key === undefined || key === null ? trace.id : key);
