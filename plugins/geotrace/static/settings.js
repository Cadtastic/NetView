// GeoTrace settings sections: home location (address search, coordinates, pick on the globe), location data and the globe files.
// Every string that came from the server goes in through textContent.
import { bundleStatusText, canDownloadBundle, geoStatusText, hasCoordinates } from "./settings-model.js";
import { PICK_EVENT, requestPick, takePicked } from "./pick.js";

export const DB_IP_TEXT = "IP geolocation by DB-IP";
export const DB_IP_HREF = "https://db-ip.com";
const MAX_RESULTS = 5;
const POLL_MS = 3000;

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function field(label, input) {
  const wrap = h("label", "gt-field");
  wrap.append(h("span", "", label), input);
  return wrap;
}

function textInput(label, attrs = {}) {
  const input = h("input", "gt-input");
  input.type = "text";
  input.setAttribute("aria-label", label);
  for (const [k, v] of Object.entries(attrs)) input.setAttribute(k, v);
  return input;
}

function button(text, cls = "") {
  const b = h("button", `gt-btn ${cls}`.trim(), text);
  b.type = "button";
  return b;
}

/** Disable `buttons` while `fn` runs; a failure's text goes to `note` (textContent). */
async function busy(buttons, note, fn) {
  buttons.forEach((b) => (b.disabled = true));
  note.textContent = "";
  note.classList.remove("gt-bad");
  try {
    return await fn();
  } catch (err) {
    note.textContent = (err && err.message) || "Something went wrong.";
    note.classList.add("gt-bad");
    return undefined;
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

const labelOf = (r) => (typeof r.label === "string" ? r.label : "");

/** Settings > General > home location. deps: {reopen()} reopens the settings dialog on this plugin, so the form shows the saved values. */
export function renderHome(body, ctx, deps) {
  const root = h("div", "gt-set");
  const search = textInput("Search for an address");
  search.placeholder = "Search for an address or place";
  const go = button("Search");
  const searchRow = h("div", "gt-set-row");
  searchRow.append(search, go);
  const results = h("ul", "gt-set-results");
  const label = textInput("Home name");
  const lat = textInput("Latitude", { inputmode: "decimal" });
  const lon = textInput("Longitude", { inputmode: "decimal" });
  const coords = h("div", "gt-set-coords");
  coords.append(field("Name", label), field("Latitude", lat), field("Longitude", lon));
  const save = button("Save home location", "gt-primary");
  const pick = button("Pick on the globe");
  const note = h("p", "gt-set-note");
  const actions = h("div", "gt-set-row");
  actions.append(save, pick);
  root.append(
    h("p", "gt-muted", "Where your traces start. Search for an address, type coordinates, or click the globe."),
    searchRow,
    results,
    coords,
    actions,
    note,
  );
  body.appendChild(root);

  const refreshSave = () => {
    save.disabled = !hasCoordinates(lat.value, lon.value);
  };
  lat.addEventListener("input", refreshSave);
  lon.addEventListener("input", refreshSave);
  refreshSave();

  function fill(r) {
    label.value = labelOf(r);
    lat.value = String(r.lat);
    lon.value = String(r.lon);
    results.replaceChildren();
    refreshSave();
  }

  async function runSearch() {
    const q = search.value.trim();
    if (!q) return;
    results.replaceChildren();
    await busy([go, save, pick], note, async () => {
      const found = await ctx.apiGet(`${ctx.apiBase}/geocode?q=${encodeURIComponent(q)}`);
      const list = (Array.isArray(found) ? found : []).filter((r) => Number.isFinite(r.lat) && Number.isFinite(r.lon)).slice(0, MAX_RESULTS);
      if (!list.length) {
        note.textContent = "No matching places.";
        return;
      }
      for (const r of list) {
        const li = h("li");
        const choose = h("button", "gt-set-result", labelOf(r));
        choose.type = "button";
        choose.addEventListener("click", () => fill(r));
        li.appendChild(choose);
        results.appendChild(li);
      }
    });
    refreshSave();
  }
  go.addEventListener("click", runSearch);
  search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runSearch();
    }
  });

  save.addEventListener("click", async () => {
    if (!hasCoordinates(lat.value, lon.value)) return;
    const saved = await busy([go, save, pick], note, async () => {
      // PATCH changes only the fields it names, through the same validated, audited route as the form's Save.
      await ctx.apiSend("PATCH", ctx.apiBase, {
        settings: { home_label: label.value.trim(), home_lat: Number(lat.value), home_lon: Number(lon.value) },
      });
      return true;
    });
    if (saved) deps.reopen();
    else refreshSave();
  });

  pick.addEventListener("click", () => {
    if (!requestPick()) {
      note.textContent = "This browser blocks the storage that picking on the globe needs.";
      note.classList.add("gt-bad");
      return;
    }
    const dlg = body.closest("dialog");
    if (dlg && dlg.open) dlg.close();
    const target = `#/p/${ctx.pluginId}/geotrace`;
    if (location.hash === target) window.dispatchEvent(new Event(PICK_EVENT));
    else location.hash = target;
  });

  // Current values first, then anything a globe pick left behind.
  (async () => {
    try {
      const info = await ctx.apiGet(ctx.apiBase);
      const s = (info && info.settings) || {};
      label.value = s.home_label || "";
      if (Number.isFinite(s.home_lat)) lat.value = String(s.home_lat);
      if (Number.isFinite(s.home_lon)) lon.value = String(s.home_lon);
    } catch (err) {
      note.textContent = (err && err.message) || "The saved home location could not be read.";
    }
    const picked = takePicked();
    if (picked) {
      lat.value = picked.lat.toFixed(5);
      lon.value = picked.lon.toFixed(5);
      note.textContent = "Location picked on the globe. Save it to keep it.";
    }
    refreshSave();
  })();
}

function row(name, value) {
  const r = h("div", "gt-set-line");
  r.append(h("span", "gt-set-name", name), h("span", "gt-set-value", value));
  return r;
}

/** Runs `fn` every few seconds until `body` has left the page. */
function whileAttached(body, fn) {
  const timer = setInterval(() => {
    if (!body.isConnected) clearInterval(timer);
    else fn();
  }, POLL_MS);
}

/** Settings > Location data: DB-IP status, Update now, credit and the sources that are not built yet. */
export function renderLocationData(body, ctx) {
  const root = h("div", "gt-set");
  const month = row("Database", "");
  const checked = row("Last check", "");
  const error = h("p", "gt-set-note gt-bad");
  error.hidden = true;
  const update = button("Update now");
  const note = h("p", "gt-set-note");
  const actions = h("div", "gt-set-row");
  actions.appendChild(update);
  const credit = h("p", "gt-muted");
  const link = h("a", "", DB_IP_TEXT);
  link.href = DB_IP_HREF;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  credit.appendChild(link);
  const later = [row("MaxMind GeoLite2 — coming later", ""), row("RIPE IPmap — coming later", "")];
  for (const r of later) r.classList.add("gt-set-off");
  root.append(h("p", "gt-muted", "Free DB-IP city and network files place each hop on the globe."), month, checked, error, actions, note, credit, ...later);
  body.appendChild(root);

  function show(status) {
    const t = geoStatusText(status);
    month.lastChild.textContent = t.month;
    checked.lastChild.textContent = t.checked;
    error.hidden = !t.error;
    error.textContent = t.error || "";
  }
  async function load() {
    try {
      show(await ctx.apiGet(`${ctx.apiBase}/status`));
    } catch (err) {
      error.hidden = false;
      error.textContent = (err && err.message) || "The status could not be read.";
    }
  }
  update.addEventListener("click", () =>
    busy([update], note, async () => {
      show(await ctx.apiSend("POST", `${ctx.apiBase}/geodata/update`));
      note.textContent = "Updating in the background. This section refreshes itself.";
    }),
  );
  load();
  whileAttached(body, load);
}

/** Settings > Map: the state of the globe files and Download now. */
export function renderGlobe(body, ctx) {
  const root = h("div", "gt-set");
  const state = row("Globe files", "Checking…");
  const version = row("Version", "–");
  const download = button("Download now");
  download.disabled = true;
  const note = h("p", "gt-set-note");
  const actions = h("div", "gt-set-row");
  actions.appendChild(download);
  root.append(h("p", "gt-muted", "The globe itself downloads once, from the plugin's own release."), state, version, actions, note);
  body.appendChild(root);

  let inFlight = false;
  function show(status) {
    state.lastChild.textContent = bundleStatusText(status);
    const v = status && status.bundle && status.bundle.version;
    version.lastChild.textContent = v ? String(v) : "–";
    if (!inFlight) download.disabled = !canDownloadBundle(status);
  }
  async function load() {
    try {
      show(await ctx.apiGet(`${ctx.apiBase}/status`));
    } catch (err) {
      state.lastChild.textContent = (err && err.message) || "The status could not be read.";
    }
  }
  download.addEventListener("click", async () => {
    inFlight = true;
    await busy([download], note, async () => {
      show({ bundle: await ctx.apiSend("POST", `${ctx.apiBase}/bundle/download`) });
    });
    inFlight = false;
    await load();
  });
  load();
  whileAttached(body, load);
}
