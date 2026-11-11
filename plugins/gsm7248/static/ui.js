// GSM7248 UI module: registers the dashboard tile, the Switch page, the Devices "Switch port" column and the
// "Connection" settings section. All data comes from one small store so the slots share their fetches.
import { createPage } from "./page.js";
import { portSortKey } from "./port-grid.js";
import { drawReport, reportModel } from "./report.js";

const MIN_GAP_MS = 10000;
const REPORT_GAP_MS = 15000;

/** Shared data for every slot. `refresh` fetches summary, ports, MACs and VLANs, at most once per 10 s unless forced. */
export function createStore(ui, now = Date.now) {
  const store = {
    data: { summary: null, ports: [], macs: [], vlans: [], error: null },
    subscribers: new Set(),
    subscribe(fn) {
      store.subscribers.add(fn);
      return () => store.subscribers.delete(fn);
    },
    refresh(force = false) {
      if (loading || (!force && now() - startedAt < MIN_GAP_MS)) return Promise.resolve();
      loading = true;
      startedAt = now();
      return Promise.all([
        ui.apiGet(`${ui.apiBase}/summary`),
        ui.apiGet(`${ui.apiBase}/ports`),
        ui.apiGet(`${ui.apiBase}/macs`),
        ui.apiGet(`${ui.apiBase}/vlans`),
      ])
        .then(([summary, ports, macs, vlans]) => {
          store.data = { summary, ports, macs, vlans, error: null };
          macMap = buildMacMap(macs);
        })
        .catch((e) => {
          // keep the last good data on screen
          store.data = { ...store.data, error: e && e.message ? e.message : String(e) };
        })
        .finally(() => {
          loading = false;
          for (const fn of [...store.subscribers]) fn();
          ui.requestRender();
        });
    },
    /** The switch attachment of a device's MAC: `{port, via}` or null. */
    attachment(mac) {
      return (mac && macMap.get(String(mac).toLowerCase())) || null;
    },
  };
  let loading = false;
  let startedAt = -Infinity;
  let macMap = new Map();
  return store;
}

/** MAC to `{port, via}`. A port the device is directly on beats an uplink port it was seen through. */
export function buildMacMap(macs) {
  const map = new Map();
  for (const m of macs) {
    if (!m.port) continue;
    const key = String(m.mac).toLowerCase();
    const have = map.get(key);
    if (have && !have.via) continue;
    if (have && have.via && m.via_uplink) continue;
    map.set(key, { port: m.port, via: !!m.via_uplink });
  }
  return map;
}

/** Inner HTML of the dashboard tile (the shell wraps it in `.tile`). */
export function tileHtml(summary, esc, fmtRate) {
  const k = `<div class="k">Switch</div>`;
  if (!summary) return `${k}<div class="v">–</div><div class="s">loading</div>`;
  if (!summary.configured) return `${k}<div class="v">–</div><div class="s">Set up in Settings</div>`;
  if (summary.reachable === false) {
    return `${k}<div class="v word bad"><span aria-hidden="true">⚠</span> Unreachable</div><div class="s">${esc(summary.last_error || "no answer from the switch")}</div>`;
  }
  if (!summary.switch) {
    if (summary.last_error) {
      return `${k}<div class="v word bad"><span aria-hidden="true">⚠</span> Error</div><div class="s">${esc(summary.last_error)}</div>`;
    }
    return `${k}<div class="v">–</div><div class="s">waiting for the first poll</div>`;
  }
  const t = summary.throughput_bps || { in: 0, out: 0 };
  const cpu = summary.health && summary.health.cpu_percent != null ? `, CPU ${esc(summary.health.cpu_percent)}%` : "";
  return (
    `${k}<div class="v">${esc(summary.ports.up)}<small>of ${esc(summary.ports.total)} ports up</small></div>` +
    `<div class="s">↓ ${esc(fmtRate(t.in))}  ↑ ${esc(fmtRate(t.out))}${cpu}</div>`
  );
}

/**
 * Whether the switch can be shown as a source of device ports: the plugin is answering, set up, and its last
 * poll reached the switch. False before the first successful poll, while the switch is unreachable, and once the
 * plugin's API stops answering (the plugin was turned off).
 */
export function switchAvailable(data) {
  const s = data && data.summary;
  return !!s && !data.error && s.configured === true && s.reachable === true;
}

/** The "Connection" settings section: a button that tests the stored settings. It never touches secret fields. */
export function renderConnection(body, { apiBase, apiSend, util }) {
  body.innerHTML =
    `<p class="sub">Tests the saved settings. Save changes first.</p>` +
    `<div class="formfoot"><button type="button" class="small" data-act="test">Test connection</button>` +
    `<span class="err" role="status" aria-live="polite"></span></div>`;
  const btn = body.querySelector("[data-act=test]");
  const out = body.querySelector(".err");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    out.classList.remove("ok");
    out.textContent = "Testing…";
    try {
      const r = await apiSend("POST", apiBase + "/test", {});
      if (r && r.ok === "true") {
        out.classList.add("ok");
        out.textContent = "✓ Connected: " + (r.sys_descr || "no description");
      } else {
        out.textContent = "⚠ " + ((r && r.error) || "failed");
      }
    } catch (e) {
      out.textContent = "⚠ " + (e && e.message ? e.message : "failed");
    } finally {
      btn.disabled = false;
    }
  });
  void util;
}

/**
 * What the SSH test says for a POST /console/probe answer: `{ok, text}`. SSH works in three of the five states;
 * only "connected" also proves the serial line.
 */
export function sshTestResult(info) {
  const s = info && info.status;
  if (!s) return { ok: false, text: "⚠ No result" };
  const firstLine = String(s.text || "").split("\n")[0];
  if (s.state === "connected") return { ok: true, text: `✓ SSH works and the switch answered${firstLine ? `: ${firstLine}` : ""}` };
  if (s.state === "in_use") return { ok: true, text: `✓ SSH works. ${s.detail}, so the serial line was not tested` };
  if (s.state === "silent") return { ok: false, text: `⚠ SSH works, but the serial line is silent. ${s.detail}` };
  if (s.state === "no_device") return { ok: false, text: `⚠ SSH works, but ${s.detail}` };
  return { ok: false, text: `⚠ ${s.detail || "SSH failed"}` };
}

/** The SSH tab's test: runs the same probe as the console port on the Switch page, with the stored settings. */
export function renderSshTest(body, { apiBase, apiSend }) {
  body.innerHTML =
    `<p class="sub">Tests the saved settings. Save changes first. When SSH works, this sends one Enter to the switch's console.</p>` +
    `<div class="formfoot"><button type="button" class="small" data-act="test">Test SSH</button>` +
    `<span class="err" role="status" aria-live="polite"></span></div>`;
  const btn = body.querySelector("[data-act=test]");
  const out = body.querySelector(".err");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    out.classList.remove("ok");
    out.textContent = "Testing…";
    try {
      const r = sshTestResult(await apiSend("POST", apiBase + "/console/probe", {}));
      if (r.ok) out.classList.add("ok");
      out.textContent = r.text;
    } catch (e) {
      // 400: the console is turned off; 409: a probe is already running
      out.textContent = "⚠ " + (e && e.message ? e.message : "failed");
    } finally {
      btn.disabled = false;
    }
  });
}

export default function register(ui, now = Date.now) {
  if (typeof document !== "undefined") {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `/plugins/${ui.pluginId}/static/gsm7248.css`;
    document.head.appendChild(link);
  }
  const store = createStore(ui, now);
  let lastState = null;
  store.refresh(true);

  ui.slot("dashboard.tile", {
    render(state) {
      if (state !== lastState) {
        lastState = state;
        store.refresh();
      }
      return tileHtml(store.data.summary, ui.util.esc, ui.util.fmtRate);
    },
  });

  ui.slot("page", createPage(ui, store));

  // Every cell read asks for a throttled refresh (at most one fetch per 10 s), so the column stays current even
  // when only the Devices page is mounted; the store's requestRender() redraws the table when the fetch lands.
  const portOf = (d) => {
    store.refresh();
    return store.attachment(d.mac);
  };
  ui.slot("devices.column", {
    id: "port",
    label: "Switch port",
    // asked on every draw of the Devices page, so it also keeps the store fresh while the column is hidden
    available() {
      store.refresh();
      return switchAvailable(store.data);
    },
    text(d) {
      const a = portOf(d);
      return a ? (a.via ? `via ${a.port}` : a.port) : "";
    },
    sortKey(d) {
      const a = portOf(d);
      return portSortKey(a ? a.port : "");
    },
    groupKey(d) {
      const a = portOf(d);
      return a ? a.port : "";
    },
  });

  // The report section is redrawn on every state update, so a draw never awaits: it reads the per-port cache and
  // starts at most one fetch of the port and its samples per 15 s. The host's requestRender() does not reach the
  // report dialog, so when a fetch lands the slot repaints the last box it drew for that port itself.
  const cache = new Map(); // port name -> {detail, samples, at, loading, last}
  function paint(box, ip, device, c) {
    const a = store.attachment(device && device.mac);
    const model = reportModel(a, a && !a.via ? c && c.detail : null, a && !a.via ? c && c.samples : null, {
      ip,
      mac: device && device.mac,
      fmtAgo: ui.util.fmtAgo,
      fmtRate: ui.util.fmtRate,
    });
    drawReport(box, model, ui.util.lineChart, ui.util.fmtRate);
  }
  function reportData(port) {
    let c = cache.get(port);
    if (!c) {
      c = { detail: null, samples: null, at: -Infinity, loading: false, last: null };
      cache.set(port, c);
    }
    if (!c.loading && now() - c.at >= REPORT_GAP_MS) {
      c.loading = true;
      c.at = now();
      const url = `${ui.apiBase}/ports/${encodeURI(port)}`;
      Promise.all([ui.apiGet(url), ui.apiGet(`${url}/samples`)])
        .then(([detail, samples]) => {
          c.detail = detail;
          c.samples = samples;
        })
        .catch(() => {})
        .finally(() => {
          c.loading = false;
          ui.requestRender();
          const l = c.last;
          if (l && l.box.isConnected) paint(l.box, l.ip, l.device, c);
        });
    }
    return c;
  }
  ui.slot("report.live-section", {
    id: "gsm7248-port",
    draw(box, { ip, device }) {
      store.refresh();
      const a = store.attachment(device && device.mac);
      const c = a && !a.via ? reportData(a.port) : null;
      if (c) c.last = { box, ip, device };
      paint(box, ip, device, c);
    },
  });

  // each connection's test sits on that connection's settings tab (the tab names are in settings.py)
  ui.slot("settings.section", { title: "Test the SNMP connection", tab: "SNMP", render: renderConnection });
  ui.slot("settings.section", { title: "Test the SSH connection", tab: "SSH", render: renderSshTest });
}
