// Blade stack: pure state for the blades stacked left to right over the globe (no DOM, so it is unit-tested).
export const BLADES_KEY = "netview.geotrace.blades";

/** Blades kept open at full width; every older one shrinks to a strip. */
const FULL_WIDTH = 2;

function clean(list) {
  const seen = new Set();
  const out = [];
  for (const b of Array.isArray(list) ? list : []) {
    if (!b || typeof b.key !== "string" || b.key === "" || seen.has(b.key)) continue;
    seen.add(b.key);
    out.push({ key: b.key, min: Boolean(b.min), wide: Boolean(b.wide) });
  }
  return out;
}

function squeeze(blades) {
  const cut = blades.length - FULL_WIDTH;
  blades.forEach((b, i) => {
    if (i < cut) b.min = true;
  });
}

/** Blades saved by saveBlades, or [] when nothing usable is stored or storage throws. */
export function loadBlades(storage) {
  try {
    const raw = (storage ?? globalThis.localStorage).getItem(BLADES_KEY);
    return raw ? clean(JSON.parse(raw)) : [];
  } catch (e) {
    return [];
  }
}

export function saveBlades(state, storage) {
  try {
    (storage ?? globalThis.localStorage).setItem(BLADES_KEY, JSON.stringify(state.blades));
  } catch (e) {
    // blocked storage: the layout just isn't remembered
  }
}

/** `initial` is a saved list of {key, min, wide}. Every call returns a copy of the state: {blades: [{key, min, wide}]}. */
export function createBladeStack(initial = []) {
  let blades = clean(initial);
  squeeze(blades);
  const snapshot = () => ({ blades: blades.map((b) => ({ ...b })) });
  return {
    state: snapshot,
    /** Open `key` at position `level` (default: the end of the stack): that blade and everything to its right closes first. */
    open(key, { level = blades.length, wide = false } = {}) {
      const at = blades.findIndex((b) => b.key === key);
      if (at >= 0 && at < level) blades = blades.slice(0, at);
      blades = blades.slice(0, Math.max(0, Math.min(level, blades.length)));
      blades.push({ key, min: false, wide: Boolean(wide) });
      squeeze(blades);
      return snapshot();
    },
    /** Close `key` and every blade to its right. */
    close(key) {
      const at = blades.findIndex((b) => b.key === key);
      if (at >= 0) blades = blades.slice(0, at);
      return snapshot();
    },
    minimise(key) {
      const b = blades.find((x) => x.key === key);
      if (b) b.min = true;
      return snapshot();
    },
    restore(key) {
      const b = blades.find((x) => x.key === key);
      if (b) b.min = false;
      return snapshot();
    },
  };
}

/**
 * Runs stack changes one at a time: `run(op)` calls op() for the new state and hands it to `apply`. A change asked for
 * while `apply` is running (a blade opening another from its render) waits its turn instead of re-entering `apply`.
 */
export function createBladeController(apply) {
  const queue = [];
  let busy = false;
  return {
    run(op) {
      queue.push(op);
      if (busy) return;
      busy = true;
      try {
        while (queue.length) apply(queue.shift()());
      } finally {
        busy = false;
        queue.length = 0;
      }
    },
  };
}

/** A blade's title: `title` is a string or a (key, snapshot) => string; `fallback` when it is missing or throws. */
export function bladeTitle(title, key, snapshot, fallback = key) {
  if (typeof title === "string") return title;
  if (typeof title === "function") {
    try {
      const t = title(key, snapshot);
      if (typeof t === "string" && t !== "") return t;
    } catch (e) {
      // fall through to the fallback
    }
  }
  return fallback;
}
