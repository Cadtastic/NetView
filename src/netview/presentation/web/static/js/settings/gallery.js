// Pure helpers for the plugin galleries: status, ordering, filtering and card markup.
import { needsSetup } from "../nav.js";
import { dotHtml } from "../dot.js";
import { esc } from "../util.js";
import { CAPABILITY_LABELS } from "./plugins-tab.js";

const firstLine = (s) => String(s ?? "").split(/\r?\n/, 1)[0];

/**
 * The status dot of a plugin: {kind, tip}. Precedence: failed, then pending or restart required,
 * then off, then needs configuring, then active.
 */
export function pluginStatus(info) {
  if (info.state === "failed") return { kind: "bad", tip: `Failed: ${firstLine(info.error)}` };
  if (info.state === "pending" || info.restart_required) return { kind: "restart", tip: "Awaiting restart" };
  if (!info.enabled || info.state === "disabled") return { kind: "off", tip: "Off" };
  if (needsSetup(info)) return { kind: "warn", tip: "Needs configuring" };
  return { kind: "ok", tip: "Active" };
}

/** What deserves a dot on the Installed rail entry: "bad", "warn" or null. */
export function attention(list) {
  if (list.some((p) => p.state === "failed" || p.state === "pending" || p.restart_required)) return "bad";
  if (list.some(needsSetup)) return "warn";
  return null;
}

const RANK = { bad: 0, restart: 1, warn: 2 };
const rankOf = (p) => RANK[pluginStatus(p).kind] ?? 3;

/** Installed plugins, attention first (failed, awaiting restart, needs configuring), then by name. */
export function sortInstalled(list) {
  return [...list].sort(
    (a, b) => rankOf(a) - rankOf(b) || a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
  );
}

/** True when `text` appears in the plugin's name or description (case-insensitive); empty text matches all. */
export function matchesFilter(p, text) {
  const q = String(text ?? "").trim().toLowerCase();
  if (!q) return true;
  return `${p.name} ${p.description ?? ""}`.toLowerCase().includes(q);
}

/** Where the plugin comes from, as shown on its card. */
export function sourceText(p) {
  if (p.state === "pending") return "Just installed";
  return p.source === "folder" ? "Folder" : "Built in";
}

/** The letter shown in a card's monogram tile. */
export function monogram(name) {
  return String(name ?? "").trim().charAt(0).toUpperCase();
}

/** The solid capability chips of a plugin. */
export function chipsHtml(keys) {
  return keys
    .map((k) => `<span class="chip solid" title="${esc(k)}">${esc(CAPABILITY_LABELS[k] || k)}</span>`)
    .join("");
}

function switchHtml(p) {
  const off = p.state === "failed";
  return `<label class="switch"><input type="checkbox" data-enable="${esc(p.id)}" ${p.enabled ? "checked" : ""} ${off ? "disabled" : ""}><span class="track"></span>${p.enabled ? "On" : "Off"}</label>`;
}

/** One card of the Installed gallery. The whole card opens the overlay; the switch does not. */
export function installedCardHtml(p) {
  const st = pluginStatus(p);
  const foot =
    p.state === "pending"
      ? '<span class="pnote">Loads the next time netview starts</span>'
      : switchHtml(p);
  return `<div class="pcard" role="button" tabindex="0" data-id="${esc(p.id)}" aria-label="${esc(`${p.name}, ${st.tip}`)}">
    <div class="phead"><span class="mono" aria-hidden="true">${esc(monogram(p.name))}</span>
      <div class="ptitle"><b>${esc(p.name)}</b><span class="pver">${esc(p.version)} · ${esc(sourceText(p))}</span></div>
      <span class="pdot">${dotHtml(st.kind, st.tip)}</span></div>
    <p class="pdesc">${esc(p.description)}</p>
    <div class="chips">${chipsHtml(p.capabilities || [])}</div>
    <div class="pfoot">${foot}</div>
  </div>`;
}

// ---- Available gallery ------------------------------------------------------

/** "just now", "4 min ago", "2 h ago" or "3 d ago". */
export function ageText(ms, now) {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

function dateText(ms) {
  const d = new Date(ms);
  const two = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
}

/** The line under the Available heading: when the list was checked, or what went wrong. */
export function catalogLine(cat, now) {
  const fetched = cat.fetched_at_ms;
  if (cat.error) {
    return fetched == null ? cat.error : `${cat.error} \u00b7 showing the list from ${dateText(fetched)}`;
  }
  if (fetched == null && cat.source === "bundled") return "Built-in list";
  if (fetched == null) return "From github.com/Cadtastic/NetView";
  return `From github.com/Cadtastic/NetView \u00b7 checked ${ageText(fetched, now)}`;
}

/** What the Available pane says when it has no cards. `filtering` is true while the filter box has text. */
export function emptyAvailableText(cat, filtering = false) {
  if (filtering) return "No plugins found.";
  if (cat.error && cat.fetched_at_ms == null && !cat.plugins.length) {
    return "Couldn't reach GitHub. Check the connection and press Refresh.";
  }
  return "Every available plugin is installed.";
}

const BUSY = { queued: "Queued", downloading: "Downloading\u2026", installing: "Installing\u2026" };

function progressHtml(job) {
  let text = BUSY[job.state];
  let bar = '<progress max="100"></progress>';
  if (job.state === "downloading" && job.percent != null) {
    text = `Downloading\u2026 ${job.percent}%`;
    bar = `<progress max="100" value="${Number(job.percent)}"></progress>`;
  }
  return `<div class="pprog" role="status">${bar}<span class="pnote">${esc(text)}</span></div>`;
}

const installButton = (entry, disabled) =>
  `<button type="button" class="primary small" data-install="${esc(entry.id)}"${disabled ? " disabled" : ""}>Install</button>`;

/** The footer of an Available card: Install, its progress, its error, or why it cannot be installed. */
export function availableFooter(entry, job) {
  if (job && BUSY[job.state]) return progressHtml(job);
  if (job && job.state === "failed") return `<p class="err">${esc(job.error || "Install failed")}</p>${installButton(entry, false)}`;
  if (entry.installable === false) return `<span class="pnote">${esc(entry.reason || "")}</span>${installButton(entry, true)}`;
  return installButton(entry, false);
}

/** One card of the Available gallery: like an Installed card, without a status dot. */
export function availableCardHtml(entry, job) {
  const by = entry.author ? ` \u00b7 by ${esc(entry.author)}` : "";
  return `<div class="pcard avail" data-id="${esc(entry.id)}">
    <div class="phead"><span class="mono" aria-hidden="true">${esc(monogram(entry.name))}</span>
      <div class="ptitle"><b>${esc(entry.name)}</b><span class="pver">${esc(entry.version)}${by}</span></div></div>
    <p class="pdesc">${esc(entry.description)}</p>
    <div class="chips">${chipsHtml(entry.capabilities || [])}</div>
    <div class="pfoot">${availableFooter(entry, job)}</div>
  </div>`;
}
