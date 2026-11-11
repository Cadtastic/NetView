// The Switch page: header, drawn faceplate with Status and VLAN views, pause and poll controls, the port
// detail panel with a traffic chart, per-group errors and the configuration sections.
import { jackHtml, portChartSeries, portState, powerDotStyle, speedShort, vlanColors } from "./port-grid.js";

const FACE_SRC = new URL("./faceplate.svg", import.meta.url).href;
const VIEW_KEY = "netview.gs105e.faceView";
const REFRESH_MS = 15000;
const POLL_CHECK_MS = 1500;
const POLL_WAIT_MS = 60000;
const SAMPLES_GAP_MS = 15000;
const DASH = "–";

const VIEWS = [
  ["status", "Status"],
  ["vlan", "VLAN"],
];
const RANGES = [
  ["1h", "1 h", 3_600_000, "raw"],
  ["24h", "24 h", 86_400_000, "5m"],
  ["7d", "7 d", 604_800_000, "5m"],
];

/** The faceplate view last chosen in this browser: "status" (the default) or "vlan". */
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

/** The Poll now button: disabled while this page's request is out or while the server reports a poll running. */
export function pollButtonState(summary, requesting) {
  const busy = !!requesting || !!(summary && summary.polling);
  return busy
    ? { disabled: true, label: "Polling…", title: "A poll of the switch is running" }
    : { disabled: false, label: "Poll now", title: "Poll the switch now" };
}

/** "Paused for 14 min" while a pause runs, otherwise an empty string. */
export function pauseLabel(summary, now) {
  const until = summary && summary.paused_until_ms;
  if (until == null || until <= now) return "";
  return `Paused for ${Math.max(1, Math.ceil((until - now) / 60000))} min`;
}

/** The one banner worth showing above the faceplate, or null. `cls` is "bad" or "warn". */
export function statusBanner(summary) {
  if (!summary) return null;
  if (!summary.configured) return { cls: "warn", text: "Not configured: set the switch address and password in Settings." };
  if (summary.reachable === false) return { cls: "bad", text: "Unreachable: the switch is not answering." };
  if (summary.login === "failed") return { cls: "bad", text: "Login failed: the switch refused the password. Press Test connection in Settings." };
  if (summary.login === "paused") {
    return summary.pause_reason === "another_login"
      ? { cls: "warn", text: "Paused: another login. Someone else is using the switch's web interface, so polling stopped to leave it alone." }
      : { cls: "warn", text: "Paused: polling is stopped until you resume it." };
  }
  const sw = summary.switch;
  if (sw && sw.firmware_tested === false) {
    return { cls: "warn", text: `Untested firmware${sw.firmware ? " " + sw.firmware : ""}: pages may read incorrectly. Tested on V1.6.0.11.` };
  }
  return null;
}

const VLAN_MODES = {
  off: "Off",
  basic_8021q: "Basic 802.1Q",
  advanced_8021q: "Advanced 802.1Q",
  basic_port: "Basic port-based",
  advanced_port: "Advanced port-based",
};
const QOS_MODES = { port: "Port-based priority", dot1p: "802.1p/DSCP" };
const MGMT_MODES = { web: "Web only", web_and_utility: "Web and Plus Utility" };

const yesNo = (v) => (v ? "on" : "off");

/** Configuration sections in spec order. `ports` (the /ports list) supplies descriptions; `summary` the Switch section. */
export function configSectionsHtml(config, esc, ports = [], summary = null) {
  const desc = new Map((ports || []).map((p) => [p.port, p.description || ""]));
  const field = (k, v) => `<div><dt>${esc(k)}</dt><dd>${esc(v == null || v === "" ? DASH : v)}</dd></div>`;
  const dl = (...fields) => `<dl class="g5e-fields">${fields.join("")}</dl>`;
  const section = (title, body) => `<section class="card g5e-cfg" aria-label="${esc(title)}"><h2>${esc(title)}</h2>${body}</section>`;
  const unread = `<p class="sub">not read yet</p>`;
  const cfg = config || {};
  const portName = (n) => (desc.get(n) ? `${n} (${desc.get(n)})` : String(n));
  const table = (head, rows) =>
    `<div class="tablewrap"><table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows
      .map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`)
      .join("")}</tbody></table></div>`;

  const out = [];

  const v = cfg.vlans;
  if (!v) out.push(section("VLANs", unread));
  else if (v.mode === "off") {
    out.push(section("VLANs", `<p><b>VLANs off</b></p><p class="sub">Default VLAN ${esc((v.vlan_ids || []).join(", ") || "1")} only.</p>`));
  } else {
    const word = { U: "untagged", T: "tagged", "": "not a member" };
    const members =
      v.shown && v.shown.members
        ? `<h3>Members of VLAN ${esc(v.shown.vid)}</h3>` +
          table(
            ["Port", "Membership"],
            v.shown.members.map((c, i) => [portName(i + 1), word[c] ?? "unknown"]),
          )
        : "";
    const pvids = (v.pvids || []).length ? `<h3>PVIDs</h3>${table(["Port", "PVID"], v.pvids.map(([p, id]) => [portName(p), id]))}` : "";
    out.push(section("VLANs", dl(field("Mode", VLAN_MODES[v.mode] || v.mode), field("VLAN ids", (v.vlan_ids || []).join(", "))) + members + pvids));
  }

  const q = cfg.qos;
  if (!q) out.push(section("QoS", unread));
  else {
    const limits = (q.rate_limits || []).length
      ? `<h3>Rate limits</h3>` +
        table(
          ["Port", "Ingress", "Egress"],
          q.rate_limits.map((r) => [
            portName(r.port),
            r.ingress_kbps == null ? "no limit" : `${r.ingress_kbps} kbit/s`,
            r.egress_kbps == null ? "no limit" : `${r.egress_kbps} kbit/s`,
          ]),
        )
      : "";
    out.push(section("QoS", dl(field("Mode", QOS_MODES[q.mode] || q.mode)) + limits));
  }

  const g = cfg.igmp;
  out.push(
    section(
      "Multicast",
      g
        ? dl(
            field("IGMP snooping", yesNo(g.enabled)),
            field("VLAN", g.vlan),
            field("Validate IGMPv3 header", yesNo(g.validate_v3_header)),
            field("Block unknown multicast", yesNo(g.block_unknown)),
            field("Router port", g.router_port),
          )
        : unread,
    ),
  );

  const m = cfg.mirror;
  out.push(
    section(
      "Mirroring",
      !m
        ? unread
        : m.enabled
          ? dl(field("Mirroring", "on"), field("Destination port", m.destination), field("Source ports", (m.sources || []).join(", ")))
          : dl(field("Mirroring", "off")),
    ),
  );

  out.push(section("Storm control", q ? dl(field("Broadcast filtering", yesNo(q.storm_control))) : unread));

  const mg = cfg.management;
  out.push(section("Loop detection", mg ? dl(field("Loop detection", yesNo(mg.loop_detection))) : unread));

  if (!mg) out.push(section("Management", unread));
  else {
    const acl = (mg.access_list || []).length ? `<h3>Access control list</h3>${table(["Address", "Mask"], mg.access_list)}` : "";
    out.push(
      section(
        "Management",
        dl(field("Mode", MGMT_MODES[mg.mode] || mg.mode), field("TFTP via Plus Utility", yesNo(mg.tftp)), field("Power saving", yesNo(mg.power_saving))) + acl,
      ),
    );
  }

  const sw = summary && summary.switch;
  out.push(
    section(
      "Switch",
      sw
        ? dl(field("Name", sw.name), field("Model", sw.product), field("Serial", sw.serial), field("MAC", sw.mac), field("Firmware", sw.firmware), field("Bootloader", sw.bootloader), field("Addressing", sw.dhcp == null ? null : sw.dhcp ? "DHCP" : "static"), field("IP address", sw.ip), field("Subnet mask", sw.mask), field("Gateway", sw.gateway))
        : unread,
    ),
  );
  return out.join("");
}

/** What the legend of the VLAN view lists: each PVID in use with its port count. */
function vlanLegend(ports) {
  const counts = new Map();
  for (const p of ports) if (p.pvid != null) counts.set(p.pvid, (counts.get(p.pvid) || 0) + 1);
  const colors = vlanColors([...counts.keys()]);
  return { colors, vlans: [...colors.keys()].map((vid) => ({ vid, count: counts.get(vid), color: colors.get(vid) })) };
}

export function createPage(ui, store) {
  const { esc, fmtAgo, fmtRate } = ui.util;

  return {
    id: "switch",
    title: "GS105E",
    mount(el) {
      el.innerHTML = `
      <div class="g5e">
        <section class="card" aria-label="GS105E"><div id="gsHead"></div></section>
        <section class="card" aria-label="Ports">
          <div class="card-head"><h2>Ports</h2><div class="g5e-view" id="gsView" role="group" aria-label="Faceplate view"></div></div>
          <div class="g5e-faceplate-scroll" id="gsGrid"></div>
          <div id="gsLegend" class="g5e-legend"></div>
        </section>
        <section class="card" id="gsDetailCard" aria-label="Port detail" aria-live="polite"><div id="gsDetail"></div></section>
        <section class="card" id="gsErrors" aria-label="Poll errors" hidden></section>
        <div id="gsConfig"></div>
      </div>`;
      const $ = (id) => el.querySelector("#" + id);
      let selected = null;
      let view = loadView();
      let range = "1h";
      let highlight = null;
      let lastState = null;
      let pollMsg = "";
      let requesting = false;
      let destroyed = false;
      let expiring = false;
      const samples = new Map(); // "port:range" -> {rows, at}
      let samplesSeq = 0;

      const portByNum = (n) => store.data.ports.find((p) => p.port === Number(n)) || null;

      function renderHead() {
        const s = store.data.summary;
        const sw = s && s.switch;
        let status = "";
        if (store.data.error) status = `<span class="chip bad">⚠ ${esc(store.data.error)}</span>`;
        else if (s && s.reachable === true) status = `<span class="chip ok">✓ Reachable</span>`;
        else if (s && s.reachable === false) status = `<span class="chip bad">⚠ Unreachable</span>`;
        else if (s && s.configured) status = `<span class="chip">Not polled yet</span>`;
        const info = sw
          ? `<span class="chip"><b>${esc(sw.name || "GS105E")}</b></span><span class="chip">${esc(sw.product || "model unknown")}</span>` +
            `<span class="chip">firmware <b>${esc(sw.firmware || DASH)}</b></span>`
          : "";
        const last = s && s.last_poll_ms ? `<span class="sub">polled ${esc(fmtAgo(s.last_poll_ms))}</span>` : "";
        const paused = !!(s && s.login === "paused");
        const b = pollButtonState(s, requesting);
        const banner = statusBanner(s);
        $("gsHead").innerHTML =
          `<div class="card-head"><h2>NETGEAR GS105E</h2>${info}${status}${last}` +
          `<button type="button" class="small" id="gsPause" aria-pressed="${paused}"${s && s.configured ? "" : " disabled"}>${paused ? "Resume" : "Pause"}</button>` +
          `<span class="sub" id="gsPauseNote" role="status">${esc(pauseLabel(s, Date.now()))}</span>` +
          `<button type="button" class="primary small" id="gsPoll" title="${esc(b.title)}"${b.disabled || !(s && s.configured) ? " disabled" : ""}>${esc(b.label)}</button>` +
          `<span class="err" id="gsPollMsg" role="status">${esc(pollMsg)}</span></div>` +
          (banner ? `<p class="g5e-banner ${banner.cls}" role="status"><span aria-hidden="true">${banner.cls === "bad" ? "⚠" : "⏸"}</span> ${esc(banner.text)}</p>` : "");
      }

      function renderGrid() {
        const grid = $("gsGrid");
        const active = document.activeElement;
        const focused = active && grid.contains(active) && active.dataset ? active.dataset.port : null;
        const ports = store.data.ports;
        const s = store.data.summary;
        $("gsView").innerHTML = ports.length
          ? VIEWS.map(
              ([id, label]) =>
                `<button type="button" class="${view === id ? "primary" : "quiet"} small" data-view="${id}" aria-pressed="${view === id}">${label}</button>`,
            ).join("")
          : "";
        if (!ports.length) {
          grid.innerHTML = `<p class="sub">No port data yet.</p>`;
          $("gsLegend").innerHTML = "";
          return;
        }
        const legend = vlanLegend(ports);
        const cfg = store.data.config;
        const shown = cfg && cfg.vlans && cfg.vlans.shown ? cfg.vlans.shown.vid : null;
        const dot = s && s.reachable === true ? "ok" : s && s.reachable === false ? "bad" : "idle";
        const dotWord = dot === "ok" ? "reachable" : dot === "bad" ? "unreachable" : "not polled yet";
        grid.innerHTML =
          `<div class="g5e-faceplate"><img src="${esc(FACE_SRC)}" alt="" draggable="false">` +
          `<span class="g5e-pdot ${dot}" style="${powerDotStyle()}" title="Power LED: switch ${esc(dotWord)}" aria-hidden="true"></span>` +
          ports.map((p) => jackHtml(p, esc, view, legend.colors, shown)).join("") +
          `</div>`;
        const cells = [...grid.querySelectorAll("[data-port]")];
        for (const b of cells) if (Number(b.dataset.port) === selected) b.setAttribute("aria-pressed", "true");
        if (focused) {
          const again = cells.find((b) => b.dataset.port === focused);
          if (again) again.focus();
        }
        if (view === "vlan") {
          if (!legend.vlans.some((v) => v.vid === highlight)) highlight = null;
          const plural = (n) => `${n} port${n === 1 ? "" : "s"}`;
          const off = cfg && cfg.vlans && cfg.vlans.mode === "off";
          $("gsLegend").innerHTML =
            (off ? `<span>VLANs off: every port is in the default VLAN</span>` : "") +
            legend.vlans
              .map(
                (v) =>
                  `<button type="button" class="g5e-vl" data-vid="${esc(v.vid)}" title="Highlight every port with PVID ${esc(v.vid)}">` +
                  `<i style="background:${esc(v.color)}"></i>PVID ${esc(v.vid)} · ${esc(plural(v.count))}</button>`,
              )
              .join("") +
            (shown != null ? `<span>T: tagged in VLAN ${esc(shown)}</span>` : "") +
            `<span>number: PVID</span>`;
        } else {
          highlight = null;
          $("gsLegend").innerHTML =
            `<span>both LEDs: 1G</span><span>left LED: 100M</span><span>right LED: 10M</span>` +
            `<span>— link down</span><span>⦸ admin disabled</span><span>⇄ mirror source (src) or destination (dst)</span><span>bar: utilisation</span>`;
        }
        applyHighlight();
      }

      function applyHighlight() {
        for (const j of $("gsGrid").querySelectorAll("button.g5e-jack")) {
          const p = portByNum(j.dataset.port);
          j.classList.toggle("dim", highlight != null && !(p && p.pvid === highlight));
        }
      }

      function setHighlight(e, on) {
        const chip = e.target.closest("[data-vid]");
        const next = on && chip ? Number(chip.dataset.vid) : null;
        if (next === highlight) return;
        highlight = next;
        applyHighlight();
      }

      function renderDetail() {
        const box = $("gsDetail");
        const p = selected && portByNum(selected);
        if (!p) {
          box.innerHTML = `<p class="sub">Select a port to see its details.</p>`;
          return;
        }
        const st = portState(p);
        const field = (k, v) => `<div><dt>${esc(k)}</dt><dd>${esc(v == null || v === "" ? DASH : v)}</dd></div>`;
        const rate = (v) => (v == null ? DASH : fmtRate(v));
        const limit = (v) => (v == null ? "no limit" : `${v} kbit/s`);
        const member = { U: "untagged", T: "tagged", "": "not a member" }[p.vlan_member ?? ""] ?? "unknown";
        const shown = store.data.config && store.data.config.vlans && store.data.config.vlans.shown;
        const symbol = st.cls === "up" ? "▲" : st.cls === "disabled" ? "⦸" : "▼";
        box.innerHTML =
          `<div class="card-head"><h2>Port ${esc(p.port)}</h2><span class="chip">${symbol} ${esc(st.words)}</span>` +
          (p.mirror ? `<span class="chip accent">⇄ mirror ${esc(p.mirror)}</span>` : "") +
          `<button type="button" class="quiet small" id="gsClose">Close</button></div>` +
          `<dl class="g5e-fields">` +
          field("Description", p.description) +
          field("Link speed", p.up ? speedShort(p.link_mbps) : DASH) +
          field("Configured speed", p.speed_setting) +
          field("Flow control", p.flow_control ? "on" : "off") +
          field("In", rate(p.in_bps)) +
          field("Out", rate(p.out_bps)) +
          field("Utilisation", p.util_percent == null ? DASH : `${p.util_percent.toFixed(1)} %`) +
          field("CRC errors", p.crc_errors) +
          field("CRC errors, last interval", p.crc_delta) +
          field("PVID", p.pvid) +
          field(shown ? `VLAN ${shown.vid}` : "VLAN membership", p.vlan_member == null ? DASH : member) +
          field("Ingress limit", limit(p.ingress_kbps)) +
          field("Egress limit", limit(p.egress_kbps)) +
          field("Max MTU", p.max_mtu) +
          field("Mirroring", p.mirror || "none") +
          `</dl>` +
          `<div class="card-head"><h3>Traffic</h3><div class="g5e-view" id="gsRange" role="group" aria-label="Chart range">` +
          RANGES.map(
            ([id, label]) =>
              `<button type="button" class="${range === id ? "primary" : "quiet"} small" data-range="${id}" aria-pressed="${range === id}">${label}</button>`,
          ).join("") +
          `</div></div><div class="g5e-chart" id="gsPortChart"></div>`;
        drawPortChart();
      }

      function drawPortChart() {
        const box = $("gsPortChart");
        if (!box || !selected) return;
        const have = samples.get(`${selected}:${range}`);
        const label = RANGES.find((r) => r[0] === range)[1];
        ui.util.lineChart(box, {
          label: `Port ${selected} traffic, last ${label}`,
          series: portChartSeries(have ? have.rows : null),
          fmt: fmtRate,
        });
      }

      function loadSamples() {
        if (!selected) return;
        const port = selected;
        const r = RANGES.find((x) => x[0] === range);
        const key = `${port}:${range}`;
        const have = samples.get(key);
        if (have && Date.now() - have.at < SAMPLES_GAP_MS) return;
        const seq = ++samplesSeq;
        const to = Date.now();
        // stamp first so the many store refreshes do not each start a fetch
        samples.set(key, { rows: have ? have.rows : [], at: to });
        ui.apiGet(`${ui.apiBase}/ports/${port}/samples?from_ms=${to - r[2]}&to_ms=${to}&resolution=${r[3]}`)
          .then((rows) => {
            samples.set(key, { rows, at: Date.now() });
            if (seq !== samplesSeq || destroyed || selected !== port || range !== r[0]) return;
            drawPortChart();
          })
          .catch(() => samples.delete(key));
      }

      function renderErrors() {
        const s = store.data.summary;
        const errors = s && s.errors ? Object.entries(s.errors) : [];
        const box = $("gsErrors");
        box.hidden = !errors.length;
        box.innerHTML = errors.length
          ? `<h2>Poll errors</h2><ul class="g5e-devs">${errors.map(([g, t]) => `<li><b>${esc(g)}</b>: ${esc(t)}</li>`).join("")}</ul>`
          : "";
      }

      function renderConfig() {
        $("gsConfig").innerHTML = configSectionsHtml(store.data.config, esc, store.data.ports, store.data.summary);
      }

      function renderAll() {
        if (destroyed) return;
        renderHead();
        renderGrid();
        renderDetail();
        renderErrors();
        renderConfig();
      }

      function select(n) {
        n = Number(n);
        selected = selected === n ? null : n;
        renderGrid();
        renderDetail();
        loadSamples();
      }

      /** After this page's own POST the server polls on a thread: look again until it has finished (at most a minute). */
      async function waitForPoll() {
        const until = Date.now() + POLL_WAIT_MS;
        do {
          await new Promise((r) => setTimeout(r, POLL_CHECK_MS));
          if (destroyed) return;
          await store.refresh(true);
        } while (store.data.summary && store.data.summary.polling && Date.now() < until);
      }

      async function pollNow() {
        if (pollButtonState(store.data.summary, requesting).disabled) return;
        requesting = true;
        pollMsg = "";
        renderHead();
        try {
          await ui.apiSend("POST", `${ui.apiBase}/poll`, {});
        } catch (err) {
          // 409 with "poll already running": wait for that one. Any other 409 reason is shown as it is.
          if (err.status !== 409 || err.message !== "poll already running") {
            pollMsg = err.message;
            requesting = false;
            if (!destroyed) renderHead();
            return;
          }
        }
        await waitForPoll();
        requesting = false;
        if (!destroyed) renderHead();
      }

      async function togglePause() {
        const s = store.data.summary;
        const paused = !!(s && s.login === "paused");
        pollMsg = "";
        try {
          await ui.apiSend(paused ? "DELETE" : "POST", `${ui.apiBase}/pause`, paused ? undefined : {});
        } catch (err) {
          pollMsg = err.message;
        }
        await store.refresh(true);
        if (paused && !destroyed) {
          // resuming: the next poll job may already be running
          await waitForPoll();
        }
        if (!destroyed) renderHead();
      }

      el.querySelector(".g5e").addEventListener("click", (e) => {
        const cell = e.target.closest("[data-port]");
        if (cell && $("gsGrid").contains(cell)) return select(cell.dataset.port);
        const viewBtn = e.target.closest("#gsView [data-view]");
        if (viewBtn) {
          view = viewBtn.dataset.view;
          saveView(view);
          renderGrid();
          const again = $("gsView").querySelector(`[data-view="${view}"]`);
          if (again) again.focus();
          return;
        }
        const rangeBtn = e.target.closest("#gsRange [data-range]");
        if (rangeBtn) {
          range = rangeBtn.dataset.range;
          renderDetail();
          const again = $("gsRange").querySelector(`[data-range="${range}"]`);
          if (again) again.focus();
          loadSamples();
          return;
        }
        if (e.target.closest("#gsClose")) return select(selected);
        if (e.target.closest("#gsPoll")) return pollNow();
        if (e.target.closest("#gsPause")) return togglePause();
      });
      for (const [type, on] of [["mouseover", true], ["focusin", true], ["mouseout", false], ["focusout", false]]) {
        $("gsLegend").addEventListener(type, (e) => setHighlight(e, on));
      }

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
        loadSamples();
      });
      const timer = setInterval(() => {
        if (document.visibilityState !== "visible") return;
        store.refresh();
      }, REFRESH_MS);
      // the pause countdown; when a pause runs out, fetch once so the button and banner change
      const countdown = setInterval(() => {
        const s = store.data.summary;
        const note = $("gsPauseNote");
        if (!s || !note) return;
        note.textContent = pauseLabel(s, Date.now());
        if (s.paused_until_ms != null && s.paused_until_ms <= Date.now() && !expiring) {
          expiring = true;
          store.refresh(true).finally(() => {
            expiring = false;
          });
        }
      }, 1000);

      renderAll();
      store.refresh(true);

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
          clearInterval(countdown);
          clearTimeout(recheck);
          unsubscribe();
        },
      };
    },
  };
}
