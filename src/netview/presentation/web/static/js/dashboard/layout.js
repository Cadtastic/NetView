// Pure dashboard layout model. No DOM access: Task 9 (grid) and Task 10 (Customize) consume it.

export const KEY_RE = /^(core|[0-9a-f-]{36})\.(tile|card)\.[A-Za-z0-9_.-]{1,100}$/;
export const SPAN_COLS = { third: 4, half: 6, full: 12 };
export const TILE_COLS = 2;

export const TYPE_LABELS = {
  router: "Router",
  switch: "Switch",
  access_point: "Access point",
  firewall: "Firewall",
  modem: "Modem",
  server: "Server",
  nas: "NAS",
  computer: "Computer",
  tv: "TV",
  printer: "Printer",
  camera: "Camera",
  ups: "UPS",
  iot: "IoT",
  software: "Software",
  other: "Other",
};

export const BUILTIN_PLUGIN_GROUP = "NetView";
export const BUILTIN_TYPE_GROUP = "NetView (built in)";

const SPAN_ORDER = ["third", "half", "full"];

export function itemFromSpec(spec, kind) {
  const isCore = spec.pluginId === "core";
  const failed = !isCore && (spec.failed === true || (spec.id === "failed" && !spec.pluginGuid));
  const owner = failed ? null : isCore ? "core" : spec.pluginGuid;
  const builtin = isCore || spec.pluginSource === "builtin";
  const candidate = owner ? `${owner}.${kind}.${spec.id}` : "";
  const fixed = failed || !KEY_RE.test(candidate);
  return {
    runtimeKey: `${spec.pluginId}.${kind}.${spec.id}`,
    layoutKey: fixed ? null : candidate,
    kind,
    owner,
    groupPlugin: builtin ? BUILTIN_PLUGIN_GROUP : spec.pluginDisplayName || "Other",
    groupType: builtin ? BUILTIN_TYPE_GROUP : TYPE_LABELS[spec.pluginType] || "Other",
    defaultSpan: kind === "card" ? spec.span || null : null,
    fixed,
  };
}

export function emptyLayout() {
  return { version: 1, order: [], hidden: [], spans: {}, group: "none" };
}

function normalized(layout) {
  const l = layout || {};
  return {
    version: 1,
    order: Array.isArray(l.order) ? l.order : [],
    hidden: Array.isArray(l.hidden) ? l.hidden : [],
    spans: l.spans && typeof l.spans === "object" ? l.spans : {},
    group: l.group || "none",
  };
}

// Every item in display order, hidden ones included.
function ordered(items, layout) {
  const { order } = normalized(layout);
  const byKey = new Map();
  for (const it of items) if (!it.fixed && it.layoutKey) byKey.set(it.layoutKey, it);
  const out = [];
  const seen = new Set();
  for (const key of order) {
    const it = byKey.get(key);
    if (it && !seen.has(key)) {
      out.push(it);
      seen.add(key);
    }
  }
  for (const it of items) if (!it.fixed && !seen.has(it.layoutKey)) out.push(it);
  for (const it of items) if (it.fixed) out.push(it);
  return out;
}

export function applyLayout(items, layout) {
  const hiddenKeys = new Set(normalized(layout).hidden);
  const visible = [];
  const hidden = [];
  for (const it of ordered(items, layout)) {
    if (!it.fixed && hiddenKeys.has(it.layoutKey)) hidden.push(it);
    else visible.push(it);
  }
  return { visible, hidden };
}

export function spanOf(item, layout) {
  if (item.kind === "tile") return TILE_COLS;
  const saved = item.layoutKey ? normalized(layout).spans[item.layoutKey] : null;
  return SPAN_COLS[saved || item.defaultSpan || "half"] || SPAN_COLS.half;
}

export function groupItems(visible, group) {
  if (group !== "plugin" && group !== "plugin_type") return [{ name: "", items: [...visible] }];
  const prop = group === "plugin" ? "groupPlugin" : "groupType";
  const builtin = group === "plugin" ? BUILTIN_PLUGIN_GROUP : BUILTIN_TYPE_GROUP;
  const map = new Map();
  for (const it of visible) {
    const name = it[prop];
    if (!map.has(name)) map.set(name, []);
    map.get(name).push(it);
  }
  const groups = [...map.entries()].map(([name, list]) => ({
    name,
    items: [...list.filter((i) => !i.fixed), ...list.filter((i) => i.fixed)],
  }));
  groups.sort((a, b) => {
    if (a.name === builtin) return b.name === builtin ? 0 : -1;
    if (b.name === builtin) return 1;
    return a.name.localeCompare(b.name);
  });
  return groups;
}

export function moveKey(order, key, targetKey, after) {
  if (key === targetKey || !order.includes(targetKey)) return [...order];
  const rest = order.filter((k) => k !== key);
  const at = rest.indexOf(targetKey) + (after ? 1 : 0);
  rest.splice(at, 0, key);
  return rest;
}

export function nudge(order, key, delta, groupKeys) {
  const i = groupKeys.indexOf(key);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= groupKeys.length || delta === 0) return [...order];
  return moveKey(order, key, groupKeys[j], delta > 0);
}

export function nextSpan(span) {
  return SPAN_ORDER[(SPAN_ORDER.indexOf(span) + 1) % SPAN_ORDER.length];
}

export function dropSpot(rects, x, y) {
  if (!rects.length) return null;
  for (const r of rects) {
    if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) {
      return { key: r.key, after: x > r.left + (r.right - r.left) / 2 };
    }
  }
  const row = rects.filter((r) => y >= r.top - 6 && y <= r.bottom + 6);
  if (row.length) {
    const next = row.find((r) => r.left > x);
    if (next) return { key: next.key, after: false };
    return { key: row[row.length - 1].key, after: true };
  }
  return { key: rects[rects.length - 1].key, after: true };
}

export function toSaved(items, layout) {
  const l = normalized(layout);
  const present = ordered(items, layout).filter((i) => !i.fixed);
  const keys = new Set(present.map((i) => i.layoutKey));
  const spans = {};
  for (const [k, v] of Object.entries(l.spans)) if (keys.has(k)) spans[k] = v;
  return {
    version: 1,
    order: present.map((i) => i.layoutKey),
    hidden: l.hidden.filter((k) => keys.has(k)),
    spans,
    group: l.group,
  };
}

export function sameLayout(a, b) {
  const x = normalized(a);
  const y = normalized(b);
  const sortedSpans = (s) => JSON.stringify(Object.entries(s).sort(([p], [q]) => (p < q ? -1 : p > q ? 1 : 0)));
  return (
    x.group === y.group &&
    JSON.stringify(x.order) === JSON.stringify(y.order) &&
    JSON.stringify([...x.hidden].sort()) === JSON.stringify([...y.hidden].sort()) &&
    sortedSpans(x.spans) === sortedSpans(y.spans)
  );
}

export function saveAction({ editingDefault, resetPressed, edited }) {
  if (editingDefault) return "default";
  if (resetPressed && !edited) return "delete";
  return "put";
}
