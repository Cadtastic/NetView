// GS105E UI module: registers the dashboard tile, the Switch page, the device report section and the
// "Connection" settings section. All data comes from one small store so the slots share their fetches.
import { createPage } from "./page.js";
import { drawReport, reportModel } from "./report.js";

const MIN_GAP_MS = 10000;

/** Shared data for every slot. `refresh` fetches summary, ports and config, at most once per 10 s unless forced. */
export function createStore(ui, now = Date.now) {
  const store = {
    // receivedAt: browser time the summary arrived, so a page mounted later still counts a pause down from then
    data: { summary: null, ports: [], config: null, error: null, receivedAt: null },
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
        ui.apiGet(`${ui.apiBase}/config`),
      ])
        .then(([summary, ports, config]) => {
          store.data = { summary, ports, config, error: null, receivedAt: now() };
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
  };
  let loading = false;
  let startedAt = -Infinity;
  return store;
}

/** Inner HTML of the dashboard tile (the shell wraps it in `.tile`). Bad states carry a symbol and a word. */
export function tileHtml(summary, esc, fmtRate) {
  return `<div class="g5e-tile">${tileInner(summary, esc, fmtRate)}</div>`;
}

function tileInner(summary, esc, fmtRate) {
  const k = `<div class="k">GS105E</div>`;
  if (!summary) return `${k}<div class="v">–</div><div class="s">loading</div>`;
  if (!summary.configured) return `${k}<div class="v">–</div><div class="s">Set up in Settings</div>`;
  if (summary.reachable === false) {
    const why = summary.errors && Object.values(summary.errors)[0];
    return `${k}<div class="v bad"><span aria-hidden="true">⚠</span> Unreachable</div><div class="s">${esc(why || "no answer from the switch")}</div>`;
  }
  if (summary.login === "failed") {
    return `${k}<div class="v bad"><span aria-hidden="true">⚠</span> Login failed</div><div class="s">Press Test connection in Settings</div>`;
  }
  if (summary.login === "paused") {
    const why = summary.pause_reason === "another_login" ? "another login" : "paused by you";
    return `${k}<div class="v warn"><span aria-hidden="true">⏸</span> Paused</div><div class="s">${esc(why)}</div>`;
  }
  if (!summary.switch) return `${k}<div class="v">–</div><div class="s">waiting for the first poll</div>`;
  const t = summary.throughput_bps;
  const rate = (v) => (t ? esc(fmtRate(v)) : "–");
  return (
    `${k}<div class="v">${esc(summary.ports.up)}<small>of ${esc(summary.ports.total)} ports up</small></div>` +
    `<div class="s">↓ ${rate(t && t.in)}  ↑ ${rate(t && t.out)}</div>`
  );
}

/** The "Connection" settings section: a button that tests the stored settings. It never touches secret fields. */
export function renderConnection(body, { apiBase, apiSend }) {
  body.innerHTML =
    `<div class="g5e-conn"><p class="sub">Logs in to the switch with the saved settings. Save changes first.</p>` +
    `<div class="formfoot"><button type="button" class="small" data-act="test">Test connection</button>` +
    `<span class="err" role="status" aria-live="polite"></span></div></div>`;
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
        out.textContent = `✓ Connected: ${r.product || "switch"}, firmware ${r.firmware || "unknown"}${r.name ? ` (${r.name})` : ""}`;
      } else {
        out.textContent = "⚠ " + ((r && r.error) || "failed");
      }
    } catch (e) {
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
    link.href = `/plugins/${ui.pluginId}/static/gs105e.css`;
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

  ui.slot("report.live-section", {
    id: "gs105e-summary",
    draw(box, { ip }) {
      store.refresh();
      drawReport(box, reportModel(store.data.summary, ip, ui.util.fmtRate, ui.pluginId));
    },
  });

  ui.slot("settings.section", { title: "Test the connection", tab: "Connection", render: renderConnection });
}
