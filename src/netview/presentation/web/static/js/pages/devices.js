// Devices: filterable, sortable, groupable table with show/hide columns and click-to-edit nicknames.
import { apiSend } from "../api.js";
import { esc, fmtAgo } from "../util.js";
import { toast } from "../toast.js";
import { canHide, compileIpRegex, groupKey, ipNum, sortDevices, visibleColumns } from "../table-model.js";

const DEFAULT_REGEX = String.raw`^(\d+\.\d+\.\d+)\.`;
const STATUS_ORDER = { online: 0, quiet: 1, offline: 2 };
const STATUS_TEXT = { online: "Online", quiet: "Quiet", offline: "Offline" };
const GROUP_ORDER = ["Online", "Quiet", "Offline"];

const load = (key, dflt) => {
  try {
    const v = localStorage.getItem(key);
    return v == null ? dflt : JSON.parse(v);
  } catch (e) {
    return dflt;
  }
};
const save = (key, value) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    /* not persisted */
  }
};

/** True for a locally administered MAC (second bit of the first octet), as phones use for private addresses. */
export function isLocalMac(mac) {
  const m = /^([0-9a-f]{2})[:-]/i.exec(String(mac ?? ""));
  return !!m && (parseInt(m[1], 16) & 2) !== 0;
}

/** The device count as separate stat chips for the toolbar. */
export function statChips(counts) {
  return [
    ["ok", counts.online, "online"],
    ["warn", counts.quiet, "quiet"],
    ["bad", counts.offline, "offline"],
  ]
    .map(([kind, n, label]) => `<span class="chip ${kind}"><b>${esc(n)}</b> ${label}</span>`)
    .join("");
}

/** The confirmation text before a device is forgotten. */
export function forgetPrompt(d) {
  const name = d.nickname || d.device_name || d.ip || d.key;
  return `Forget ${name}? Its nickname is kept and comes back if the device returns.`;
}

/** True for a dotted-quad IPv4 address (each part 0 to 255). */
export function isIpv4(value) {
  const parts = String(value ?? "").trim().split(".");
  return parts.length === 4 && parts.every((p) => /^[0-9]{1,3}$/.test(p) && Number(p) <= 255);
}

const hasCapability = (state, name) => !!(state && (state.capabilities || []).includes(name));

/** The Actions cell: Inspect or View report, Watch (when not watched), and Forget (not for this device). */
export function actionsCell(d, state) {
  const inspected = !!(state && state.inspected && state.inspected[d.ip]);
  const canInspect = hasCapability(state, "inspection");
  const label = inspected ? "View report" : "Inspect";
  // A disabled button ignores the pointer, so the wrapper carries the hover text too.
  const inspect = canInspect
    ? `<button type="button" class="small" data-inspect="${esc(d.ip)}">${label}</button>`
    : `<span title="No inspection plugin is turned on"><button type="button" class="small" data-inspect="${esc(d.ip)}" disabled title="No inspection plugin is turned on">${label}</button></span>`;
  if (d.is_self) return `<td>${inspect}</td>`;
  const watch = d.watched ? "" : `<button type="button" class="small" data-watch="${esc(d.ip)}">Watch</button>`;
  return `<td><span class="acts">${inspect}${watch}<button type="button" class="small quiet" data-forget="${esc(d.key)}">Forget</button></span></td>`;
}

const dateTitle = (ms) => (ms ? new Date(ms).toLocaleString() : "");

/** The core columns; every value is escaped. `sortKey` drives sorting, `td` renders the cell. */
export const CORE_COLUMNS = [
  {
    id: "status",
    label: "Status",
    fixed: true,
    sortKey: (d) => STATUS_ORDER[d.status] ?? 9,
    td: (d) => `<td><span class="st ${esc(d.status)}"><span class="dot-s ${esc(d.status)}"></span>${esc(STATUS_TEXT[d.status] || d.status)}</span></td>`,
  },
  {
    id: "nickname",
    label: "Nickname",
    sub: "(yours, click to edit)",
    sortKey: (d) => d.nickname || "￿",
    td: (d) =>
      `<td class="namecell" data-key="${esc(d.key)}"${d.is_self ? ' data-self="1"' : ""}>${
        d.nickname ? esc(d.nickname) : `<span class="ph">${d.is_self ? "This device" : "add nickname"}</span>`
      }</td>`,
  },
  {
    id: "device_name",
    label: "Device name",
    sortKey: (d) => d.device_name || "￿",
    td: (d) =>
      `<td>${d.device_name ? `${esc(d.device_name)}<div class="scope">from ${esc(d.name_source)}</div>` : '<span class="scope">not announced</span>'}${
        d.is_new ? '<span class="badge new">New</span>' : ""
      }${d.watched ? '<span class="badge watch">Watched</span>' : ""}</td>`,
  },
  {
    id: "type",
    label: "Type",
    sortKey: (d) => d.type || "￿",
    td: (d) =>
      `<td>${
        d.type
          ? esc(d.type) + (d.type_source === "vendor" && !d.is_self ? '<div class="scope">guess from maker</div>' : "")
          : '<span class="scope">–</span>'
      }</td>`,
  },
  { id: "ip", label: "IP", fixed: true, sortKey: (d) => ipNum(d.ip), td: (d) => `<td class="addr">${esc(d.ip)}</td>` },
  { id: "mac", label: "MAC", sortKey: (d) => d.mac || "", td: (d) => `<td class="addr">${esc(d.mac || "–")}</td>` },
  {
    id: "vendor",
    label: "Vendor / hint",
    sortKey: (d) => d.vendor || "￿",
    td: (d) => {
      const maker = d.vendor ? esc(d.vendor) : isLocalMac(d.mac) ? '<span class="scope">Random or local MAC</span>' : "";
      const hint = d.os_hint && d.ttl ? `<div class="scope">TTL ${esc(d.ttl)}: ${esc(d.os_hint)}</div>` : "";
      return `<td>${maker}${hint}</td>`;
    },
  },
  {
    id: "first_seen",
    label: "First seen",
    sortKey: (d) => d.first_seen_ms,
    td: (d) => `<td title="${esc(dateTitle(d.first_seen_ms))}">${esc(fmtAgo(d.first_seen_ms))}</td>`,
  },
  {
    id: "last_seen",
    label: "Last seen",
    sortKey: (d) => d.last_seen_ms,
    td: (d) => `<td title="${esc(dateTitle(d.last_seen_ms))}">${esc(fmtAgo(d.last_seen_ms))}</td>`,
  },
  {
    id: "actions",
    label: "Actions",
    fixed: true,
    td: (d, state) => actionsCell(d, state),
  },
];

/** Wrap a plugin's devices.column spec in the shape the table uses. A plugin cell is `text(d)` (escaped here) or `render(d)` (HTML the plugin has escaped). */
function pluginColumn(spec) {
  const cell = (d, state) => {
    try {
      return typeof spec.text === "function" ? esc(spec.text(d, state)) : String(spec.render(d, state) ?? "");
    } catch (e) {
      console.error(`Plugin "${spec.pluginId}" column "${spec.id}" failed`, e);
      return `<span class="err">error</span>`;
    }
  };
  return {
    id: `${spec.pluginId}.${spec.id}`,
    label: spec.label || spec.id,
    sub: spec.sub,
    sortKey: typeof spec.sortKey === "function" ? (d, state) => spec.sortKey(d, state) : undefined,
    groupKey: spec.groupKey,
    td: (d, state) => `<td>${cell(d, state)}</td>`,
  };
}

export function mountDevices(el, ctx) {
  const columns = [...CORE_COLUMNS, ...ctx.host.get("devices.column").map(pluginColumn)];
  const fixedIds = new Set(columns.filter((c) => c.fixed).map((c) => c.id));

  let hidden = new Set(load("netview-hidden-cols", []).filter((id) => columns.some((c) => c.id === id && !fixedIds.has(id))));
  if (hidden.has("nickname") && hidden.has("device_name")) hidden.delete("nickname");
  let groupBy = load("netview-group-by", "none");
  if (!["none", "status", "type", "vendor", "ip"].includes(groupBy) && !columns.some((c) => c.id === groupBy && c.groupKey)) groupBy = "none";
  let ipRegex = load("netview-ip-regex", DEFAULT_REGEX);
  let statusFilter = "all";
  let sort = { key: "ip", dir: 1 };
  const collapsed = new Set();
  let editing = null; // device key being edited
  let state = ctx.getState();

  const groupOptions = [
    ["none", "Nothing"],
    ["status", "Status"],
    ["type", "Type"],
    ["vendor", "Vendor"],
    ["ip", "IP pattern (regex)"],
    ...columns.filter((c) => c.groupKey).map((c) => [c.id, c.label]),
  ];

  el.innerHTML = `
  <div class="toolbar" role="search">
    <input type="text" class="search" id="devFilter" placeholder="Filter by IP, MAC, name or vendor" aria-label="Filter devices">
    <div class="seg" id="devSeg" role="group" aria-label="Status filter">
      <button type="button" data-v="all" class="on">All</button>
      <button type="button" data-v="online">Online</button>
      <button type="button" data-v="quiet">Quiet</button>
      <button type="button" data-v="offline">Offline</button>
    </div>
    <label class="gl" for="groupBy">Group by</label>
    <select id="groupBy" aria-label="Group devices by">${groupOptions.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select>
    <input type="text" id="ipRegex" class="hide" spellcheck="false" aria-label="IP grouping pattern (regular expression)"
           title="Devices are grouped by the first capture group, or by the whole match when there is no group. Non-matching devices go under '(no match)'.">
    <div class="colmenu">
      <button type="button" id="colBtn" aria-haspopup="true" aria-expanded="false" aria-controls="colPop">Columns</button>
      <div class="colpop hide" id="colPop" role="dialog" aria-label="Show or hide columns"></div>
    </div>
    <span class="count chips" id="devCount" aria-label="Device counts"></span>
    <form class="inspect-any" id="inspectAny" novalidate>
      <input type="text" id="inspectIp" placeholder="Inspect any IP, e.g. 192.168.1.125" aria-label="Inspect any IP" autocomplete="off" spellcheck="false">
      <button type="submit" id="inspectGo">Inspect</button>
    </form>
  </div>
  <p class="err" id="regexErr" role="status"></p>
  <div class="tablewrap tall">
    <table id="devTable"><thead id="devHead"></thead><tbody id="devBody"></tbody></table>
  </div>`;

  const $ = (id) => el.querySelector("#" + id);
  $("groupBy").value = groupBy;
  $("ipRegex").value = ipRegex;
  $("ipRegex").classList.toggle("hide", groupBy !== "ip");

  function renderColMenu(full) {
    const n = hidden.size;
    $("colBtn").textContent = n ? `Columns (${n} hidden)` : "Columns";
    if (!full || $("colPop").classList.contains("hide")) return;
    const items = columns
      .map((col) => {
        const verdict = canHide(col.id, hidden);
        const locked = !verdict.ok && !hidden.has(col.id);
        const why = locked ? verdict.reason : col.id === groupBy && !hidden.has(col.id) ? "hidden while grouped" : "";
        return `<label class="${locked ? "dis" : ""}"><input type="checkbox" data-col="${esc(col.id)}" ${hidden.has(col.id) ? "" : "checked"} ${locked ? "disabled" : ""}>${esc(col.label)}<span class="why">${esc(why)}</span></label>`;
      })
      .join("");
    $("colPop").innerHTML = `${items}<div class="foot"><span class="scope">${n ? n + " hidden" : "All shown"}</span><button type="button" class="small" id="colAll" ${n ? "" : "disabled"}>Show all</button></div>`;
  }

  function groupOrder(a, b) {
    if (groupBy === "status") return GROUP_ORDER.indexOf(a) - GROUP_ORDER.indexOf(b);
    const last = (s) => (/^(Unknown|\(no match\))/.test(s) ? 1 : 0);
    return last(a) - last(b) || a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }

  function render() {
    if (editing || !state) return; // don't clobber an open name editor
    const q = $("devFilter").value.trim().toLowerCase();
    const all = state.devices;
    const counts = { online: 0, quiet: 0, offline: 0 };
    for (const d of all) if (d.status in counts) counts[d.status]++;
    $("devCount").innerHTML = statChips(counts);

    const matches = all.filter(
      (d) =>
        (statusFilter === "all" || d.status === statusFilter) &&
        (!q || [d.ip, d.mac, d.nickname, d.device_name, d.type, d.vendor, d.os_hint].some((v) => (v || "").toLowerCase().includes(q))),
    );
    const list = sortDevices(matches, sort.key, sort.dir, columns, state);
    const cols = visibleColumns(columns, hidden, groupBy);

    $("devHead").innerHTML = `<tr>${cols
      .map((col) => {
        if (!col.sortKey) return `<th>${esc(col.label)}</th>`;
        const on = col.id === sort.key;
        return `<th class="sort" data-k="${esc(col.id)}" aria-sort="${on ? (sort.dir > 0 ? "ascending" : "descending") : "none"}">${esc(col.label)}${col.sub ? ` <span class="scope">${esc(col.sub)}</span>` : ""}${on ? `<span class="arr">${sort.dir > 0 ? "▲" : "▼"}</span>` : ""}</th>`;
      })
      .join("")}</tr>`;
    renderColMenu(false); // only the button label: rebuilding an open popover would steal focus

    if (!list.length) {
      $("devBody").innerHTML = `<tr><td colspan="${cols.length}" class="empty">${all.length ? "No devices match the filter." : "Waiting for the first sweep…"}</td></tr>`;
      return;
    }
    const row = (d) => `<tr class="${esc(d.status)}">${cols.map((c) => c.td(d, state)).join("")}</tr>`;

    if (groupBy === "none") {
      $("devBody").innerHTML = list.map(row).join("");
      return;
    }
    let regex = null;
    if (groupBy === "ip") {
      try {
        regex = compileIpRegex(ipRegex || DEFAULT_REGEX);
        $("regexErr").textContent = "";
      } catch (e) {
        $("regexErr").textContent = e.message;
        $("devBody").innerHTML = list.map(row).join("");
        return;
      }
    }
    const groups = new Map();
    for (const d of list) {
      const g = groupKey(d, groupBy, regex, columns);
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(d);
    }
    $("devBody").innerHTML = [...groups.keys()]
      .sort(groupOrder)
      .map((g) => {
        const ds = groups.get(g);
        const shut = collapsed.has(g);
        const on = ds.filter((d) => d.status === "online").length;
        return (
          `<tr class="grp"><th colspan="${cols.length}" scope="colgroup"><button type="button" data-group="${esc(g)}" aria-expanded="${!shut}">${shut ? "▸" : "▾"} ${esc(g)}</button><span class="scope">${ds.length} device${ds.length > 1 ? "s" : ""}, ${on} online</span></th></tr>` +
          (shut ? "" : ds.map(row).join(""))
        );
      })
      .join("");
  }

  // ---------- columns popover
  const closeColPop = () => {
    $("colPop").classList.add("hide");
    $("colBtn").setAttribute("aria-expanded", "false");
  };
  $("colBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    const pop = $("colPop");
    const open = pop.classList.toggle("hide") === false;
    $("colBtn").setAttribute("aria-expanded", String(open));
    if (open) {
      renderColMenu(true);
      const first = pop.querySelector("input:not([disabled])");
      if (first) first.focus();
    }
  });
  $("colPop").addEventListener("click", (e) => {
    e.stopPropagation();
    if (e.target.id !== "colAll") return;
    hidden.clear();
    save("netview-hidden-cols", []);
    render();
    renderColMenu(true);
  });
  $("colPop").addEventListener("change", (e) => {
    const id = e.target.dataset.col;
    if (!id) return;
    if (e.target.checked) hidden.delete(id);
    else if (canHide(id, hidden).ok) hidden.add(id);
    else e.target.checked = true;
    save("netview-hidden-cols", [...hidden]);
    render();
    renderColMenu(true);
    const again = $("colPop").querySelector(`input[data-col="${CSS.escape(id)}"]`);
    if (again) again.focus();
  });
  const onDocClick = () => closeColPop();
  const onDocKey = (e) => {
    if (e.key === "Escape" && !$("colPop").classList.contains("hide")) {
      closeColPop();
      $("colBtn").focus();
    }
  };
  document.addEventListener("click", onDocClick);
  document.addEventListener("keydown", onDocKey);

  // ---------- filters, grouping, sorting
  $("groupBy").addEventListener("change", () => {
    groupBy = $("groupBy").value;
    save("netview-group-by", groupBy);
    $("ipRegex").classList.toggle("hide", groupBy !== "ip");
    if (groupBy !== "ip") $("regexErr").textContent = "";
    collapsed.clear();
    render();
  });
  $("ipRegex").addEventListener("input", () => {
    ipRegex = $("ipRegex").value;
    save("netview-ip-regex", ipRegex);
    collapsed.clear();
    render();
  });
  $("devFilter").addEventListener("input", render);
  $("devSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    statusFilter = b.dataset.v;
    $("devSeg").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    render();
  });
  $("devHead").addEventListener("click", (e) => {
    const th = e.target.closest("th.sort");
    if (!th) return;
    sort = { key: th.dataset.k, dir: sort.key === th.dataset.k ? -sort.dir : 1 };
    render();
  });

  // ---------- group rows and nickname editing
  $("devBody").addEventListener("click", (e) => {
    const ib = e.target.closest("[data-inspect]");
    if (ib) {
      ctx.openReport(ib.dataset.inspect);
      return;
    }
    const wb = e.target.closest("[data-watch]");
    if (wb) {
      watch(wb.dataset.watch);
      return;
    }
    const fb = e.target.closest("[data-forget]");
    if (fb) {
      forget(fb.dataset.forget);
      return;
    }
    const gb = e.target.closest("[data-group]");
    if (gb) {
      const g = gb.dataset.group;
      if (collapsed.has(g)) collapsed.delete(g);
      else collapsed.add(g);
      render();
      return;
    }
    const cell = e.target.closest(".namecell");
    if (!cell || cell.dataset.self || editing) return;
    startEdit(cell);
  });

  async function watch(ip) {
    try {
      await apiSend("POST", "/api/v1/watches", { spec: ip });
      ctx.refresh();
    } catch (err) {
      toast(err.message || "Could not watch the device", "bad");
    }
  }

  // ---------- inspect any IP
  const inspectIp = $("inspectIp");
  inspectIp.addEventListener("input", () => inspectIp.setCustomValidity(""));
  $("inspectAny").addEventListener("submit", (e) => {
    e.preventDefault();
    const value = inspectIp.value.trim();
    if (!value) return;
    if (!isIpv4(value)) {
      inspectIp.setCustomValidity("Enter an IPv4 address");
      inspectIp.reportValidity();
      return;
    }
    inspectIp.setCustomValidity("");
    ctx.openReport(value);
  });

  async function forget(key) {
    const device = state.devices.find((d) => d.key === key);
    if (!device || !window.confirm(forgetPrompt(device))) return;
    try {
      await apiSend("DELETE", `/api/v1/devices/${encodeURIComponent(key)}`);
      ctx.refresh();
    } catch (err) {
      toast(err.message || "Could not forget the device", "bad");
    }
  }

  function startEdit(cell) {
    const key = cell.dataset.key;
    const device = state.devices.find((d) => d.key === key);
    editing = key;
    cell.innerHTML = `<input type="text" value="${esc(device ? device.nickname : "")}" aria-label="Nickname" placeholder="Your name for it"><div class="err" role="status"></div>`;
    const input = cell.querySelector("input");
    const errBox = cell.querySelector(".err");
    input.focus();
    input.select();
    let busy = false;
    let finished = false;
    const stop = () => {
      finished = true;
      editing = null;
      render();
    };
    const commit = async () => {
      if (busy || finished) return;
      const value = input.value.trim();
      if ((device ? device.nickname || "" : "") === value) return stop();
      busy = true;
      try {
        await apiSend("PUT", `/api/v1/devices/${encodeURIComponent(key)}/nickname`, { nickname: value === "" ? null : value });
        finished = true;
        editing = null;
        ctx.refresh();
      } catch (err) {
        errBox.textContent = err.message; // a 422 stays visible inline; the editor stays open
        busy = false;
        input.focus();
      }
    };
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") commit();
      else if (ev.key === "Escape") stop();
    });
    input.addEventListener("blur", () => {
      if (!errBox.textContent && !finished) commit();
    });
    input.addEventListener("input", () => {
      errBox.textContent = "";
    });
  }

  render();
  return {
    update(s) {
      state = s;
      render();
    },
    destroy() {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onDocKey);
    },
  };
}
