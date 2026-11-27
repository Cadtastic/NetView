// A refresh loop where only the newest request may apply its answer, and an older one waits for the newest instead of
// reporting on its own (stale) answer. refresh() resolves true when the newest request's targets fetch succeeded.
export function createRefresher({ load, apply, isGone }) {
  let seq = 0;
  let latest = Promise.resolve(false);
  function refresh() {
    const mine = ++seq;
    const run = (async () => {
      const result = await load();
      if (isGone()) return false;
      if (mine !== seq) return latest; // superseded: the newest request answers for us
      apply(result);
      return result.targetsOk;
    })();
    latest = run;
    return run;
  }
  return refresh;
}

/** The load-error line to show after a reload: set only when the fetch failed and there is no list to show. */
export const LOAD_ERROR = "Could not load the targets.";
export function loadErrorAfter(ok, targets) {
  return !ok && targets === null ? LOAD_ERROR : "";
}
