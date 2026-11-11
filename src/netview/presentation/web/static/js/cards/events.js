// Core Events card: what changed on the network, newest first.
import { esc, fmtTime } from "../util.js";

export const EVENTS_SUB = "New devices, devices leaving and returning, address changes, watch changes and inspections.";
export const EVENTS_EMPTY = "Nothing yet. Events start after the first sweep.";
const MAX_ROWS = 200;

const KIND_LABEL = {
  new: "New",
  moved: "Moved",
  online: "Online",
  offline: "Offline",
  conflict: "Conflict",
  name: "Name",
  nickname: "Nickname",
  forgotten: "Forgotten",
  type: "Type",
  watch: "Watch",
  plugin: "Plugin",
  inspected: "Inspected",
};
const KIND_TONE = { new: "accent", online: "ok", offline: "bad", conflict: "bad", watch: "warn", inspected: "accent" };

const capital = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");

/** The events list as HTML, newest first. */
export function eventsHtml(events) {
  const rows = [...(events || [])].sort((a, b) => b.t_ms - a.t_ms).slice(0, MAX_ROWS);
  if (!rows.length) return `<div class="empty">${esc(EVENTS_EMPTY)}</div>`;
  const items = rows
    .map(
      (e) =>
        `<li><time>${esc(fmtTime(e.t_ms))}</time><span class="chip kd ${esc(KIND_TONE[e.kind] || "")}">${esc(KIND_LABEL[e.kind] || capital(e.kind))}</span><span class="etext">${esc(e.text)}</span></li>`,
    )
    .join("");
  return `<ul class="events">${items}</ul>`;
}

const last = new WeakMap();

/** Draw the card body. The list is only rebuilt when it changed, and keeps its scroll position. */
export function drawEvents(el, state) {
  const html = eventsHtml(state.events);
  if (last.get(el) === html) return;
  last.set(el, html);
  const old = el.querySelector(".events");
  const scroll = old ? old.scrollTop : 0;
  el.innerHTML = html;
  const list = el.querySelector(".events");
  if (list && scroll) list.scrollTop = scroll;
}
