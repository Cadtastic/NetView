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
import { createDashboardGrid } from "../dashboard/grid.js";
import { itemFromSpec, emptyLayout, applyLayout, groupItems } from "../dashboard/layout.js";
import { getLayout, saveLayout, resetLayout, saveDefault } from "../dashboard/api.js";
import { createCustomizer, bindEditor } from "../dashboard/customize.js";
import { toast } from "../toast.js";

const DEFAULT_CARD_ORDER = 30;
const DEFAULT_TILE_ORDER = 50;

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

/** The core cards, drawn by the core itself. */
export function coreCardSpecs(ctx) {
  return [
    { pluginId: "core", id: "watches", title: "Watches", sub: WATCHES_SUB, order: 10, span: "full", draw: (el, state) => drawWatches(el, state, ctx) },
    { pluginId: "core", id: "events", title: "Events", sub: EVENTS_SUB, order: 60, span: "half", draw: (el, state) => drawEvents(el, state) },
  ];
}

let defaultEditRequested = false;

/** Ask the next mountDashboard to open in "edit the default layout" mode (Admin > Default dashboard > Edit). */
export function requestDefaultEdit() {
  defaultEditRequested = true;
}

/** Read and clear the request made by requestDefaultEdit. */
export function takeDefaultEditRequest() {
  const asked = defaultEditRequested;
  defaultEditRequested = false;
  return asked;
}

const COLLAPSED_KEY = "netview.dashboard.collapsed";

function loadCollapsed() {
  try {
    const raw = JSON.parse(window.localStorage.getItem(COLLAPSED_KEY) || "[]");
    return new Set(Array.isArray(raw) ? raw.filter((n) => typeof n === "string") : []);
  } catch {
    return new Set();
  }
}

function saveCollapsed(set) {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...set]));
  } catch {
    /* storage unavailable: the collapse just won't be remembered */
  }
}

export function mountDashboard(el, ctx) {
  let pendingDefaultEdit = takeDefaultEditRequest() && ctx.auth.can("core.system");
  const top = document.createElement("div");
  const root = document.createElement("div");
  root.className = "dash";
  const tray = document.createElement("div");
  const live = document.createElement("div");
  live.className = "sr-only";
  live.setAttribute("aria-live", "polite");
  el.append(top, root, tray, live);
  const collapsed = loadCollapsed();
  const grid = createDashboardGrid(document, root, { collapsed, onToggle: () => saveCollapsed(collapsed) });
  let layout = null; // null until the saved layout has loaded (or failed to)
  let defaultLayout = null; // the `default` of the last getLayout() response
  let lastState = null;
  let destroyed = false;

  function coreTileSpecs() {
    return coreTiles({ devices: [], jobs: [] }).map((t) => ({
      pluginId: "core",
      id: t.id,
      title: t.k,
      order: t.order,
      render: (state) => {
        const c = coreTiles(state).find((x) => x.id === t.id);
        return `<div class="k">${esc(c.k)}</div><div class="v">${c.v}</div><div class="s">${c.s ? esc(c.s) : "&nbsp;"}</div>`;
      },
    }));
  }

  function failedSpecs() {
    const plugins = ctx.getPlugins ? ctx.getPlugins() : [];
    return Object.entries(ctx.host.errors).map(([id, msg]) => {
      const p = plugins.find((x) => x.id === id) || {};
      return {
        pluginId: id,
        id: "failed",
        failed: true,
        pluginDisplayName: p.display_name || id,
        pluginSource: p.source,
        pluginType: p.plugin_type,
        title: p.display_name || id,
        order: 90,
        span: "full",
        render: () => `<p class="err">Its interface failed to load: ${esc(msg)}</p>`,
      };
    });
  }

  function entries() {
    const tiles = orderTiles([...coreTileSpecs(), ...ctx.host.get("dashboard.tile")]);
    const cards = orderCards([...coreCardSpecs(ctx), ...ctx.host.get("dashboard.card"), ...failedSpecs()]);
    return [...tiles.map((spec) => ({ item: itemFromSpec(spec, "tile"), spec })), ...cards.map((spec) => ({ item: itemFromSpec(spec, "card"), spec }))];
  }

  function currentItems() {
    return entries().map((e) => e.item);
  }

  function labelOf(item) {
    const node = grid.nodes.get(item.runtimeKey);
    const spec = node && node.spec;
    if (!spec) return item.layoutKey || item.runtimeKey;
    return spec.title || (spec.pluginDisplayName ? `${spec.pluginDisplayName}: ${spec.id}` : spec.id);
  }

  const auth = { can: (id) => ctx.auth.can(id) };
  const customizer = createCustomizer({
    getItems: currentItems,
    getLayout: () => layout,
    setLayout: (l) => {
      layout = l;
    },
    getDefault: () => defaultLayout,
    redraw: () => render(lastState),
    auth,
    api: {
      saveLayout,
      resetLayout,
      saveDefault: async (l, clearMine) => {
        const out = await saveDefault(l, clearMine);
        defaultLayout = l;
        return out;
      },
    },
    toast,
    label: labelOf,
    announce: (text) => editor.announce(text),
  });
  const editor = bindEditor({
    host: el,
    top,
    root,
    tray,
    live,
    grid,
    customizer,
    getItems: currentItems,
    getLayout: () => layout,
    canCustomize: auth.can("core.dashboard"),
    canDefault: auth.can("core.system"),
    toast,
    label: labelOf,
  });

  function render(state) {
    lastState = state;
    if (destroyed || !layout || !state) return;
    if (pendingDefaultEdit) {
      pendingDefaultEdit = false;
      customizer.start({ editingDefault: true }); // redraws through render()
      if (customizer.editing) return;
    }
    const list = entries();
    const { visible } = applyLayout(list.map((e) => e.item), layout);
    grid.update(list, state, { groups: groupItems(visible, layout.group), editing: customizer.editing, layout });
    editor.sync();
  }

  getLayout()
    .then((r) => {
      layout = r && r.layout ? r.layout : emptyLayout();
      defaultLayout = r && r.default ? r.default : null;
    })
    .catch(() => {
      layout = emptyLayout();
    })
    .then(() => {
      if (lastState) render(lastState);
    });

  return {
    update: render,
    destroy() {
      destroyed = true; // leaving while editing just discards the changes
      editor.destroy();
      root.remove();
    },
  };
}
