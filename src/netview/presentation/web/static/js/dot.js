// Animated status dot. The CSS lives in css/app.css (.sdot); only the disc animates, never the tooltip.
import { esc } from "./util.js";

/**
 * Markup for a status dot. `kind` is ok, warn, bad, restart, off or idle; `tip` is both the
 * accessible name and the hover tooltip. `size: "sm"` is the 10px rail/nav/table size; `still`
 * turns the animation off for a dot that sits where motion would distract.
 */
export function dotHtml(kind, tip, { size = "md", still = false } = {}) {
  const cls = `sdot ${kind}${size === "sm" ? " sm" : ""}${still ? " still" : ""}`;
  return `<span class="${cls}" role="img" aria-label="${esc(tip)}" data-tip="${esc(tip)}"></span>`;
}
