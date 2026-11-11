// The Switch page: header, faceplate, port detail and the VLAN / MAC / spanning tree / LAG / inventory sections.
import {
  consoleButtonHtml, consoleState, cpuSlot, faceplateLayout, fmtUptime, jackHtml, portAreaStyle, portCellHtml, portChartSeries, portRanges, portSortKey,
  portState, speedShort, vlanLegend,
} from "./port-grid.js";

const FACE_SRC = new URL("./faceplate.svg", import.meta.url).href;
const VIEW_KEY = "netview.gsm7248.faceView";
const REFRESH_MS = 15000;

// The Ports card's views: the faceplate by link state, the faceplate by VLAN, and the switch's management side.
const VIEWS = [
  ["status", "Ports"],
  ["vlan", "VLAN"],
  ["mgmt", "Management"],
];

/** The Ports card view last chosen in this browser: "status" (the default), "vlan" or "mgmt". */
export function loadView() {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    return VIEWS.some(([id]) => id === v) ? v : "status";
  } catch {
    return "status";
  }
}

function saveView(view) {
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {
    // private window or blocked storage: the choice just lasts for this visit
  }
}
const POLL_CHECK_MS = 1500;
const POLL_WAIT_MS = 60000;

/**
 * The Poll now button. Disabled while this page's request is out or waiting for its poll, or while the
 * server reports any poll running (summary.polling), since a second one would only be refused.
 */
export function pollButtonState(summary, requesting) {
  const busy = !!requesting || !!(summary && summary.polling);
  return busy
    ? { disabled: true, label: "Polling…", title: "A poll of the switch is running" }
    : { disabled: false, label: "Poll now", title: "Poll the switch now" };
}

/** "60 of 128 MB", or "60 MB" when the switch reports no total (GSM7248 firmware 6.3.x); null when unknown. */
export function memoryText(health) {
  const free = health ? health.mem_free_kb : null;
  if (free == null) return null;
  const mb = (kb) => Math.round(kb / 1024);
  return health.mem_total_kb ? `${mb(free)} of ${mb(health.mem_total_kb)} MB` : `${mb(free)} MB`;
}

/** The notice laid over the greyed-out ports in the Management view. Static text: nothing to escape. */
export const MGMT_NOTICE =
  `<b>Management view.</b> Ports are greyed out: this view covers the switch itself. Its CPU interface links to the ` +
  `management processor (web UI, SNMP, spanning tree); the serial console is the port at the far right.`;

/**
 * The faceplate for the Management view: the drawing with its ports greyed out under MGMT_NOTICE. A copy of the
 * notice sits below the drawing for screens too narrow to show the whole faceplate (the CSS shows one of the two).
 */
export function managementFaceHtml(faceSrc, esc, consoleButton) {
  return (
    `<div class="faceplate mgmt"><img src="${esc(faceSrc)}" alt="" draggable="false">` +
    `<div class="mgmt-cover" style="${portAreaStyle()}"><p>${MGMT_NOTICE}</p></div>${consoleButton || ""}</div>` +
    `<p class="mgmt-note">${MGMT_NOTICE}</p>`
  );
}

/**
 * The Management view's details: the switch's management address and its CPU interface, the internal link to
 * the management processor. That interface has no socket, so it shows no link, speed or VLAN state.
 */
export function managementHtml(summary, cpuPorts, esc, fmtAgo) {
  const s = summary || {};
  const sw = s.switch || {};
  const h = s.health || {};
  const field = (k, v) => `<div><dt>${esc(k)}</dt><dd>${esc(v == null || v === "" ? "–" : v)}</dd></div>`;
  const status = s.reachable === true ? "✓ answering SNMP" : s.reachable === false ? "⚠ not answering" : null;
  const cpu = (cpuPorts || []).map((p) => cpuSlot(p.name)).join(", ") || "none reported";
  return (
    `<div class="gs-mgmt">` +
    `<dl class="gs-fields">` +
    field("Management address", s.host) +
    field("Switch MAC", sw.mac) +
    field("CPU interface", cpu) +
    field("Status", status) +
    field("Last polled", s.last_poll_ms ? fmtAgo(s.last_poll_ms) : null) +
    field("CPU load", h.cpu_percent != null ? `${h.cpu_percent} %` : null) +
    field("Memory free", memoryText(h)) +
    `</dl></div>`
  );
}

/** Shown in the Management view when the serial console is turned off. */
export const CONSOLE_OFF_HTML =
  `<div class="gs-console off" role="group" aria-label="Serial console"><b>Serial console</b>` +
  `<span class="sub">Turned off. Turn it on in Settings, in the Serial console section of the GSM7248 tab.</span></div>`;

/**
 * The serial console panel: the last probe result, Probe now and Open terminal; Close only when `closable`.
 * Empty when the console is turned off. `msg` is the last action's message.
 */
export function consolePanelHtml(info, esc, fmtAgo, msg, closable) {
  const st = consoleState(info);
  if (!st) return "";
  const status = info.probing ? null : info.status;
  const where = `${esc(info.device)} on ${esc(info.host)}`;
  const when = status ? `, probed ${esc(fmtAgo(status.at_ms))}` : "";
  return (
    `<div class="gs-console" role="group" aria-label="Serial console">` +
    `<b>Serial console</b><span class="chip">${st.symbol} ${esc(st.words)}</span><span class="sub">${where}${when}</span>` +
    `<span class="grow"></span>` +
    `<button type="button" class="quiet small" id="gsProbe"${info.probing ? " disabled" : ""}>Probe now</button>` +
    (info.can_open ? `<button type="button" class="primary small" id="gsTerm">Open terminal</button>` : "") +
    (closable ? `<button type="button" class="quiet small" id="gsConsoleClose">Close</button>` : "") +
    (status && status.detail ? `<p class="sub">${esc(status.detail)}</p>` : "") +
    (status && status.text ? `<pre aria-label="What the switch sent">${esc(status.text)}</pre>` : "") +
    `<p class="err" role="status">${esc(msg)}</p></div>`
  );
}

/** Build the page spec. `store` is the shared data store from ui.js. */
export function createPage(ui, store) {
  const { esc, fmtAgo, fmtRate } = ui.util;

  return {
    id: "switch",
    title: "Switch",
    mount(el) {
      el.innerHTML = `
      <div class="gsw">
        <section class="card" aria-label="Switch"><div id="gsHead"></div></section>
        <section class="card" aria-label="Ports">
          <div class="card-head"><h2>Ports</h2><div class="gs-view" id="gsView" role="group" aria-label="Faceplate view"></div></div>
          <div class="faceplate-scroll" id="gsGrid"></div>
          <div id="gsConsole"></div>
          <div id="gsLegend" class="gs-legend"></div>
        </section>
        <section class="card" id="gsDetailCard" aria-label="Port detail" aria-live="polite"><div id="gsDetail"></div></section>
        <section class="card"><h2>VLANs</h2><div class="tablewrap" id="gsVlans"></div></section>
        <section class="card">
          <div class="card-head"><h2>MAC table</h2>
            <input type="search" id="gsMacFilter" class="search" placeholder="Filter by MAC, port, name or vendor" aria-label="Filter MAC table"></div>
          <div class="tablewrap" id="gsMacs"></div>
        </section>
        <section class="card"><h2>Spanning tree</h2><div class="tablewrap" id="gsStp"></div></section>
        <section class="card"><h2>Link aggregation</h2><div id="gsLags"></div></section>
        <section class="card"><h2>Inventory</h2><div id="gsInv"></div></section>
      </div>`;
      const $ = (id) => el.querySelector("#" + id);
      let selected = null;
      let view = loadView();
      let highlight = null; // the VLAN whose legend chip is hovered or focused
      let consoleInfo = null; // GET /console: settings and the last probe result
      let consoleOpen = false; // the console panel under the faceplate is shown
      let consoleMsg = "";
      let consoleAsked = false; // the probe that runs once when the page opens has been sent
      let consoleTimer = null;
      let detail = null; // /ports/{name} for the selected port
      let detailSeq = 0;
      const samples = new Map(); // port name -> {rows, at}: the last hour of samples, fetched at most once per 15 s
      const asked = new Map(); // port name -> when its samples were last requested
      let samplesSeq = 0;
      let filter = "";
      let lastState = null;
      let pollMsg = "";
      let requesting = false; // the POST /poll is out, or we are waiting for the poll it started
      let destroyed = false;

      const portByName = (name) => store.data.ports.find((p) => p.name === name) || null;

      function renderHead() {
        const s = store.data.summary;
        const sw = s && s.switch;
        let status = "";
        if (store.data.error) status = `<span class="chip bad">⚠ ${esc(store.data.error)}</span>`;
        else if (s && !s.configured) status = `<span class="chip warn">⚠ Not configured: set up in Settings</span>`;
        else if (s && s.reachable === false) status = `<span class="chip bad">⚠ Unreachable${s.last_error ? ": " + esc(s.last_error) : ""}</span>`;
        else if (s && s.reachable) status = `<span class="chip ok">✓ Reachable</span>`;
        if (s && s.configured && s.reachable !== false && s.last_error && !store.data.error) {
          status += `<span class="chip warn">⚠ ${esc(s.last_error)}</span>`;
        }
        const info = sw
          ? `<span class="chip"><b>${esc(sw.name || "GSM7248")}</b></span><span class="chip">${esc(sw.model || "model unknown")}</span>` +
            `<span class="chip">firmware <b>${esc(sw.firmware || "–")}</b></span><span class="chip">up <b>${esc(fmtUptime(sw.uptime_s))}</b></span>`
          : "";
        const last = s && s.last_poll_ms ? `<span class="sub">polled ${esc(fmtAgo(s.last_poll_ms))}</span>` : "";
        $("gsHead").innerHTML =
          `<div class="card-head"><h2>NETGEAR GSM7248</h2>${info}${status}${last}` +
          (() => {
            const b = pollButtonState(s, requesting);
            return `<button type="button" class="primary small" id="gsPoll" title="${esc(b.title)}"${b.disabled ? " disabled" : ""}>${esc(b.label)}</button>`;
          })() +
          `<span class="err" id="gsPollMsg" role="status">${esc(pollMsg)}</span></div>`;
      }

      function renderGrid() {
        const grid = $("gsGrid");
        const active = document.activeElement;
        const focused = active && grid.contains(active) && active.dataset ? active.dataset.port : null;
        const consoleFocused = !!(active && grid.contains(active) && active.dataset && "console" in active.dataset);
        const ports = store.data.ports;
        const viewBtn = (id, label) =>
          `<button type="button" class="${view === id ? "primary" : "quiet"} small" data-view="${id}" aria-pressed="${view === id}">${label}</button>`;
        $("gsView").innerHTML = ports.length ? VIEWS.map(([id, label]) => viewBtn(id, label)).join("") : "";
        if (!ports.length) {
          grid.innerHTML = `<p class="sub">No port data yet.</p>`;
          $("gsLegend").innerHTML = "";
          return;
        }
        const f = faceplateLayout(ports);
        const face = [...f.top, ...f.bottom];
        if (view === "mgmt") {
          highlight = null;
          grid.innerHTML =
            (face.length ? managementFaceHtml(FACE_SRC, esc, consoleButtonHtml(consoleInfo, esc, true)) : "") +
            managementHtml(store.data.summary, f.mgmt, esc, fmtAgo);
          if (consoleFocused) {
            const again = grid.querySelector("[data-console]");
            if (again) again.focus();
          }
          $("gsLegend").innerHTML = "";
          renderConsole();
          return;
        }
        const legend = vlanLegend(ports, store.data.vlans);
        grid.innerHTML =
          (face.length
            ? `<div class="faceplate"><img src="${esc(FACE_SRC)}" alt="" draggable="false">${face.map((p) => jackHtml(p, esc, view, legend.colors)).join("")}${consoleButtonHtml(consoleInfo, esc, consoleOpen)}</div>`
            : "") +
          (f.extra.length
            ? `<div class="gs-extra"><span class="sub">Other interfaces</span><div class="gs-row">${f.extra.map((p) => portCellHtml(p, esc)).join("")}</div></div>`
            : "");
        const cells = [...grid.querySelectorAll("[data-port]")];
        for (const b of cells) if (b.dataset.port === selected) b.setAttribute("aria-pressed", "true");
        if (focused) {
          const again = cells.find((b) => b.dataset.port === focused);
          if (again) again.focus();
        }
        if (consoleFocused) {
          const again = grid.querySelector("[data-console]");
          if (again) again.focus();
        }
        renderConsole();
        if (view === "vlan") {
          if (!legend.vlans.some((v) => v.vid === highlight)) highlight = null;
          const plural = (n) => `${n} port${n === 1 ? "" : "s"}`;
          $("gsLegend").innerHTML =
            legend.vlans
              .map(
                (v) =>
                  `<button type="button" class="gs-vl" data-vid="${esc(v.vid)}" title="Highlight every port in VLAN ${esc(v.vid)}, tagged or untagged">` +
                  `<i style="background:${esc(v.color)}"></i>${esc(v.vid)}${v.name ? " " + esc(v.name) : ""} · ${esc(plural(v.count))}</button>`,
              )
              .join("") +
            (legend.trunks ? `<span class="gs-vl"><i class="tr"></i>T trunk (tagged in other VLANs) · ${esc(plural(legend.trunks))}</span>` : "") +
            `<span>dot: link up</span>`;
        } else {
          highlight = null;
          $("gsLegend").innerHTML =
            `<span>green ring: link up</span><span>no ring: link down</span><span>⦸ admin disabled</span><span>⏸ STP blocking</span>` +
            `<span>↑ uplink</span><span>bar: utilisation</span>`;
        }
        applyHighlight();
      }

      /**
       * The console panel. Under the faceplate it opens from the console port; in the Management view it is
       * always shown (with no Close), or a note when the console is turned off.
       */
      function renderConsole() {
        const box = $("gsConsole");
        if (view === "mgmt") {
          box.innerHTML = consoleInfo ? consolePanelHtml(consoleInfo, esc, fmtAgo, consoleMsg, false) || CONSOLE_OFF_HTML : "";
          return;
        }
        box.innerHTML = consoleOpen ? consolePanelHtml(consoleInfo, esc, fmtAgo, consoleMsg, true) : "";
      }

      /** Read the console's state; the first time, also probe it once if it is turned on. */
      function loadConsole() {
        return ui
          .apiGet(`${ui.apiBase}/console`)
          .then((info) => {
            if (destroyed) return;
            consoleInfo = info;
            if (!info.enabled) consoleOpen = false;
            renderGrid();
            if (info.enabled && !consoleAsked) {
              consoleAsked = true;
              if (!info.status && !info.probing) probeConsole();
            }
          })
          .catch(() => {});
      }

      async function probeConsole() {
        if (!consoleInfo || !consoleInfo.enabled || consoleInfo.probing) return;
        consoleInfo = { ...consoleInfo, probing: true };
        consoleMsg = "";
        renderGrid();
        try {
          consoleInfo = await ui.apiSend("POST", `${ui.apiBase}/console/probe`, {});
        } catch (err) {
          // 409: another tab's probe is running, so its result arrives with the next refresh
          consoleInfo = { ...consoleInfo, probing: false };
          if (err.status !== 409) consoleMsg = err.message;
        }
        if (!destroyed) renderGrid();
      }

      async function openTerminal() {
        consoleOpen = true;
        if (!consoleInfo || !consoleInfo.can_open) return renderGrid();
        try {
          await ui.apiSend("POST", `${ui.apiBase}/console/open`, {});
          consoleMsg = "Terminal window opened.";
          // the new session holds the serial port: look again so the port shows "a console session is open"
          clearTimeout(consoleTimer);
          consoleTimer = setTimeout(() => {
            if (!destroyed) probeConsole();
          }, 4000);
        } catch (err) {
          consoleMsg = err.message;
        }
        if (!destroyed) renderGrid();
      }

      /** Dim every jack that is not a member of the highlighted VLAN. */
      function applyHighlight() {
        for (const j of $("gsGrid").querySelectorAll("[data-vlans]")) {
          j.classList.toggle("dim", highlight != null && !j.dataset.vlans.split(" ").includes(String(highlight)));
        }
      }

      function setHighlight(e, on) {
        const chip = e.target.closest("[data-vid]");
        const next = on && chip ? Number(chip.dataset.vid) : null;
        if (next === highlight) return;
        highlight = next;
        applyHighlight();
      }

      function deviceLine(d) {
        const name = d.display_name ? esc(d.display_name) : `<span class="badge">unknown</span>`;
        return `<li><span class="addr">${esc(d.mac)}</span> ${name}${d.ip ? ` <span class="sub">${esc(d.ip)}</span>` : ""}${d.vendor ? ` <span class="sub">${esc(d.vendor)}</span>` : ""}</li>`;
      }

      function renderDetail() {
        const box = $("gsDetail");
        const p = selected && portByName(selected);
        if (!p) {
          box.innerHTML = `<p class="sub">Select a port to see its details.</p>`;
          return;
        }
        const st = portState(p);
        const r = p.rates;
        const vl = p.vlans || { untagged: [], tagged: [] };
        const field = (k, v) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`;
        const fresh = detail && detail.name === p.name;
        const devices = fresh ? detail.devices : p.devices;
        const history = fresh ? detail.mac_history || [] : [];
        box.innerHTML =
          `<div class="card-head"><h2>Port ${esc(p.name)}</h2><span class="chip">${st.symbol} ${esc(st.words)}</span>` +
          `${p.uplink ? `<span class="chip accent">uplink</span>` : ""}` +
          `<button type="button" class="quiet small" id="gsClose">Close</button></div>` +
          `<dl class="gs-fields">` +
          field("Alias", p.alias ? esc(p.alias) : "–") +
          field("Speed", `${esc(speedShort(p.oper_up ? p.speed_mbps : null))} ${esc(p.oper_up ? p.duplex || "" : "")}`) +
          field("PVID", esc(p.pvid ?? "–")) +
          field("VLANs untagged", esc(vl.untagged.join(", ") || "–")) +
          field("VLANs tagged", esc(vl.tagged.join(", ") || "–")) +
          field("STP state", esc(p.stp_state || "–")) +
          field("LAG", esc(p.lag || "–")) +
          field("In", r ? esc(fmtRate(r.in_bps)) : "–") +
          field("Out", r ? esc(fmtRate(r.out_bps)) : "–") +
          field("Errors/s", r ? esc((r.in_err_ps + r.out_err_ps).toFixed(2)) : "–") +
          field("Discards/s", r ? esc((r.in_disc_ps + r.out_disc_ps).toFixed(2)) : "–") +
          field("Utilisation", r && r.util_percent != null ? esc(r.util_percent.toFixed(1) + " %") : "–") +
          `</dl>` +
          `<h3>Traffic, last hour</h3><div class="gs-chart" id="gsPortChart"></div>` +
          `<h3>Attached devices</h3>` +
          (devices.length ? `<ul class="gs-devs">${devices.map(deviceLine).join("")}</ul>` : `<p class="sub">None learned on this port.</p>`) +
          `<h3>MAC history</h3>` +
          (history.length
            ? `<div class="tablewrap"><table><thead><tr><th>MAC</th><th>VLAN</th><th>First seen</th><th>Last seen</th></tr></thead><tbody>` +
              history
                .map((h) => `<tr><td class="addr">${esc(h.mac)}</td><td>${esc(h.vlan)}</td><td>${esc(fmtAgo(h.first_ms))}</td><td>${esc(fmtAgo(h.last_ms))}</td></tr>`)
                .join("") +
              `</tbody></table></div>`
            : `<p class="sub">No history.</p>`);
        drawPortChart();
      }

      function drawPortChart() {
        const box = $("gsPortChart");
        if (!box || !selected) return;
        const have = samples.get(selected);
        ui.util.lineChart(box, {
          label: `Port ${selected} traffic, last hour`,
          series: portChartSeries(have ? have.rows : null),
          fmt: fmtRate,
        });
      }

      function renderVlans() {
        const rows = store.data.vlans;
        $("gsVlans").innerHTML = rows.length
          ? `<table><thead><tr><th>VLAN</th><th>Name</th><th>Untagged</th><th>Tagged</th></tr></thead><tbody>` +
            rows
              .map((v) => `<tr><td>${esc(v.vid)}</td><td>${esc(v.name || "")}</td><td>${esc(portRanges(v.untagged) || "–")}</td><td>${esc(portRanges(v.tagged) || "–")}</td></tr>`)
              .join("") +
            `</tbody></table>`
          : `<p class="sub">No VLAN data yet.</p>`;
      }

      function renderMacs() {
        const q = filter.trim().toLowerCase();
        const rows = store.data.macs.filter(
          (m) => !q || [m.mac, m.port, m.display_name, m.vendor, m.ip, m.device_key ? "" : "unknown"].some((v) => (v || "").toLowerCase().includes(q)),
        );
        rows.sort((a, b) => portSortKey(a.port) - portSortKey(b.port) || a.mac.localeCompare(b.mac));
        $("gsMacs").innerHTML = rows.length
          ? `<table><thead><tr><th>MAC</th><th>Port</th><th>VLAN</th><th>Device</th><th>Vendor</th></tr></thead><tbody>` +
            rows
              .map((m) => {
                const port = m.port ? esc(m.port) + (m.via_uplink ? ` <span class="sub">uplink</span>` : "") : "–";
                const dev = m.device_key ? esc(m.display_name || m.ip || m.mac) : `<span class="badge">unknown</span>`;
                return `<tr><td class="addr">${esc(m.mac)}</td><td>${port}</td><td>${esc(m.vlan)}</td><td>${dev}</td><td>${esc(m.vendor || "")}</td></tr>`;
              })
              .join("") +
            `</tbody></table>`
          : `<p class="sub">${store.data.macs.length ? "No MAC matches the filter." : "No MAC table data yet."}</p>`;
      }

      function renderStp() {
        const all = store.data.ports.filter((p) => p.kind === "ethernet" && p.stp_state);
        const rows = all.filter((p) => p.stp_state !== "disabled");
        const off = all.length - rows.length;
        const note = off ? `<p class="sub">${esc(off)} port${off === 1 ? "" : "s"} not taking part (link down or spanning tree off).</p>` : "";
        $("gsStp").innerHTML = rows.length
          ? note + `<table><thead><tr><th>Port</th><th>Link</th><th>STP state</th></tr></thead><tbody>` +
            rows
              .map((p) => {
                const st = portState(p);
                return `<tr><td>${esc(p.name)}</td><td>${st.symbol} ${esc(st.words)}</td><td>${esc(p.stp_state)}</td></tr>`;
              })
              .join("") +
            `</tbody></table>`
          : note || `<p class="sub">No spanning tree data yet.</p>`;
      }

      function renderLags() {
        const lags = store.data.ports.filter((p) => p.kind === "lag");
        $("gsLags").innerHTML = lags.length
          ? `<ul class="gs-devs">` +
            lags
              .map((g) => {
                const members = store.data.ports.filter((p) => p.lag === g.name).map((p) => p.name);
                return `<li><b>${esc(g.name)}</b> ${esc(portState(g).words)}: ${esc(portRanges(members) || "no members")}</li>`;
              })
              .join("") +
            `</ul>`
          : `<p class="sub">No link aggregation groups.</p>`;
      }

      function renderInventory() {
        const s = store.data.summary;
        const sw = s && s.switch;
        if (!sw) {
          $("gsInv").innerHTML = `<p class="sub">No inventory yet.</p>`;
          return;
        }
        const h = s.health || {};
        const field = (k, v) => `<div><dt>${esc(k)}</dt><dd>${esc(v == null || v === "" ? "–" : v)}</dd></div>`;
        const mem = memoryText(h);
        $("gsInv").innerHTML =
          `<dl class="gs-fields">${field("Name", sw.name)}${field("Model", sw.model)}${field("Firmware", sw.firmware)}${field("Serial", sw.serial)}` +
          `${field("MAC", sw.mac)}${field("Uptime", fmtUptime(sw.uptime_s))}` +
          `${field("CPU", h.cpu_percent != null ? h.cpu_percent + " %" : null)}${field("Memory free", mem)}</dl>`;
      }

      function renderAll() {
        if (destroyed) return;
        renderHead();
        renderGrid();
        renderDetail();
        renderVlans();
        renderMacs();
        renderStp();
        renderLags();
        renderInventory();
      }

      function loadDetail() {
        if (!selected) return;
        const seq = ++detailSeq;
        ui.apiGet(`${ui.apiBase}/ports/${encodeURI(selected)}`)
          .then((d) => {
            if (seq !== detailSeq || destroyed) return;
            detail = d;
            renderDetail();
          })
          .catch(() => {});
      }

      function loadSamples() {
        if (!selected) return;
        const name = selected;
        const t = Date.now();
        if (t - (asked.get(name) ?? -Infinity) < REFRESH_MS) return;
        asked.set(name, t);
        const seq = ++samplesSeq;
        ui.apiGet(`${ui.apiBase}/ports/${encodeURI(name)}/samples`)
          .then((rows) => {
            samples.set(name, { rows, at: Date.now() });
            if (seq !== samplesSeq || destroyed || selected !== name) return;
            drawPortChart();
          })
          .catch(() => asked.delete(name));
      }

      function select(name) {
        selected = selected === name ? null : name;
        detail = null;
        renderGrid();
        renderDetail();
        loadDetail();
        loadSamples();
      }

      async function pollNow() {
        if (pollButtonState(store.data.summary, requesting).disabled) return;
        requesting = true;
        pollMsg = "";
        renderHead();
        try {
          await ui.apiSend("POST", `${ui.apiBase}/poll`, {});
        } catch (err) {
          // 409: a poll is already running, so wait for that one instead of reporting an error
          if (err.status !== 409) {
            pollMsg = err.message;
            requesting = false;
            if (!destroyed) renderHead();
            return;
          }
        }
        // the poll runs after the 202: fetch until the server says it has finished (at most a minute)
        const until = Date.now() + POLL_WAIT_MS;
        do {
          await new Promise((r) => setTimeout(r, POLL_CHECK_MS));
          if (destroyed) return;
          await store.refresh(true);
        } while (store.data.summary && store.data.summary.polling && Date.now() < until);
        requesting = false;
        if (!destroyed) renderHead();
      }

      // on the page's own root: `el` is the shell's shared view element and outlives this page
      el.querySelector(".gsw").addEventListener("click", (e) => {
        const cell = e.target.closest("[data-port]");
        if (cell && $("gsGrid").contains(cell)) return select(cell.dataset.port);
        if (e.target.closest("[data-console]") && $("gsGrid").contains(e.target)) {
          consoleOpen = !consoleOpen;
          return renderGrid();
        }
        if (e.target.closest("#gsProbe")) return probeConsole();
        if (e.target.closest("#gsTerm")) return openTerminal();
        if (e.target.closest("#gsConsoleClose")) {
          consoleOpen = false;
          renderGrid();
          const port = $("gsGrid").querySelector("[data-console]");
          if (port) port.focus();
          return;
        }
        const viewBtn = e.target.closest("#gsView [data-view]");
        if (viewBtn) {
          view = viewBtn.dataset.view;
          saveView(view);
          renderGrid();
          const again = $("gsView").querySelector(`[data-view="${view}"]`);
          if (again) again.focus();
          return;
        }
        if (e.target.closest("#gsClose")) return select(selected);
        if (e.target.closest("#gsPoll")) return pollNow();
      });
      // double-click or right-click on the console port goes straight to the terminal
      for (const type of ["dblclick", "contextmenu"]) {
        $("gsGrid").addEventListener(type, (e) => {
          if (!e.target.closest("[data-console]")) return;
          e.preventDefault();
          openTerminal();
        });
      }
      for (const [type, on] of [["mouseover", true], ["focusin", true], ["mouseout", false], ["focusout", false]]) {
        $("gsLegend").addEventListener(type, (e) => setHighlight(e, on));
      }
      $("gsMacFilter").addEventListener("input", (e) => {
        filter = e.target.value;
        renderMacs();
      });

      let recheck = null;
      const unsubscribe = store.subscribe(() => {
        // a poll started elsewhere (a job, another tab): look again soon so Poll now comes back promptly
        const s = store.data.summary;
        if (s && s.polling && !requesting && !recheck) {
          recheck = setTimeout(() => {
            recheck = null;
            if (!destroyed) store.refresh(true);
          }, POLL_CHECK_MS);
        }
        renderAll();
        loadDetail();
        loadSamples();
      });
      const timer = setInterval(() => {
        if (document.visibilityState !== "visible") return;
        store.refresh();
        loadConsole();
      }, REFRESH_MS);

      renderAll();
      store.refresh(true);
      loadConsole();

      return {
        update(state) {
          // an SSE state render: fetch again (the store allows one fetch per 10 s)
          if (state !== lastState) {
            lastState = state;
            store.refresh();
          }
        },
        destroy() {
          destroyed = true;
          clearInterval(timer);
          clearTimeout(recheck);
          clearTimeout(consoleTimer);
          unsubscribe();
        },
      };
    },
  };
}
