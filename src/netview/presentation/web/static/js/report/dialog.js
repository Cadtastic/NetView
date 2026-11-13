// Report dialog: live sections, then the stored (or freshly run) inspection report, section by section.
// Everything in a report can come from a device, so it reaches the page through textContent or esc().
import { apiGet, apiSend } from "../api.js";
import { esc } from "../util.js";

let env = { host: null, getState: () => null, refresh: () => {}, getAuth: () => null, getPlugins: () => [] };
let run = 0; // bumped whenever the dialog is opened or a run starts, so a late answer for an older one is ignored
let current = null; // {ip, opener, live: [{spec, el}]}

/** main.js hands over the UI host (for the section specs), the state accessor and a refresh callback. */
export function configureReport(options) {
  env = { ...env, ...options };
}

// ---------- pure helpers

/** The report.section spec that draws `section`, matched on plugin guid and section id; null when there is none. */
export function matchSection(specs, section) {
  return specs.find((s) => s.section === section.id && s.pluginGuid === section.plugin_id) || null;
}

/** The heading of a section. A failed section is stored with its plugin's guid as the title, so it shows the
 * plugin's display name when that plugin is loaded; every other section keeps the title it was stored with. */
export function sectionTitle(section, plugins) {
  if (!section.error) return section.title;
  const owner = (plugins || []).find((p) => p.guid === section.plugin_id);
  return (owner && owner.display_name) || section.title;
}

const isScalar = (v) => v === null || ["string", "number", "boolean"].includes(typeof v);

/** The fallback section: a heading and a definition list of the top-level scalar data, minus `text`. */
export function genericSectionHtml(section, title = section.title) {
  const head = `<h3>${esc(title)}</h3>`;
  if (section.error) return `${head}<p class="err">This section failed: ${esc(section.error)}</p>`;
  const rows = Object.entries(section.data || {}).filter(([k, v]) => k !== "text" && isScalar(v));
  if (!rows.length) return head;
  return `${head}<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v === null ? "–" : v)}</dd>`).join("")}</dl>`;
}

/** What the dialog says while an inspection runs. */
export function runningText(ip, ports) {
  const scope = ports === "all" ? "all 65,535 TCP ports" : "about 1,100 TCP ports";
  const time = ports === "all" ? "about a minute" : "about 10 seconds";
  return `Inspecting ${ip}: ${scope}, web pages, certificates, mDNS, NetBIOS and UPnP, ${time}…`;
}

/** What the dialog says when loading or running fails. */
export function failureText(err) {
  if (err && err.status === 409) return "No inspection plugin is turned on.";
  return `Inspection failed: ${(err && err.message) || "unknown error"}`;
}

// ---------- the dialog

const $ = (sel) => document.querySelector(`#report ${sel}`);

function deviceFor(ip) {
  const state = env.getState();
  return (state && state.devices.find((d) => d.ip === ip)) || null;
}

/** Run again and All ports start scans, so they are for people who hold core.scan. */
export function canRerun(auth) {
  return !auth || auth.can("core.scan");
}

function setBusy(busy) {
  $("[data-run]").disabled = busy;
  $("[data-all]").disabled = busy;
}

function setStatus(text, isError = false) {
  const el = $("#report-status");
  el.textContent = text;
  el.className = isError ? "err" : "note";
}

function errorBox(el, what, e) {
  console.error(what, e);
  el.textContent = "";
  const p = document.createElement("p");
  p.className = "err";
  p.textContent = `This section failed: ${e && e.message ? e.message : e}`;
  el.appendChild(p);
}

function drawLive(state) {
  if (!current) return;
  const device = deviceFor(current.ip);
  for (const { spec, el } of current.live) {
    try {
      spec.draw(el, { ip: current.ip, device, state });
    } catch (e) {
      errorBox(el, `Plugin "${spec.pluginId}" live section failed`, e);
    }
  }
}

function setTitle() {
  const device = deviceFor(current.ip);
  $("#report-title").textContent = (device && device.display_name) || current.ip;
}

function showReport(report) {
  const sub = $("#report-sub");
  sub.textContent = "";
  const addr = document.createElement("span");
  addr.className = "addr";
  addr.textContent = current.ip;
  const when = document.createElement("span");
  when.textContent = `Checked ${new Date(report.finished_ms).toLocaleString()}`;
  sub.append(addr, when);
  setStatus("");
  const box = $("#report-sections");
  box.textContent = "";
  const specs = env.host ? env.host.get("report.section") : [];
  for (const section of report.sections || []) {
    const el = document.createElement("section");
    el.className = "rsec";
    el.setAttribute("data-plugin", section.plugin_id);
    el.setAttribute("data-section", section.id);
    box.appendChild(el);
    const spec = section.error ? null : matchSection(specs, section);
    if (!spec) {
      el.innerHTML = genericSectionHtml(section, sectionTitle(section, env.getPlugins())); // every value escaped in genericSectionHtml
      continue;
    }
    try {
      spec.draw(el, section, report);
    } catch (e) {
      errorBox(el, `Plugin "${spec.pluginId}" report section failed`, e);
    }
  }
}

/** Load the stored report (unless `fresh`), running an inspection when there is none. */
async function load(token, ip, { fresh, ports }) {
  const alive = () => token === run && document.getElementById("report").open;
  setBusy(false);
  setStatus("");
  try {
    let report = null;
    if (!fresh) {
      try {
        report = await apiGet(`/api/v1/inspections/${encodeURIComponent(ip)}`);
      } catch (e) {
        if (e.status !== 404) throw e;
      }
      if (!alive()) return;
    }
    if (!report) {
      setBusy(true);
      setStatus(runningText(ip, ports));
      report = await apiSend("POST", "/api/v1/inspections", { ip, ports });
      if (!alive()) return;
      env.refresh();
    }
    showReport(report);
  } catch (e) {
    if (alive()) setStatus(failureText(e), true);
  } finally {
    if (token === run) setBusy(false);
  }
}

function rerun(ports) {
  if (!current) return;
  const token = ++run;
  $("#report-sections").textContent = "";
  load(token, current.ip, { fresh: true, ports });
}

function wire(dlg) {
  if (dlg.dataset.wired) return;
  dlg.dataset.wired = "1";
  dlg.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]") || e.target === dlg) dlg.close(); // Close button or a click on the backdrop
    else if (e.target.closest("[data-run]")) rerun("top");
    else if (e.target.closest("[data-all]")) rerun("all");
  });
  dlg.addEventListener("close", () => {
    run++;
    const opener = current && current.opener;
    current = null;
    if (opener && opener.isConnected && opener.focus) opener.focus();
  });
}

/** Redraw the live sections of the open report (called on every state update). */
export function updateReport(state) {
  const dlg = document.getElementById("report");
  if (!dlg || !dlg.open || !current) return;
  setTitle();
  drawLive(state);
}

/** Open the report for an IP: its stored report, or a fresh inspection when there is none (or `fresh`). */
export function openReport(ip, { fresh = false, ports = "top" } = {}) {
  const dlg = document.getElementById("report");
  if (!dlg) return Promise.resolve();
  wire(dlg);
  const token = ++run;
  const opener = current ? current.opener : document.activeElement;
  current = { ip, opener, live: [] };
  setTitle();
  const sub = $("#report-sub");
  sub.textContent = "";
  const addr = document.createElement("span");
  addr.className = "addr";
  addr.textContent = ip;
  sub.appendChild(addr);
  $("#report-sections").textContent = "";
  const liveBox = $("#report-live");
  liveBox.textContent = "";
  for (const spec of env.host ? env.host.get("report.live-section") : []) {
    const el = document.createElement("div");
    el.className = "rlive";
    el.setAttribute("data-plugin", spec.pluginId);
    liveBox.appendChild(el);
    current.live.push({ spec, el });
  }
  setBusy(false);
  const rerunnable = canRerun(env.getAuth());
  $("[data-run]").hidden = !rerunnable;
  $("[data-all]").hidden = !rerunnable;
  setStatus("");
  if (!dlg.open) dlg.showModal();
  const state = env.getState();
  if (state) drawLive(state);
  return load(token, ip, { fresh, ports });
}
