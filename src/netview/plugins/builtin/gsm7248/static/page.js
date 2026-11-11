// The Switch page: header, faceplate, port detail and the VLAN / MAC / spanning tree / LAG / inventory sections.
import { faceplateLayout, fmtUptime, portCellHtml, portSortKey, portState, speedShort } from "./port-grid.js";

const REFRESH_MS = 15000;

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
          <div class="faceplate-scroll" id="gsGrid"></div>
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
      let detail = null; // /ports/{name} for the selected port
      let detailSeq = 0;
      let filter = "";
      let lastState = null;
      let pollMsg = "";
      let polling = false;
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
          `<button type="button" class="primary small" id="gsPoll"${polling ? " disabled" : ""}>Poll now</button>` +
          `<span class="err" id="gsPollMsg" role="status">${esc(pollMsg)}</span></div>`;
      }

      function renderGrid() {
        const grid = $("gsGrid");
        const active = document.activeElement;
        const focused = active && grid.contains(active) && active.dataset ? active.dataset.port : null;
        const ports = store.data.ports;
        if (!ports.length) {
          grid.innerHTML = `<p class="sub">No port data yet.</p>`;
          $("gsLegend").innerHTML = "";
          return;
        }
        const f = faceplateLayout(ports);
        const row = (list) => `<div class="gs-row">${list.map((p) => portCellHtml(p, esc)).join("")}</div>`;
        grid.innerHTML =
          `<div class="faceplate">${row(f.top)}${row(f.bottom)}</div>` +
          (f.extra.length ? `<div class="gs-extra"><span class="sub">Other interfaces</span>${row(f.extra)}</div>` : "");
        const cells = [...grid.querySelectorAll("[data-port]")];
        for (const b of cells) if (b.dataset.port === selected) b.setAttribute("aria-pressed", "true");
        if (focused) {
          const again = cells.find((b) => b.dataset.port === focused);
          if (again) again.focus();
        }
        $("gsLegend").innerHTML =
          `<span>▲ link up</span><span>▼ link down</span><span>⦸ admin disabled</span><span>⏸ STP blocking</span><span>bar: utilisation</span>`;
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
      }

      function renderVlans() {
        const rows = store.data.vlans;
        $("gsVlans").innerHTML = rows.length
          ? `<table><thead><tr><th>VLAN</th><th>Name</th><th>Untagged</th><th>Tagged</th></tr></thead><tbody>` +
            rows
              .map((v) => `<tr><td>${esc(v.vid)}</td><td>${esc(v.name || "")}</td><td>${esc(v.untagged.join(", ") || "–")}</td><td>${esc(v.tagged.join(", ") || "–")}</td></tr>`)
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
        const rows = store.data.ports.filter((p) => p.kind === "ethernet" && p.stp_state);
        $("gsStp").innerHTML = rows.length
          ? `<table><thead><tr><th>Port</th><th>Link</th><th>STP state</th></tr></thead><tbody>` +
            rows
              .map((p) => {
                const st = portState(p);
                return `<tr><td>${esc(p.name)}</td><td>${st.symbol} ${esc(st.words)}</td><td>${esc(p.stp_state)}</td></tr>`;
              })
              .join("") +
            `</tbody></table>`
          : `<p class="sub">No spanning tree data yet.</p>`;
      }

      function renderLags() {
        const lags = store.data.ports.filter((p) => p.kind === "lag");
        $("gsLags").innerHTML = lags.length
          ? `<ul class="gs-devs">` +
            lags
              .map((g) => {
                const members = store.data.ports.filter((p) => p.lag === g.name).map((p) => p.name);
                return `<li><b>${esc(g.name)}</b> ${esc(portState(g).words)}: ${esc(members.join(", ") || "no members")}</li>`;
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
        const field = (k, v) => `<div><dt>${esc(k)}</dt><dd>${esc(v ?? "–")}</dd></div>`;
        const mem = h.mem_free_kb != null && h.mem_total_kb ? `${Math.round(h.mem_free_kb / 1024)} of ${Math.round(h.mem_total_kb / 1024)} MB` : null;
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

      function select(name) {
        selected = selected === name ? null : name;
        detail = null;
        renderGrid();
        renderDetail();
        loadDetail();
      }

      async function pollNow() {
        if (polling) return;
        polling = true;
        pollMsg = "";
        renderHead();
        try {
          await ui.apiSend("POST", `${ui.apiBase}/poll`, {});
          pollMsg = "Polling…";
          // the poll finishes after the 202; fetch again shortly
          setTimeout(() => store.refresh(true), 2500);
          setTimeout(() => store.refresh(true), 8000);
        } catch (err) {
          pollMsg = err.message;
        } finally {
          polling = false;
          if (!destroyed) renderHead();
        }
      }

      // on the page's own root: `el` is the shell's shared view element and outlives this page
      el.querySelector(".gsw").addEventListener("click", (e) => {
        const cell = e.target.closest("[data-port]");
        if (cell && $("gsGrid").contains(cell)) return select(cell.dataset.port);
        if (e.target.closest("#gsClose")) return select(selected);
        if (e.target.closest("#gsPoll")) return pollNow();
      });
      $("gsMacFilter").addEventListener("input", (e) => {
        filter = e.target.value;
        renderMacs();
      });

      const unsubscribe = store.subscribe(() => {
        if (pollMsg === "Polling…") pollMsg = "";
        renderAll();
        loadDetail();
      });
      const timer = setInterval(() => {
        if (document.visibilityState === "visible") store.refresh();
      }, REFRESH_MS);

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
          unsubscribe();
        },
      };
    },
  };
}
