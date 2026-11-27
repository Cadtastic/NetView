// Pure model for the Compare blade (unit-tested): display rows, cell text and the split sentence.
import { hopPlace, hopRtt } from "./hops.js";
import { fmtRtt, agoText } from "./targets.js";

/** API rows [{n, a, b, differs}] -> display rows {n, a, b, differs, className}. */
export function compareRows(apiRows) {
  return (Array.isArray(apiRows) ? apiRows : []).map((r) => ({
    n: r.n,
    a: r.a ?? null,
    b: r.b ?? null,
    differs: Boolean(r.differs),
    className: r.differs ? "gt-diff" : "",
  }));
}

/** "They split after hop N.", "Same route." or, when nothing is located at the split, "The routes differ.". */
export function splitSentence(splitAfter, rows) {
  if (splitAfter === 0) return "They split from the first hop.";
  if (Number.isInteger(splitAfter)) return `They split after hop ${splitAfter}.`;
  return (rows || []).some((r) => r.differs) ? "The routes differ." : "Same route.";
}

/** One table cell: "—" for a hop this route does not have, "* * *" for a silent one, else place and time. */
export function cellText(hop) {
  if (hop == null) return "—";
  const place = hopPlace(hop);
  if (place === "No reply") return "* * *";
  const rtt = hopRtt(hop);
  return rtt === null ? place : `${place} · ${fmtRtt(rtt)}`;
}

/** A picker entry: "2 h ago · 8 hops · 58 ms". */
export function traceLabel(t, now = Date.now()) {
  const state = t.status === "failed" ? "failed" : fmtRtt(t.rtt_ms);
  return `${agoText(t.started_ms, now)} · ${t.hop_count} ${t.hop_count === 1 ? "hop" : "hops"} · ${state}`;
}

/**
 * The entries of one picker: every done trace in history, plus a "Choose a trace" placeholder when nothing
 * is picked, or a "Trace N" entry for a pick older than the list. Never an entry for a null id.
 * Returns {options: [{value, text}], selected}.
 */
export function pickerOptions(history, current, now = Date.now()) {
  const options = (Array.isArray(history) ? history : []).map((t) => ({ value: String(t.id), text: traceLabel(t, now) }));
  if (current === null || current === undefined) {
    options.unshift({ value: "", text: "Choose a trace" });
    return { options, selected: "" };
  }
  const selected = String(current);
  if (!options.some((o) => o.value === selected)) options.push({ value: selected, text: `Trace ${selected}` });
  return { options, selected };
}
