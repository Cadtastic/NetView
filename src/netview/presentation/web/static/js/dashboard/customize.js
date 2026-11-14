// Customize mode for the dashboard.
//
//   createCustomizer(opts)  the edit-session model: layout changes, save, reset, cancel. No DOM.
//   toolbarHtml / bannerText  the fixed toolbar and banner copy (pure).
//   bindEditor(opts)        the DOM side: tools on each item, drag and drop, keyboard, the hidden tray.
//
// Nothing here touches `document` or `window` at import time. The editor only adds and removes attributes,
// classes and small tool elements on the grid's persistent nodes, so live charts and forms survive editing.
import { esc } from "../util.js";
import { eye, eyeOff, arrowsHorizontal, grip, info, layoutDashboard } from "../icons.js";
import { emptyLayout, applyLayout, groupItems, spanOf, SPAN_COLS, nextSpan, moveKey, nudge, dropSpot, toSaved, saveAction } from "./layout.js";

export const BANNER = "Drag cards to move them. Changes are only yours, and only kept when you save.";
export const BANNER_DEFAULT = "Editing the default layout for everyone. Users who saved their own layout keep it until they reset.";
export const TOAST_SAVED = "Saved to your profile. Only you see this layout.";
export const TOAST_DEFAULT = "Saved as the default layout for everyone";
export const TOAST_DISCARDED = "Changes discarded";
export const TOAST_GROUP = "Cards stay in their own group";

export const bannerText = (editingDefault) => (editingDefault ? BANNER_DEFAULT : BANNER);

const GROUP_OPTIONS = [
  ["none", "None"],
  ["plugin", "Plugin"],
  ["plugin_type", "Plugin type"],
];

/** The toolbar above the dashboard. `group` selects the current Group by option. */
export function toolbarHtml({ editing, editingDefault, canCustomize, canDefault, group = "none" }) {
  if (!editing) {
    if (!canCustomize) return "";
    return `<div class="dash-toolbar dash-toolbar-end"><button type="button" data-act="customize">${layoutDashboard}Customize</button></div>`;
  }
  const options = GROUP_OPTIONS.map(([value, label]) => `<option value="${value}"${value === group ? " selected" : ""}>${label}</option>`).join("");
  const parts = [`<label class="dash-groupby">Group by <select data-act="group">${options}</select></label>`, '<span class="spacer"></span>'];
  if (editingDefault) {
    parts.push('<button type="button" class="primary" data-act="default">Save as default for everyone</button>');
  } else {
    parts.push('<button type="button" class="primary" data-act="save">Save to my profile</button>');
    if (canDefault) parts.push('<button type="button" data-act="default">Save as default for everyone</button>');
    parts.push('<button type="button" data-act="reset">Reset to default</button>');
  }
  parts.push('<button type="button" data-act="cancel">Cancel</button>');
  return `<div class="dash-toolbar">${parts.join("")}</div>`;
}

const spanName = (cols) => Object.keys(SPAN_COLS).find((k) => SPAN_COLS[k] === cols) || "half";

export function createCustomizer({ getItems, getLayout, setLayout, getDefault, redraw, auth, api, toast, label, announce }) {
  let editing = false;
  let editingDefault = false;
  let backup = null;
  let resetPressed = false;
  let edited = false;
  let busy = false;
  const titleOf = (item) => (label ? label(item) : item.layoutKey);

  function change(next) {
    edited = true;
    setLayout(next);
    redraw();
  }
  const current = () => getLayout() || emptyLayout();

  function leave() {
    editing = false;
    editingDefault = false;
    backup = null;
    resetPressed = false;
    edited = false;
    redraw();
  }

  async function commit(action) {
    if (!editing || busy) return;
    busy = true;
    try {
      const own = backup;
      if (action === "put") {
        await api.saveLayout(toSaved(getItems(), current()));
        toast(TOAST_SAVED);
      } else if (action === "delete") {
        await api.resetLayout();
        toast(TOAST_SAVED);
      } else {
        await api.saveDefault(toSaved(getItems(), current()), !editingDefault);
        toast(TOAST_DEFAULT);
        if (editingDefault) setLayout(own); // editing the default never touches my own layout
      }
      leave();
    } catch (e) {
      toast(e && e.message ? e.message : "Could not save the layout", "bad");
    } finally {
      busy = false;
    }
  }

  return {
    get editing() {
      return editing;
    },
    get editingDefault() {
      return editingDefault;
    },
    start({ editingDefault: asDefault = false } = {}) {
      if (editing) return;
      if (asDefault ? !auth.can("core.system") : !auth.can("core.dashboard")) return;
      backup = getLayout();
      editing = true;
      editingDefault = !!asDefault;
      resetPressed = false;
      edited = false;
      const base = asDefault ? (getDefault && getDefault()) || emptyLayout() : current();
      setLayout(toSaved(getItems(), base)); // a complete order, so every move has a target
      redraw();
    },
    cancel() {
      if (!editing) return;
      setLayout(backup);
      leave();
      toast(TOAST_DISCARDED);
    },
    save() {
      return commit(saveAction({ editingDefault, resetPressed, edited }));
    },
    saveDefault() {
      return commit("default");
    },
    reset() {
      if (!editing || editingDefault) return;
      setLayout(toSaved(getItems(), (getDefault && getDefault()) || emptyLayout()));
      resetPressed = true;
      edited = false;
      redraw();
    },
    setGroup(group) {
      if (!editing) return;
      change({ ...current(), group });
    },
    hide(key) {
      const l = current();
      if (!editing || l.hidden.includes(key)) return;
      change({ ...l, hidden: [...l.hidden, key] });
    },
    show(key) {
      const l = current();
      if (!editing || !l.hidden.includes(key)) return;
      change({ ...l, hidden: l.hidden.filter((k) => k !== key) });
    },
    widen(key) {
      const item = getItems().find((i) => i.layoutKey === key);
      if (!editing || !item || item.kind !== "card") return;
      const l = current();
      change({ ...l, spans: { ...l.spans, [key]: nextSpan(spanName(spanOf(item, l))) } });
    },
    move(key, targetKey, after) {
      if (!editing) return;
      const l = current();
      change({ ...l, order: moveKey(l.order, key, targetKey, after) });
    },
    nudge(key, delta) {
      if (!editing) return;
      const items = getItems();
      const l = current();
      const groups = groupItems(applyLayout(items, l).visible, l.group);
      const group = groups.find((g) => g.items.some((i) => i.layoutKey === key));
      if (!group) return;
      const keys = group.items.filter((i) => !i.fixed && i.layoutKey).map((i) => i.layoutKey);
      const order = nudge(l.order, key, delta, keys);
      if (order.join("|") === l.order.join("|")) return;
      change({ ...l, order });
      const after = groupItems(applyLayout(items, current()).visible, l.group).find((g) => g.items.some((i) => i.layoutKey === key));
      const list = after.items.filter((i) => !i.fixed && i.layoutKey);
      const at = list.findIndex((i) => i.layoutKey === key) + 1;
      const item = items.find((i) => i.layoutKey === key);
      if (announce) announce(`Moved ${titleOf(item)} to position ${at} of ${list.length}`);
    },
  };
}

// ---- the DOM side --------------------------------------------------------------------------------

const BAR = ["dash-before", "dash-after"];

/**
 * Wire edit mode to the page. `host` receives every event (delegated); `top`, `tray` and `live` are the toolbar,
 * hidden-cards and announcement containers. Call `sync()` after every grid update and every customizer change.
 */
export function bindEditor({ host, top, root, tray, live, grid, customizer, getItems, getLayout, canCustomize, canDefault, toast, label }) {
  let toolbarSig = null;
  let traySig = null;
  let dragKey = null;
  let dragGrid = null;
  let refused = false;
  const offs = [];
  const on = (type, fn) => {
    host.addEventListener(type, fn);
    offs.push(() => host.removeEventListener(type, fn));
  };

  const labelOf = (item) => (label ? label(item) : item.layoutKey);
  const nodeByKey = (key) => [...grid.nodes.values()].find((n) => n.item.layoutKey === key);

  function toolsFor(node) {
    const title = esc(labelOf(node.item));
    const width =
      node.item.kind === "card"
        ? `<button type="button" class="icon small" data-tool="width" title="Width: third, half, full" aria-label="Change width of ${title}">${arrowsHorizontal}</button>`
        : "";
    return `${width}<button type="button" class="icon small" data-tool="hide" title="Hide" aria-label="Hide ${title}">${eyeOff}</button>`;
  }

  function decorate(node, on) {
    const el = node.el;
    const tools = el.querySelector(":scope > .dash-tools");
    const gripEl = el.querySelector(":scope > .dash-grip");
    if (!on) {
      if (tools) tools.remove();
      if (gripEl) gripEl.remove();
      if (el.getAttribute("draggable")) el.removeAttribute("draggable");
      if (el.getAttribute("tabindex")) el.removeAttribute("tabindex");
      return;
    }
    if (el.getAttribute("draggable") !== "true") el.setAttribute("draggable", "true");
    if (el.getAttribute("tabindex") !== "0") el.setAttribute("tabindex", "0");
    if (!gripEl) {
      const g = el.ownerDocument.createElement("span");
      g.className = "dash-grip";
      g.innerHTML = grip;
      el.appendChild(g);
    }
    if (!tools) {
      const t = el.ownerDocument.createElement("div");
      t.className = "dash-tools";
      t.innerHTML = toolsFor(node);
      el.appendChild(t);
    }
  }

  function sync() {
    const editing = customizer.editing;
    const layout = getLayout();
    const group = layout ? layout.group : "none";
    const sig = layout ? [editing, customizer.editingDefault, group, canCustomize, canDefault].join("|") : "";
    if (sig !== toolbarSig) {
      toolbarSig = sig;
      top.innerHTML = layout
        ? toolbarHtml({ editing, editingDefault: customizer.editingDefault, canCustomize, canDefault, group }) +
          (editing ? `<div class="dash-banner" role="note">${info}<span>${esc(bannerText(customizer.editingDefault))}</span></div>` : "")
        : "";
    }
    for (const node of grid.nodes.values()) decorate(node, editing && !node.item.fixed && !!node.item.layoutKey && !!node.el.parentNode);

    if (!editing || !layout) {
      if (traySig !== "") tray.innerHTML = "";
      traySig = "";
      return;
    }
    const hidden = applyLayout(getItems(), layout).hidden;
    const next = hidden.map((i) => `${i.layoutKey}\u0000${labelOf(i)}`).join("\u0001");
    if (next === traySig) return;
    traySig = next;
    const chips = hidden.length
      ? hidden.map((i) => `<button type="button" class="dash-chip" data-show="${esc(i.layoutKey)}">${eye}${esc(labelOf(i))}</button>`).join("")
      : '<span class="note">None. Hide a card and it waits here.</span>';
    tray.innerHTML = `<div class="dash-tray"><b>Hidden cards</b><div class="dash-chips">${chips}</div></div>`;
  }

  const itemOf = (target) => (target && target.closest ? target.closest(".dash-item[data-layout-key]") : null);

  function clearBars() {
    for (const cls of BAR) for (const e of root.querySelectorAll(`.${cls}`)) e.classList.remove(cls);
  }

  function spotFor(gridEl, e) {
    const rects = [];
    for (const el of gridEl.children) {
      const key = el.getAttribute("data-layout-key");
      if (!key || key === dragKey || el.hasAttribute("data-fixed") || el.hidden) continue;
      const r = el.getBoundingClientRect();
      rects.push({ key, left: r.left, right: r.right, top: r.top, bottom: r.bottom });
    }
    return dropSpot(rects, e.clientX, e.clientY);
  }

  on("click", (e) => {
    const t = e.target;
    const act = t.closest && t.closest("[data-act]");
    if (act) {
      const a = act.getAttribute("data-act");
      if (a === "customize") customizer.start({ editingDefault: false });
      else if (a === "cancel") customizer.cancel();
      else if (a === "save") customizer.save();
      else if (a === "default") customizer.saveDefault();
      else if (a === "reset") customizer.reset();
      return;
    }
    const chip = t.closest && t.closest("[data-show]");
    if (chip) {
      customizer.show(chip.getAttribute("data-show"));
      return;
    }
    const tool = t.closest && t.closest("[data-tool]");
    const item = itemOf(tool);
    if (tool && item) {
      const key = item.getAttribute("data-layout-key");
      if (tool.getAttribute("data-tool") === "hide") customizer.hide(key);
      else customizer.widen(key);
    }
  });

  on("change", (e) => {
    const t = e.target;
    if (t && t.getAttribute && t.getAttribute("data-act") === "group") customizer.setGroup(t.value);
  });

  on("dragstart", (e) => {
    const item = customizer.editing ? itemOf(e.target) : null;
    if (!item || item.hasAttribute("data-fixed") || e.target !== item) return;
    dragKey = item.getAttribute("data-layout-key");
    dragGrid = item.parentNode;
    refused = false;
    if (e.dataTransfer) {
      e.dataTransfer.setData("text/plain", dragKey);
      e.dataTransfer.effectAllowed = "move";
    }
    item.classList.add("dash-dragging");
  });

  on("dragover", (e) => {
    if (!dragKey) return;
    const gridEl = e.target.closest ? e.target.closest(".dash-grid") : null;
    if (!gridEl) return;
    if (gridEl !== dragGrid) {
      clearBars();
      if (!refused) {
        refused = true;
        toast(TOAST_GROUP, "warn");
      }
      return; // no preventDefault: the drop is refused
    }
    const spot = spotFor(gridEl, e);
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    clearBars();
    if (spot) {
      const node = nodeByKey(spot.key);
      if (node) node.el.classList.add(spot.after ? "dash-after" : "dash-before");
    }
  });

  on("drop", (e) => {
    if (!dragKey) return;
    const gridEl = e.target.closest ? e.target.closest(".dash-grid") : null;
    if (!gridEl || gridEl !== dragGrid) return;
    e.preventDefault();
    const spot = spotFor(gridEl, e);
    const key = dragKey;
    clearBars();
    if (spot) customizer.move(key, spot.key, spot.after);
  });

  on("dragend", () => {
    clearBars();
    for (const e of root.querySelectorAll(".dash-dragging")) e.classList.remove("dash-dragging");
    dragKey = null;
    dragGrid = null;
    refused = false;
  });

  on("keydown", (e) => {
    if (!customizer.editing || !e.ctrlKey || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    const item = itemOf(e.target);
    if (!item || item !== e.target) return; // leave Ctrl+Arrow alone inside inputs and charts
    e.preventDefault();
    const key = item.getAttribute("data-layout-key");
    customizer.nudge(key, e.key === "ArrowLeft" ? -1 : 1);
    const node = nodeByKey(key);
    if (node) node.el.focus(); // moving a node in the DOM drops focus
  });

  return {
    sync,
    announce: (text) => (live.textContent = text),
    destroy: () => offs.forEach((off) => off()),
  };
}
