// The Control view: TV picture and facts, remote, apps, type text. Pure helpers are exported for the tests.
import { esc } from "./html.js";
import { tvSvg } from "./tv.js";

export const LIMITED_PATH = "Settings › System › Advanced system settings › Control by mobile apps › Network access › Default";
export const NOT_ANSWERING_NOTE =
  "netview can't reach this TV. It may be fully powered off (standby still answers) or have a new address: run a scan in Settings.";
export const WRONG_DEVICE = "A different Roku, {name}, now answers at this address. Run a scan in Settings.";
const HOLDABLE = new Set(["Up", "Down", "Left", "Right", "Rev", "Fwd"]);
const HOLD_DELAY_MS = 300;

// The cheat sheet's common apps (inputs left out: the Remote card has them).
export const COMMON_APPS = [
  ["Netflix", "12"], ["YouTube", "837"], ["Prime Video", "13"], ["Hulu", "2285"], ["Disney+", "291097"],
  ["Max", "61322"], ["Peacock", "593099"], ["Paramount+", "31440"], ["Apple TV", "551012"],
  ["The Roku Channel", "151908"], ["Tubi", "41468"], ["Pluto TV", "74519"], ["Plex", "13535"], ["Spotify", "22297"],
];

const KEY_MAP = {
  ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right",
  Enter: "Select", Backspace: "Back", Escape: "Back", h: "Home", H: "Home", " ": "Play",
};

/** The remote key a keyboard event stands for, or null (text fields and modifier combinations are ignored). */
export function keyForEvent(e) {
  if (!e || e.ctrlKey || e.altKey || e.metaKey) return null;
  const t = e.target;
  if (t) {
    const tag = String(t.tagName || "").toUpperCase();
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable) return null;
  }
  return Object.prototype.hasOwnProperty.call(KEY_MAP, e.key) ? KEY_MAP[e.key] : null;
}

const realTimers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (id) => globalThis.clearTimeout(id),
};

/**
 * Press-and-hold for one key at a time. send(key, "press" | "down" | "up").
 * down() waits 300 ms before sending keydown; a release before that sends one plain press instead.
 * up() sends keyup for the held key once; calling it again does nothing.
 */
export function createHold(send, timers = realTimers) {
  let held = null; // {key, timer, sent}
  function up() {
    const h = held;
    if (!h) return;
    held = null;
    if (h.sent) send(h.key, "up");
    else {
      timers.clearTimeout(h.timer);
      send(h.key, "press");
    }
  }
  function down(key) {
    up();
    const h = { key, timer: null, sent: false };
    h.timer = timers.setTimeout(() => {
      if (held === h) {
        h.sent = true;
        send(key, "down");
      }
    }, HOLD_DELAY_MS);
    held = h;
  }
  return { down, up, active: () => held !== null };
}

/** What the view should be: ok, limited (read only), silent (not answering) or wrong (another Roku answers). */
export function controlState(tv) {
  const s = tv.status || {};
  if (s.wrong_device) return { kind: "wrong", on: false, text: WRONG_DEVICE.replace("{name}", s.wrong_device) };
  if (!s.reachable) return { kind: "silent", on: false, text: NOT_ANSWERING_NOTE };
  const on = s.power === "on";
  if (String(s.mode || "").toLowerCase() === "limited") return { kind: "limited", on };
  return { kind: "ok", on };
}

const SVG_ATTR = 'width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
const ICON = {
  back: `<svg ${SVG_ATTR} stroke-width="2.2"><path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/></svg>`,
  home: `<svg ${SVG_ATTR} stroke-width="2.2"><path d="M3 11 12 4l9 7v9h-6v-6H9v6H3z"/></svg>`,
  power: `<svg ${SVG_ATTR} stroke-width="2.4"><path d="M12 3v9"/><path d="M6.3 7.5a8 8 0 1 0 11.4 0"/></svg>`,
};

const initials = (name) => String(name).split(/\s+/).map((w) => w[0] || "").join("").slice(0, 3);
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

function keyButton(key, label, dis, extra = "") {
  const hold = HOLDABLE.has(key) ? " data-hold" : "";
  return `<button type="button" data-k="${key}"${hold} ${extra} ${dis}>${label}</button>`;
}

function factsHtml(tv, st, fmtAgo) {
  const s = tv.status || {};
  const answering = st.kind === "ok" || st.kind === "limited";
  const power = !answering ? "Not answering" : s.power === "on" ? "On" : s.power === "standby" ? "Standby" : "Unknown";
  const mode = answering && s.mode ? cap(String(s.mode)) : "";
  const lim = st.kind === "limited";
  const screen = st.on ? (s.active_app && s.active_app.name) || "Home" : "";
  return `<div class="facts">
    <span class="fact ${st.on ? "ok" : ""}">Power <b>${esc(power)}</b></span>
    ${mode ? `<span class="fact ${lim ? "warn" : ""}">Network access <b>${esc(mode)}</b></span>` : ""}
    ${st.on ? `<span class="fact">On screen <b>${esc(screen)}</b></span>` : ""}
    <span class="fact">Updated <b data-updated>${esc(fmtAgo(s.checked_at_ms))}</b></span>
  </div>`;
}

function remoteHtml(tv, st, dis) {
  const isTv = tv.tv !== false;
  const power = isTv
    ? `<button type="button" class="pwr ${st.on ? "" : "is-off"}" data-k="${st.on ? "PowerOff" : "PowerOn"}" ${dis}>${ICON.power}${st.on ? "Off" : "On"}</button>`
    : "";
  const inputs = isTv
    ? `<div class="inputs">
        ${[1, 2, 3, 4].map((n) => `<button type="button" data-k="InputHDMI${n}" ${dis}>HDMI ${n}</button>`).join("")}
        <button type="button" data-k="InputTuner" ${dis}>Antenna</button><button type="button" data-k="InputAV1" ${dis}>AV</button>
      </div>`
    : "";
  return `<section class="card">
    <div class="card-head"><h2>Remote</h2></div>
    <div class="remote">
      <div class="r-row">
        ${power}
        <button type="button" data-k="Back" ${dis}>${ICON.back}Back</button>
        <button type="button" data-k="Home" ${dis}>${ICON.home}Home</button>
      </div>
      <div class="dpad">
        <button type="button" class="up" data-k="Up" data-hold ${dis} aria-label="Up">▲</button>
        <button type="button" class="left" data-k="Left" data-hold ${dis} aria-label="Left">◀</button>
        <button type="button" class="ok" data-k="Select" ${dis}>OK</button>
        <button type="button" class="right" data-k="Right" data-hold ${dis} aria-label="Right">▶</button>
        <button type="button" class="down" data-k="Down" data-hold ${dis} aria-label="Down">▼</button>
      </div>
      <div class="r-row">
        <button type="button" data-k="InstantReplay" ${dis} title="Instant replay" aria-label="Instant replay">↺</button>
        <button type="button" data-k="Info" ${dis} title="Options" aria-label="Options">✱</button>
        <button type="button" data-k="Search" ${dis} title="Search" aria-label="Search">⌕</button>
      </div>
      <div class="r-row">
        ${keyButton("Rev", "◀◀", dis, 'title="Rewind" aria-label="Rewind"')}
        <button type="button" data-k="Play" ${dis} title="Play / pause" aria-label="Play or pause">▶❚❚</button>
        ${keyButton("Fwd", "▶▶", dis, 'title="Fast forward" aria-label="Fast forward"')}
      </div>
      <div class="r-row vol">
        <button type="button" data-k="VolumeDown" ${dis}>Vol −</button>
        <button type="button" data-k="VolumeMute" ${dis}>Mute</button>
        <button type="button" data-k="VolumeUp" ${dis}>Vol +</button>
      </div>
      ${inputs}
      <div class="hint">Arrow keys, Enter, Backspace, Esc, H and Space work while this page has focus.</div>
    </div>
  </section>`;
}

function appsHtml(tv, st, dis, base) {
  const s = tv.status || {};
  const head = (sub) => `<div class="card-head"><h2>Apps</h2><span class="sub">${sub}</span></div>`;
  const running = st.on && s.active_app ? String(s.active_app.id) : "";
  if (s.apps_refused) {
    const common = COMMON_APPS.map(
      ([n, id]) => `<button type="button" class="app" data-app="${id}" data-n="${esc(n)}" disabled><span class="ic">${esc(initials(n))}</span>${esc(n)}</button>`,
    ).join("");
    return `<section class="card">${head("Installed apps unavailable")}
      <p class="note">This TV refused to list its apps (its Network access setting is Limited), so these are common apps without icons. They stay disabled while it refuses commands.</p>
      <div class="apps">${common}</div></section>`;
  }
  if (!Array.isArray(s.apps)) {
    return `<section class="card">${head("Installed on this TV")}<p class="note">Reading the app list from the TV…</p></section>`;
  }
  const list = s.apps.filter((a) => a.type !== "tvin");
  const tiles = list
    .map((a) => {
      const id = String(a.id);
      const src = `${base}/tvs/${encodeURIComponent(tv.id)}/icon/${encodeURIComponent(id)}`;
      return `<button type="button" class="app ${id === running ? "running" : ""}" data-app="${esc(id)}" data-n="${esc(a.name)}" ${dis}><img class="ic-img" src="${esc(src)}" alt="" loading="lazy" width="64" height="36"><span class="ic" hidden>${esc(initials(a.name))}</span>${esc(a.name)}</button>`;
    })
    .join("");
  return `<section class="card">${head("Installed on this TV")}${list.length ? `<div class="apps">${tiles}</div>` : '<p class="note">The TV lists no apps.</p>'}</section>`;
}

function banner(st) {
  if (st.kind === "limited") {
    return `<div class="callout"><b>This TV refuses commands.</b> Its Network access setting is Limited, so netview can read it but every button returns 403. Change it on the TV:
      <div class="path">${esc(LIMITED_PATH)}</div></div>`;
  }
  if (st.kind === "wrong") return `<div class="callout"><b>Different Roku.</b> ${esc(st.text)}</div>`;
  if (st.kind === "silent") return `<div class="callout"><b>Not answering.</b> ${esc(NOT_ANSWERING_NOTE)}</div>`;
  return "";
}

/**
 * Draw the Control view for one TV into el and wire it up.
 * api: {base, send(method, path, body), toast(message, kind), fmtAgo(ms), afterCommand?()}.
 * Returns {destroy(), busy(), tick()}: busy() is true while a key is held, tick() refreshes the "Updated" fact.
 */
export function renderControl(el, tv, api) {
  const st = controlState(tv);
  const dis = st.kind === "ok" ? "" : "disabled";
  const draft = el.querySelector("[data-text]");
  const kept = draft ? draft.value : "";
  const s = tv.status || {};
  const sub = [tv.model, tv.location, tv.ip].filter(Boolean).map(esc).join(" · ");

  el.innerHTML = `${banner(st)}
    <div class="rk-grid">
      <section class="card rk-tvpic">
        ${tvSvg({ on: st.on, name: tv.title })}
        <div class="card-head"><h2>${esc(tv.title)}</h2><span class="sub">${sub}</span></div>
        ${factsHtml(tv, st, api.fmtAgo)}
      </section>
      ${remoteHtml(tv, st, dis)}
    </div>
    ${appsHtml(tv, st, dis, api.base)}
    <section class="card">
      <div class="card-head"><h2>Type text</h2><span class="sub">Open the app's search box first. Sends one keypress per character.</span></div>
      <div class="typebox"><input type="text" data-text maxlength="100" aria-label="Text to type" ${dis}><button type="button" class="primary" data-type ${dis}>Send</button><button type="button" data-k="Backspace" aria-label="Backspace" ${dis}>⌫</button></div>
    </section>`;
  const input = el.querySelector("[data-text]");
  if (input && kept) input.value = kept;

  const tvBase = `${api.base}/tvs/${encodeURIComponent(tv.id)}`;
  const fail = (err) => api.toast(err && err.message ? err.message : String(err), "bad");
  const done = () => {
    if (api.afterCommand) api.afterCommand();
  };

  function sendKey(key, action) {
    const q = action === "press" ? "" : `?action=${action}`;
    return api
      .send("POST", `${tvBase}/key/${encodeURIComponent(key)}${q}`)
      .then(() => {
        if (action !== "up") api.toast(`Sent ${key} to ${tv.title}`);
        done();
      })
      .catch(fail);
  }
  const hold = createHold((key, action) => sendKey(key, action));

  function sendText() {
    const box = el.querySelector("[data-text]");
    const text = box ? box.value : "";
    if (!text || (box && box.disabled)) return;
    api
      .send("POST", `${tvBase}/text`, { text })
      .then(() => {
        api.toast(`Typed ${text.length} character${text.length === 1 ? "" : "s"} on ${tv.title}`);
        if (box) box.value = "";
        done();
      })
      .catch(fail);
  }
  const onClick = (e) => {
    const b = e.target.closest && e.target.closest("button");
    if (!b || b.disabled) return;
    if (b.dataset.k) {
      // A pointer press on a holdable key was already handled by pointerdown/up; keyboard activation arrives with detail 0.
      if (b.hasAttribute("data-hold") && e.detail !== 0) return;
      sendKey(b.dataset.k, "press");
    } else if (b.dataset.app) {
      api
        .send("POST", `${tvBase}/launch/${encodeURIComponent(b.dataset.app)}`)
        .then(() => {
          api.toast(`Launched ${b.dataset.n} on ${tv.title}`);
          done();
        })
        .catch(fail);
    } else if (b.hasAttribute("data-type")) sendText();
  };
  const releaseAll = () => hold.up();
  const onDown = (e) => {
    const b = e.target.closest && e.target.closest("button[data-hold]");
    if (!b || b.disabled || (e.button !== undefined && e.button !== 0)) return;
    hold.down(b.dataset.k);
    window.addEventListener("pointerup", releaseAll, { once: true });
    window.addEventListener("pointercancel", releaseAll, { once: true });
  };
  const onKey = (e) => {
    if (st.kind !== "ok" || e.repeat || e.defaultPrevented) return;
    const key = keyForEvent(e);
    if (!key) return;
    const t = e.target;
    if ((e.key === "Enter" || e.key === " ") && t && t.closest && t.closest("button, a, summary")) return;
    e.preventDefault();
    sendKey(key, "press");
  };
  const onInputKey = (e) => {
    if (e.key === "Enter" && e.target.matches && e.target.matches("[data-text]")) {
      e.preventDefault();
      sendText();
    }
  };
  const onImgError = (e) => {
    const img = e.target;
    if (img && img.tagName === "IMG" && img.classList.contains("ic-img")) {
      img.hidden = true;
      if (img.nextElementSibling) img.nextElementSibling.hidden = false;
    }
  };

  el.addEventListener("click", onClick);
  el.addEventListener("pointerdown", onDown);
  el.addEventListener("keydown", onInputKey);
  el.addEventListener("error", onImgError, true);
  for (const b of el.querySelectorAll("button[data-hold]")) {
    b.addEventListener("pointerleave", releaseAll);
    b.addEventListener("pointercancel", releaseAll);
  }
  document.addEventListener("keydown", onKey);
  window.addEventListener("blur", releaseAll);

  return {
    busy: () => hold.active(),
    tick() {
      const u = el.querySelector("[data-updated]");
      if (u) u.textContent = api.fmtAgo(s.checked_at_ms);
    },
    destroy() {
      hold.up();
      el.removeEventListener("click", onClick);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("keydown", onInputKey);
      el.removeEventListener("error", onImgError, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("blur", releaseAll);
      window.removeEventListener("pointerup", releaseAll);
      window.removeEventListener("pointercancel", releaseAll);
    },
  };
}
