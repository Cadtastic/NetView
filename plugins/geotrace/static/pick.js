// Pick mode: Settings sends the user to the GeoTrace page, one click on the globe sets the home location,
// and Settings opens again with the numbers filled in. The hand-over goes through sessionStorage (blocked storage = no pick mode).
export const PICK_KEY = "netview.geotrace.pick";
export const PICKED_KEY = "netview.geotrace.picked";
export const PICK_EVENT = "geotrace:pick";
export const PICK_HINT = "Click the globe to set your home location.";

function store(storage) {
  return storage ?? globalThis.sessionStorage;
}

/** Ask the page to start pick mode. Returns false when storage is blocked. */
export function requestPick(storage) {
  try {
    store(storage).setItem(PICK_KEY, "1");
    return true;
  } catch (e) {
    return false;
  }
}

/** True once if a pick was requested (and clears the request). */
export function takePickRequest(storage) {
  try {
    const s = store(storage);
    const asked = s.getItem(PICK_KEY) === "1";
    if (asked) s.removeItem(PICK_KEY);
    return asked;
  } catch (e) {
    return false;
  }
}

export function savePicked(lat, lon, storage) {
  try {
    store(storage).setItem(PICKED_KEY, JSON.stringify({ lat, lon }));
  } catch (e) {
    // blocked storage: Settings opens without the numbers
  }
}

/** {lat, lon} (numbers) left by a pick, or null; clears it. */
export function takePicked(storage) {
  try {
    const s = store(storage);
    const raw = s.getItem(PICKED_KEY);
    if (raw === null) return null;
    s.removeItem(PICKED_KEY);
    const v = JSON.parse(raw);
    return Number.isFinite(v.lat) && Number.isFinite(v.lon) ? { lat: v.lat, lon: v.lon } : null;
  } catch (e) {
    return null;
  }
}

/**
 * Show the hint and wait for one pick. `pickOnce(cb) -> cancel` is the globe's; `onDone({lat, lon} | null)` runs once,
 * with null when Esc cancelled. Returns a function that ends pick mode without calling onDone.
 */
export function startPick(root, { pickOnce, onDone, doc = document }) {
  const banner = doc.createElement("div");
  banner.className = "gt-pick-banner";
  banner.setAttribute("role", "status");
  banner.textContent = PICK_HINT;
  root.appendChild(banner);
  root.classList.add("gt-picking");
  let ended = false;
  let cancelPick = () => {};
  const finish = (value, notify) => {
    if (ended) return;
    ended = true;
    cancelPick();
    doc.removeEventListener("keydown", onKey, true);
    banner.remove();
    root.classList.remove("gt-picking");
    if (notify) onDone(value);
  };
  function onKey(e) {
    if (e.key === "Escape") {
      e.stopPropagation();
      finish(null, true);
    }
  }
  doc.addEventListener("keydown", onKey, true);
  cancelPick = pickOnce((point) => finish(point, true)) || (() => {});
  return () => finish(null, false);
}
