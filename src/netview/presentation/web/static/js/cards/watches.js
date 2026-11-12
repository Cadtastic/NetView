// Core Watches card: one row per watched host, checked layer by layer (ARP, ping, each TCP port).
import { apiSend } from "../api.js";
import { esc, fmtMs, fmtTime } from "../util.js";
import { dotHtml } from "../dot.js";

export const WATCHES_SUB = "Checked every few seconds, layer by layer: ARP (is it on this network?), ping, then each TCP port.";
export const WATCHES_EMPTY = "No watched hosts. Add one below, for example the iDRAC address with ports 443 and 22.";
export const WATCHES_NO_HEALTH = "No health plugin is turned on, so watches are not being checked.";
export const WATCH_PLACEHOLDER = "192.168.1.128:443,22=R720 iDRAC";

const STATUS = {
  up: ["ok", "Up"],
  degraded: ["warn", "Partly up"],
  present: ["warn", "On the network only"],
  absent: ["bad", "Not on the network"],
  down: ["bad", "No reply"],
  pending: ["off", "Checking"],
};

/** The status dot of a watch: colour and motion say the state, the tooltip and accessible name spell it out. */
export function statusChip(state) {
  const [kind, label] = STATUS[state] || ["idle", String(state ?? "")];
  return dotHtml(kind, label);
}

const layer = (kind, text) => `<span class="layer ${kind}">${esc(text)}</span>`;

/** The ARP, ping and per-port chips of one watch. */
export function layerChips(w) {
  if (w.state === "pending") {
    // Nothing has been measured yet, so no layer has passed or failed.
    return [layer("na", "… ARP"), layer("na", "… Ping"), ...(w.ports || []).map((p) => layer("na", `… TCP ${p}`))].join("");
  }
  const arp =
    w.l2 == null
      ? layer("na", "ARP: n/a (routed)")
      : layer(w.l2 ? "ok" : "bad", `${w.l2 ? "✓" : "✕"} ARP${w.mac ? " " + w.mac : ""}`);
  const ping = w.rtt_ms != null ? layer("ok", `✓ Ping ${fmtMs(w.rtt_ms)} ms`) : layer("bad", "✕ Ping");
  const ports = (w.ports || []).map((p) => {
    const s = (w.port_state || {})[String(p)];
    if (s === "open") return layer("ok", `✓ TCP ${p} open`);
    if (s === "closed") return layer("bad", `✕ TCP ${p} refused`);
    if (s === "filtered") return layer("bad", `✕ TCP ${p} no answer`);
    return layer("na", `… TCP ${p}`);
  });
  return [arp, ping, ...ports].join("");
}

/** The history strip: one tick per check, 1 is up, 0.5 partly up, anything else down. */
export function historyStrip(history) {
  const h = history || [];
  const ticks = h.map((v) => `<span class="${v === 1 ? "u" : v === 0.5 ? "d" : "x"}"></span>`).join("");
  return `<span class="strip" title="Last ${h.length} checks">${ticks}</span>`;
}

/** One watch as HTML. Labels and diagnoses can come from the user or a device, so everything is escaped. */
export function watchHtml(w, canRemove = true) {
  return `<div class="watch ${esc(w.state)}" data-ip="${esc(w.ip)}">
    <div class="wh"><b>${esc(w.label || w.ip)}</b><span class="addr">${esc(w.ip)}</span><span class="wdot">${statusChip(w.state)}</span></div>
    <div class="layers">${layerChips(w)}</div>
    <p class="diag">${esc(w.diagnosis)}</p>
    <div class="foot">${historyStrip(w.history)}<span>${w.since_ms ? "since " + esc(fmtTime(w.since_ms)) : ""}</span>
      ${canRemove ? `<button type="button" class="small" data-unwatch="${esc(w.ip)}">Remove</button>` : ""}</div>
  </div>`;
}

/** Status rows for every watch; one that has no status yet (for example without a health plugin) reads as Checking. */
export function watchRows(state) {
  const have = new Map((state.watch_status || []).map((w) => [w.ip, w]));
  const rows = [...have.values()];
  for (const w of state.watches || []) {
    if (!have.has(w.ip)) {
      rows.push({
        ip: w.ip,
        label: w.label,
        ports: w.ports,
        state: "pending",
        since_ms: null,
        l2: null,
        mac: null,
        rtt_ms: null,
        port_state: {},
        diagnosis: "",
        history: [],
      });
    }
  }
  return rows;
}

/** The message under the add form when adding fails. */
export function addErrorText(err) {
  const msg = (err && err.message) || "failed";
  return err && err.status === 422 ? `Couldn't add that: ${msg}. Format: IP[:port,port][=label]` : msg;
}

const canManage = (ctx) => !ctx.auth || ctx.auth.can("core.watches");

const built = new WeakMap(); // card body -> {note, list, err, last}

function build(el, ctx) {
  el.innerHTML = `<p class="note err" data-note hidden></p>
    <div class="watches" data-list></div>
    <form class="addwatch" autocomplete="off">
      <input type="text" name="spec" placeholder="${esc(WATCH_PLACEHOLDER)}" aria-label="Host to watch" spellcheck="false">
      <button type="submit" class="primary">Watch host</button>
    </form>
    <p class="err" role="status" data-err></p>`;
  const parts = {
    note: el.querySelector("[data-note]"),
    list: el.querySelector("[data-list]"),
    err: el.querySelector("[data-err]"),
    last: null,
  };
  const form = el.querySelector("form");
  form.hidden = !canManage(ctx);
  const input = form.querySelector("input");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const spec = input.value.trim();
    if (!spec) return;
    parts.err.textContent = "";
    try {
      await apiSend("POST", "/api/v1/watches", { spec });
      input.value = "";
      ctx.refresh();
    } catch (err) {
      parts.err.textContent = addErrorText(err);
    }
  });
  parts.list.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-unwatch]");
    if (!b) return;
    b.disabled = true;
    parts.err.textContent = "";
    try {
      await apiSend("DELETE", `/api/v1/watches/${encodeURIComponent(b.dataset.unwatch)}`);
      ctx.refresh();
    } catch (err) {
      b.disabled = false;
      parts.err.textContent = err.message || "Could not remove the watch";
    }
  });
  return parts;
}

/** Draw the card body. The add form is built once and kept; only the list is redrawn. */
export function drawWatches(el, state, ctx) {
  let parts = built.get(el);
  if (!parts) {
    parts = build(el, ctx);
    built.set(el, parts);
  }
  const noHealth = !(state.capabilities || []).includes("health");
  parts.note.hidden = !noHealth;
  parts.note.textContent = noHealth ? WATCHES_NO_HEALTH : "";
  const rows = watchRows(state);
  const html = rows.length ? rows.map((w) => watchHtml(w, canManage(ctx))).join("") : `<div class="empty">${esc(WATCHES_EMPTY)}</div>`;
  if (html !== parts.last) {
    parts.last = html;
    parts.list.innerHTML = html;
  }
}
