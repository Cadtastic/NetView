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
