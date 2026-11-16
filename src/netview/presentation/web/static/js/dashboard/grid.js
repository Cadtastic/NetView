// The persistent dashboard grid. Every runtime key gets ONE element for its whole life: regrouping, re-ordering
// and toggling edit mode only MOVE existing nodes, so a chart, an open <details> or a half-typed form survives.
//
//   createDashboardGrid(doc, container, opts?) -> { nodes, update(entries, state, view) }
//   entries: [{ item, spec }]   (item from layout.js itemFromSpec)
//   view:    { groups: [{ name, items }], editing, layout }
//   opts:    { collapsed: Set of group names, onToggle(name, collapsed) }
import { esc } from "../util.js";
import { spanOf, emptyLayout } from "./layout.js";

function make(doc, tag, className, text) {
  const e = doc.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = text;
  return e;
}

// Put `desired` at the start of `parent`'s children, in order, touching the DOM only where a position differs.
function place(parent, desired) {
  desired.forEach((el, i) => {
    const current = parent.children[i];
    if (current !== el) parent.insertBefore(el, current || null);
  });
}

export function createDashboardGrid(doc, container, opts = {}) {
  const nodes = new Map(); // runtimeKey -> {el, body, error, item, spec, html}
  const groups = new Map(); // name -> {section, head, grid, count, name}
  const collapsed = opts.collapsed || new Set();
  let lastEditing = null;

  function createNode(item, spec) {
    let node;
    if (item.kind === "tile") {
      const el = make(doc, "div", "tile dash-item");
      el.setAttribute("data-plugin", spec.pluginId);
      el.setAttribute("data-tile", spec.id);
      node = { el, body: el, error: null, item, spec, html: null };
    } else {
      const el = make(doc, "section", "card dash-item");
      el.setAttribute("data-plugin", spec.pluginId);
      el.setAttribute("data-card", item.runtimeKey);
      if (spec.title) el.appendChild(make(doc, "h2", "", spec.title));
      if (spec.sub) el.appendChild(make(doc, "p", "sub", spec.sub));
      const error = make(doc, "p", "err hide");
      const body = make(doc, "div", "card-body");
      el.appendChild(error);
      el.appendChild(body);
      node = { el, body, error, item, spec, html: null };
    }
    if (item.layoutKey) node.el.setAttribute("data-layout-key", item.layoutKey);
    if (item.fixed) node.el.setAttribute("data-fixed", "");
    return node;
  }

  function classes(node, view) {
    const base = node.item.kind === "tile" ? "tile" : "card";
    const next = `${base} dash-item col-${spanOf(node.item, view.layout || emptyLayout())}`;
    if (node.el.className !== next) node.el.className = next;
  }

  function drawTile(node, state) {
    const { spec, el } = node;
    let html;
    try {
      html = spec.render(state) || "";
    } catch (e) {
      console.error(`Plugin "${spec.pluginId}" dashboard tile "${spec.id}" failed`, e);
      html = `<div class="k">${esc(spec.pluginDisplayName || spec.pluginId)}</div><div class="s err">${esc(e && e.message ? e.message : e)}</div>`;
    }
    if (html !== node.html) {
      node.html = html;
      el.innerHTML = html;
    }
    const hide = html === ""; // an empty render hides the tile; it keeps its slot
    if (el.hidden !== hide) el.hidden = hide;
  }

  function drawCard(node, state) {
    const { spec, body, error } = node;
    try {
      if (typeof spec.draw === "function") spec.draw(body, state);
      else body.innerHTML = spec.render(state);
      if (error.className !== "err hide") error.className = "err hide";
      if (error.textContent !== "") error.textContent = "";
    } catch (e) {
      console.error(`Plugin "${spec.pluginId}" dashboard card "${spec.id}" failed`, e);
      error.className = "err";
      error.textContent = `This card failed: ${e && e.message ? e.message : e}`;
    }
  }

  function setCollapsed(group, on) {
    group.section.className = on ? "dash-group collapsed" : "dash-group";
    if (group.head) group.head.setAttribute("aria-expanded", on ? "false" : "true");
  }

  function ensureGroup(name) {
    let group = groups.get(name);
    if (group) return group;
    const section = make(doc, "section", "dash-group");
    group = { name, section, head: null, grid: make(doc, "div", "dash-grid"), count: null };
    if (name !== "") {
      const head = make(doc, "button", "dash-group-head");
      head.setAttribute("type", "button");
      head.appendChild(make(doc, "span", "dash-chevron"));
      head.appendChild(make(doc, "span", "dash-group-name", name));
      group.count = make(doc, "span", "dash-group-count");
      head.appendChild(group.count);
      head.addEventListener("click", () => {
        const on = !collapsed.has(name);
        if (on) collapsed.add(name);
        else collapsed.delete(name);
        setCollapsed(group, on);
        if (opts.onToggle) opts.onToggle(name, on);
      });
      group.head = head;
      section.appendChild(head);
    }
    section.appendChild(group.grid);
    setCollapsed(group, name !== "" && collapsed.has(name));
    groups.set(name, group);
    return group;
  }

  return {
    nodes,
    update(entries, state, view) {
      const live = new Set();
      for (const { item, spec } of entries) {
        live.add(item.runtimeKey);
        let node = nodes.get(item.runtimeKey);
        if (!node) {
          node = createNode(item, spec);
          nodes.set(item.runtimeKey, node);
        }
        node.item = item;
        node.spec = spec;
      }
      for (const [key, node] of [...nodes]) {
        if (!live.has(key)) {
          node.el.remove();
          nodes.delete(key);
        }
      }

      const placed = new Set();
      const sections = [];
      for (const { name, items } of view.groups) {
        const group = ensureGroup(name);
        sections.push(group.section);
        const els = [];
        for (const item of items) {
          const node = nodes.get(item.runtimeKey);
          if (!node) continue;
          classes(node, view);
          els.push(node.el);
          placed.add(item.runtimeKey);
        }
        place(group.grid, els);
        if (group.count) {
          const text = String(els.length);
          if (group.count.textContent !== text) group.count.textContent = text;
        }
      }
      place(container, sections);

      // an item the layout hides stays alive (its state persists) but leaves the page
      for (const [key, node] of nodes) {
        if (!placed.has(key) && node.el.parentNode) node.el.remove();
      }
      const wanted = new Set(view.groups.map((g) => g.name));
      for (const [name, group] of [...groups]) {
        if (!wanted.has(name)) {
          group.section.remove();
          groups.delete(name);
        }
      }

      const editing = !!view.editing;
      if (editing !== lastEditing) {
        lastEditing = editing;
        container.classList.toggle("dash-editing", editing);
      }

      for (const node of nodes.values()) {
        if (node.item.kind === "tile") drawTile(node, state);
        else drawCard(node, state);
      }
    },
  };
}
