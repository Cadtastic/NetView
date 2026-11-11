// Dashboard: core tiles plus every dashboard.tile and dashboard.card a plugin contributes.
//
// Card spec:  {id, title?, sub?, order = 30, span = "half", render(state) -> html | draw(el, state)}
// Tile spec:  {id, order = 50, render(state) -> html}  (an empty string hides the tile)
// Cards are persistent: one <section class="card"> per spec is created once and never rebuilt, so a chart,
// an open details element or a half-typed form survives every state update. A `draw` spec owns the inside
// of its body element; a `render` spec has that body's innerHTML replaced each time.
import { esc, fmtAgo } from "../util.js";
import { drawEvents, EVENTS_SUB } from "../cards/events.js";
import { drawWatches, WATCHES_SUB } from "../cards/watches.js";

const DEFAULT_CARD_ORDER = 30;
const DEFAULT_TILE_ORDER = 50;
const SPAN_CLASS = { full: "span-6", half: "span-3", third: "span-2" };

/** The core summary tiles (order 0 to 3). `now` is injectable for tests. */
export function coreTiles(state, now = Date.now()) {
  const counts = { online: 0, quiet: 0, offline: 0 };
  for (const d of state.devices) if (d.status in counts) counts[d.status]++;
  const sweep = state.jobs.find((j) => j.owner === "core" && j.name === "scan");
  return [
    { id: "online", order: 0, k: "Devices online", v: `${counts.online}<small>/ ${state.devices.length}</small>`, s: "online / total" },
    { id: "quiet", order: 1, k: "Quiet", v: String(counts.quiet), s: "answer ARP, not ping" },
    { id: "offline", order: 2, k: "Offline", v: String(counts.offline), s: "not seen recently" },
    {
      id: "sweep",
      order: 3,
      k: "Last sweep",
      v: sweep && sweep.last_finished_ms ? esc(fmtAgo(sweep.last_finished_ms, now)) : "–",
      s: sweep && sweep.last_ok === false ? esc(sweep.last_error || "failed") : "",
    },
  ];
}

/** A stable sort by `order`, then by registration order. */
export function orderBy(specs, fallback) {
  return specs
    .map((spec, i) => ({ spec, i }))
    .sort((a, b) => (a.spec.order ?? fallback) - (b.spec.order ?? fallback) || a.i - b.i)
    .map((x) => x.spec);
}

/** Cards in display order: `order` (default 30), then registration order. */
export const orderCards = (specs) => orderBy(specs, DEFAULT_CARD_ORDER);

/** Tiles in display order: `order` (default 50), then registration order. */
export const orderTiles = (specs) => orderBy(specs, DEFAULT_TILE_ORDER);

/** The grid class for a card span ("full", "half" or "third"); anything else is half. */
export const spanClass = (span) => SPAN_CLASS[span] || SPAN_CLASS.half;

export const cardKey = (spec) => `${spec.pluginId}.${spec.id}`;

function make(doc, tag, className, text) {
  const e = doc.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = text;
  return e;
}

/**
 * The persistent card grid. `update(specs, state)` creates a card for each new spec, keeps them in order,
 * and draws each one. A spec that throws shows its error inside its own card and nothing else changes.
 */
export function createCardGrid(doc, container) {
  const cards = new Map(); // key -> {section, body, error, spec}
  let lastOrder = [];

  function ensure(spec) {
    const key = cardKey(spec);
    let card = cards.get(key);
    if (!card) {
      const section = make(doc, "section", `card ${spanClass(spec.span)}`);
      section.setAttribute("data-plugin", spec.pluginId);
      section.setAttribute("data-card", key);
      if (spec.title) section.appendChild(make(doc, "h2", "", spec.title));
      if (spec.sub) section.appendChild(make(doc, "p", "sub", spec.sub));
      const error = make(doc, "p", "err hide");
      const body = make(doc, "div", "card-body");
      section.appendChild(error);
      section.appendChild(body);
      card = { section, body, error, spec };
      cards.set(key, card);
    }
    card.spec = spec;
    return card;
  }

  return {
    cards,
    update(specs, state) {
      const ordered = orderCards(specs);
      const present = ordered.map((s) => ensure(s));
      const keys = ordered.map(cardKey);
      for (const [key, card] of [...cards]) {
        if (!keys.includes(key)) {
          card.section.remove();
          cards.delete(key);
        }
      }
      if (keys.length !== lastOrder.length || keys.some((k, i) => k !== lastOrder[i])) {
        for (const card of present) container.appendChild(card.section); // appending an attached node moves it
        lastOrder = keys;
      }
      for (const card of present) {
        const { spec, body, error } = card;
        try {
          if (typeof spec.draw === "function") spec.draw(body, state);
          else body.innerHTML = spec.render(state);
          error.className = "err hide";
          error.textContent = "";
        } catch (e) {
          console.error(`Plugin "${spec.pluginId}" dashboard card "${spec.id}" failed`, e);
          error.className = "err";
          error.textContent = `This card failed: ${e && e.message ? e.message : e}`;
        }
      }
    },
  };
}

function safe(plugin, fn, fallback) {
  try {
    return fn();
  } catch (e) {
    console.error(`Plugin "${plugin}" dashboard slot failed`, e);
    return fallback(e);
  }
}

/** The core cards, drawn by the core itself. */
export function coreCardSpecs(ctx) {
  return [
    { pluginId: "core", id: "watches", title: "Watches", sub: WATCHES_SUB, order: 10, span: "full", draw: (el, state) => drawWatches(el, state, ctx) },
    { pluginId: "core", id: "events", title: "Events", sub: EVENTS_SUB, order: 60, span: "half", draw: (el, state) => drawEvents(el, state) },
  ];
}

export function mountDashboard(el, ctx) {
  const tilesEl = document.createElement("section");
  tilesEl.className = "tiles";
  tilesEl.setAttribute("aria-label", "Summary");
  const cardsEl = document.createElement("div");
  cardsEl.className = "cards";
  el.append(tilesEl, cardsEl);
  const grid = createCardGrid(document, cardsEl);

  function renderTiles(state) {
    const tiles = [
      ...coreTiles(state).map((t) => ({
        order: t.order,
        html: `<div class="tile" data-tile="${esc(t.id)}"><div class="k">${esc(t.k)}</div><div class="v">${t.v}</div><div class="s">${t.s ? esc(t.s) : "&nbsp;"}</div></div>`,
      })),
      ...ctx.host.get("dashboard.tile").map((spec) => ({
        order: spec.order,
        pluginId: spec.pluginId,
        html: safe(
          spec.pluginId,
          () => {
            const body = spec.render(state);
            return body ? `<div class="tile" data-plugin="${esc(spec.pluginId)}">${body}</div>` : ""; // "" hides the tile
          },
          (e) => `<div class="tile"><div class="k">${esc(spec.pluginId)}</div><div class="s err">${esc(e.message)}</div></div>`,
        ),
      })),
    ];
    tilesEl.innerHTML = orderTiles(tiles).map((t) => t.html).join("");
  }

  function failedSpecs() {
    return Object.entries(ctx.host.errors).map(([id, msg]) => ({
      pluginId: id,
      id: "failed",
      title: id,
      order: 90,
      span: "full",
      render: () => `<p class="err">Its interface failed to load: ${esc(msg)}</p>`,
    }));
  }

  function render(state) {
    renderTiles(state);
    grid.update([...coreCardSpecs(ctx), ...ctx.host.get("dashboard.card"), ...failedSpecs()], state);
  }

  return { update: render };
}
