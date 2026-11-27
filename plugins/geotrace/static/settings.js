// GeoTrace settings sections: home location (address search, coordinates, pick on the globe), location data and the globe files.
// Every string that came from the server goes in through textContent.
import { bundleStatusText, canDownloadBundle, geoStatusText } from "./settings-model.js";
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

const NEED_CONFIGURE = "You need the Configure permission for this.";
const PICK_NEEDS_GLOBE = "Picking needs the globe files; download them under Map first.";

/** The settings form in a dialog (the dialog holds one plugin's form at a time). */
function formIn(dlg) {
  return dlg ? dlg.querySelector("form.settings") : null;
}

/** Write a value into one of the form's own inputs and tell the form. */
function setFormField(form, name, value) {
  const input = form && form.querySelector(`[name="${name}"]`);
  if (!input) return false;
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}

const SAVE_WAIT_MS = 15000;

/** Submit the settings form and wait for its own answer: {ok: true} on settings:saved, else {ok: false, error}. */
export function saveForm(form, wait = SAVE_WAIT_MS) {
  return new Promise((resolve) => {
    let timer = null;
    const done = (result) => {
      clearTimeout(timer);
      form.removeEventListener("settings:saved", onSaved);
      form.removeEventListener("settings:failed", onFailed);
      resolve(result);
    };
    const onSaved = () => done({ ok: true });
    const onFailed = (e) => done({ ok: false, error: String((e && e.detail) || "") });
    form.addEventListener("settings:saved", onSaved);
    form.addEventListener("settings:failed", onFailed);
    timer = setTimeout(() => done({ ok: false, error: "The save took too long." }), wait);
    form.requestSubmit();
  });
}

/**
 * Settings > General > Find your home: address search and "Pick on the globe". The coordinates live in the form's own
 * fields above, so the form's Save is the only thing that saves them (same validation and audit as every other setting).
 * deps: {can(permission)}.
 */
export function renderHome(body, ctx, deps) {
  const allowed = deps.can("configure");
  const root = h("div", "gt-set");
  const search = textInput("Search for an address");
  search.placeholder = "Search for an address or place";
  const go = button("Search");
  const searchRow = h("div", "gt-set-row");
  searchRow.append(search, go);
  const results = h("ul", "gt-set-results");
  const credit = h("p", "gt-muted gt-set-credit");
  const osm = h("a", "", "© OpenStreetMap contributors");
  osm.href = "https://www.openstreetmap.org/copyright";
  osm.target = "_blank";
  osm.rel = "noopener noreferrer";
  credit.appendChild(osm);
  credit.hidden = true;
  const pick = button("Pick on the globe");
  const note = h("p", "gt-set-note");
  const prompt = h("div", "gt-set-prompt");
  prompt.hidden = true;
  const actions = h("div", "gt-set-row");
  actions.appendChild(pick);
  root.append(
    h(
      "p",
      "gt-muted",
      allowed
        ? "Search for an address to fill the home fields above, or click the globe. Save keeps the values."
        : "Only an administrator can change the home location.",
    ),
    searchRow,
    results,
    credit,
    actions,
    prompt,
    note,
  );
  body.appendChild(root);

  const dlg = body.closest("dialog"); // taken now: a save that redraws the dialog detaches this section
  const form = formIn(dlg);
  let dirty = false;
  if (form) {
    form.addEventListener("input", (e) => {
      if (e.isTrusted) dirty = true; // the user's own edits; our programmatic writes are not asked about
    });
    // Only a save that went through clears it: a failed one leaves the edits unsaved.
    form.addEventListener("settings:saved", () => {
      dirty = false;
    });
  }
  let globeReady = false;
  let working = false;
  const refreshButtons = () => {
    go.disabled = !allowed || working;
    pick.disabled = !allowed || !globeReady || working || !prompt.hidden;
    go.title = allowed ? "" : NEED_CONFIGURE;
    pick.title = !allowed ? NEED_CONFIGURE : !globeReady ? PICK_NEEDS_GLOBE : "";
  };
  refreshButtons();
  subscribeStatus(ctx, body, (status) => {
    globeReady = !!(status && status.bundle && status.bundle.state === "ready");
    refreshButtons();
  });

  function fill(r) {
    setFormField(form, "home_label", labelOf(r));
    setFormField(form, "home_lat", String(r.lat));
    setFormField(form, "home_lon", String(r.lon));
    results.replaceChildren();
    credit.hidden = true;
    note.classList.remove("gt-bad");
    note.textContent = "Filled in the home fields above. Save to keep them.";
  }

  async function runSearch() {
    const q = search.value.trim();
    if (!q || !allowed || working) return;
    results.replaceChildren();
    working = true;
    refreshButtons();
    await busy([go], note, async () => {
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
      credit.hidden = false;
    });
    working = false;
    refreshButtons();
  }
  go.addEventListener("click", runSearch);
  search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runSearch();
    }
  });

  function startPicking() {
    if (!requestPick()) {
      note.textContent = "This browser blocks the storage that picking on the globe needs.";
      note.classList.add("gt-bad");
      return;
    }
    if (dlg && dlg.open) dlg.close();
    const target = `#/p/${ctx.pluginId}/geotrace`;
    if (location.hash === target) window.dispatchEvent(new Event(PICK_EVENT));
    else location.hash = target;
  }

  // The form has unsaved edits: closing the dialog would lose them, so ask first.
  function ask() {
    prompt.hidden = false;
    note.hidden = true;
    refreshButtons();
    const text = h("p", "gt-set-note", "Save your changes first, or discard them?");
    const keep = button("Save", "gt-primary");
    const drop = button("Discard");
    const cancel = button("Cancel");
    const close = () => {
      prompt.hidden = true;
      prompt.replaceChildren();
      note.hidden = false;
      refreshButtons();
    };
    keep.addEventListener("click", async () => {
      [keep, drop, cancel].forEach((b) => (b.disabled = true));
      const result = await saveForm(form);
      close();
      if (!result.ok) {
        note.textContent = "The settings were not saved, so picking was not started.";
        note.classList.add("gt-bad");
        return;
      }
      startPicking();
    });
    drop.addEventListener("click", () => {
      close();
      startPicking();
    });
    cancel.addEventListener("click", close);
    const buttons = h("div", "gt-set-row");
    buttons.append(keep, drop, cancel);
    prompt.replaceChildren(text, buttons);
  }

  pick.addEventListener("click", () => {
    if (!allowed || !globeReady) return;
    if (dirty && form) ask();
    else startPicking();
  });

  // Back from the globe: the picked point goes into the form's home fields, not saved yet.
  const picked = form ? takePicked() : null; // without a form (no configure) the pick stays for someone who can use it
  if (picked && form) {
    setFormField(form, "home_label", "Home"); // the old name would describe the wrong place
    setFormField(form, "home_lat", picked.lat.toFixed(5));
    setFormField(form, "home_lon", picked.lon.toFixed(5));
    note.textContent = "Picked on the globe. Save to keep it.";
  }
}

function row(name, value) {
  const r = h("div", "gt-set-line");
  r.append(h("span", "gt-set-name", name), h("span", "gt-set-value", value));
  return r;
}

// One /status poll for all three sections. A tick is skipped while the document is hidden, while every section's tab is hidden
// (nobody is looking), and while the previous request is still out. /status has side effects on the server, so it is not hammered.
const listeners = new Set(); // {body, fn}
let timer = null;
let polling = false;

async function tick(ctx) {
  if (polling || document.hidden) return;
  for (const l of [...listeners]) if (!l.body.isConnected) listeners.delete(l);
  if (!listeners.size) {
    clearInterval(timer);
    timer = null;
    return;
  }
  if (![...listeners].some((l) => !l.body.closest('[hidden], [aria-hidden="true"]'))) return; // a closed child blade stays in the page, aria-hidden
  polling = true;
  try {
    const status = await ctx.apiGet(`${ctx.apiBase}/status`);
    for (const l of [...listeners]) l.fn(status, null);
  } catch (err) {
    for (const l of [...listeners]) l.fn(null, err);
  } finally {
    polling = false;
  }
}

/** fn(status, error) runs after each poll; the first poll starts as soon as the section is attached. */
function subscribeStatus(ctx, body, fn) {
  listeners.add({ body, fn });
  if (timer === null) timer = setInterval(() => tick(ctx), POLL_MS);
  queueMicrotask(() => tick(ctx));
}

/** Settings > Location data: DB-IP status, Update now, credit and the sources that are not built yet. */
export function renderLocationData(body, ctx, deps) {
  const root = h("div", "gt-set");
  const month = row("Database", "");
  const checked = row("Last check", "");
  const error = h("p", "gt-set-note gt-bad");
  error.hidden = true;
  const update = button("Update now");
  const allowed = deps.can("configure");
  update.disabled = !allowed;
  update.title = allowed ? "" : NEED_CONFIGURE;
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
  const onStatus = (status, err) => {
    if (status) return show(status);
    error.hidden = false;
    error.textContent = (err && err.message) || "The status could not be read.";
  };
  update.addEventListener("click", () =>
    busy([update], note, async () => {
      show(await ctx.apiSend("POST", `${ctx.apiBase}/geodata/update`));
      note.textContent = "Updating in the background. This section refreshes itself.";
    }),
  );
  subscribeStatus(ctx, body, onStatus);
}

/** Settings > Map: the state of the globe files and Download now. */
export function renderGlobe(body, ctx, deps) {
  const root = h("div", "gt-set");
  const state = row("Globe files", "Checking…");
  const version = row("Version", "–");
  const download = button("Download now");
  const allowed = deps.can("configure");
  download.disabled = true;
  download.title = allowed ? "" : NEED_CONFIGURE;
  const note = h("p", "gt-set-note");
  const actions = h("div", "gt-set-row");
  actions.appendChild(download);
  root.append(h("p", "gt-muted", "The globe itself downloads once, from the plugin's own release."), state, version, actions, note);
  body.appendChild(root);

  let inFlight = false;
  let lastStatus = null;
  function show(status) {
    lastStatus = status;
    state.lastChild.textContent = bundleStatusText(status);
    const v = status && status.bundle && status.bundle.version;
    version.lastChild.textContent = v ? String(v) : "–";
    if (!inFlight) download.disabled = !allowed || !canDownloadBundle(status);
  }
  const onStatus = (status, err) => {
    if (status) return show(status);
    state.lastChild.textContent = (err && err.message) || "The status could not be read.";
  };
  download.addEventListener("click", async () => {
    inFlight = true;
    await busy([download], note, async () => {
      show({ bundle: await ctx.apiSend("POST", `${ctx.apiBase}/bundle/download`) });
    });
    inFlight = false;
    download.disabled = !allowed || !canDownloadBundle(lastStatus); // busy() re-enabled it; the new state decides
  });
  subscribeStatus(ctx, body, onStatus);
}
