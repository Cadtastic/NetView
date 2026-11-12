// The Roku page: one tab per saved TV, a Control | Commands toggle on the same line, and the selected view below.
import { esc } from "./html.js";
import { renderControl, typingIn } from "./control.js";
import { renderCommands, defaultShell, appRows } from "./commands.js";

const KEY_TV = "netview.roku.tv";
const KEY_VIEW = "netview.roku.view";
const KEY_SHELL = "netview.roku.shell";
const POLL_MS = 5000;
// The server re-reads the status 1 s after a command and that read takes a moment, so look twice.
export const AFTER_COMMAND_DELAYS_MS = [1500, 3000];

function readPref(key) {
  try {
    return localStorage.getItem(key);
  } catch (e) {
    return null;
  }
}
function writePref(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (e) {
    // private window or blocked storage: the choice just isn't remembered
  }
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** Dot class for a TV's tab: on (green), lim (amber, Network access Limited) or empty (grey). */
export function tabDot(tv) {
  const s = tv.status || {};
  if (!s.reachable) return "";
  if (String(s.mode || "").toLowerCase() === "limited") return "lim";
  return s.power === "on" ? "on" : "";
}

/** Tab tooltip: address, state, Network access. */
export function tabTip(tv) {
  const s = tv.status || {};
  if (!s.reachable) return `${tv.ip} · not answering`;
  const state = s.power === "on" ? "on" : s.power === "standby" ? "standby" : "unknown";
  return `${tv.ip} · ${state}${s.mode ? ` · Network access: ${cap(String(s.mode))}` : ""}`;
}

/** The tab buttons for the saved TVs; selectedId marks the open one. */
export function tabsHtml(tvs, selectedId) {
  return tvs
    .map(
      (tv) =>
        `<button role="tab" type="button" aria-selected="${tv.id === selectedId}" data-id="${esc(tv.id)}" title="${esc(tabTip(tv))}"><span class="dot ${tabDot(tv)}"></span>${esc(tv.title)}</button>`,
    )
    .join("");
}

/** The tab markup to write, or null when `next` is what `shown` already holds (so a redraw that changes nothing
 * leaves the tabs alone and a focused or half-clicked tab is not lost). */
export function nextTabsMarkup(shown, next) {
  return shown === next ? null : next;
}

/** Call `reload` after each delay in AFTER_COMMAND_DELAYS_MS using `setTimer(fn, ms)`; returns the timer ids.
 * With `pending`, each id is added to that set and removed again when its timer fires. */
export function scheduleReloads(setTimer, reload, delays = AFTER_COMMAND_DELAYS_MS, pending = null) {
  const ids = [];
  for (const ms of delays) {
    const id = setTimer(() => {
      if (pending) pending.delete(id);
      reload();
    }, ms);
    ids.push(id);
    if (pending) pending.add(id);
  }
  return ids;
}

/** What changes the Control view, leaving out the check time so a quiet poll doesn't redraw it. */
function signature(tv, view) {
  const status = { ...(tv.status || {}) };
  delete status.checked_at_ms;
  return JSON.stringify([view, { ...tv, status }]);
}

/** What the Commands view shows: the TV's id, address, title and Network access mode, the shell, the app list and
 * the selected key. Power, the active app and the check time are not in it, so a status poll leaves the view alone. */
export function commandsSignature(tv, shell, key) {
  const s = tv.status || {};
  return JSON.stringify(["commands", tv.id, tv.ip, tv.title, tv.tv !== false, s.mode || "", shell, key, appRows(tv)]);
}

export function createPage(ui, store, { toast = () => {} } = {}) {
  return {
    id: "tvs",
    unavailable: () => store.unavailable(),
    mount(el) {
      let selectedId = readPref(KEY_TV);
      let view = readPref(KEY_VIEW) === "commands" ? "commands" : "control";
      let shell = readPref(KEY_SHELL);
      if (shell !== "ps" && shell !== "cmd" && shell !== "curl") shell = defaultShell(typeof navigator === "undefined" ? "" : navigator.platform);
      const cmdState = { key: "Home", text: "star trek" }; // survives redraws while the page is open
      let ctl = null;
      let shownSig = null;
      let shownTabs = null;
      let refreshedFor = null;
      let gone = false;
      const timers = new Set();

      el.innerHTML = `<div class="rk-tabrow">
          <div class="tabs" role="tablist" aria-label="Roku TVs"></div>
          <div class="seg" role="group" aria-label="View">
            <button type="button" data-view="control">Control</button>
            <button type="button" data-view="commands">Commands</button>
          </div>
        </div>
        <div class="rk-view"></div>`;
      const tabsEl = el.querySelector(".tabs");
      const segEl = el.querySelector(".seg");
      const viewEl = el.querySelector(".rk-view");

      const api = {
        base: ui.apiBase,
        send: (method, path, body) => ui.apiSend(method, path, body),
        toast,
        fmtAgo: (ms) => ui.util.fmtAgo(ms),
        afterCommand() {
          scheduleReloads(
            (fn, ms) => setTimeout(fn, ms),
            () => {
              if (!gone) store.load();
            },
            undefined,
            timers,
          );
        },
      };

      function refreshSelected() {
        if (!selectedId) return;
        refreshedFor = selectedId;
        Promise.resolve(ui.apiSend("POST", `${ui.apiBase}/tvs/${encodeURIComponent(selectedId)}/refresh`))
          .then(() => (gone ? undefined : store.load()))
          .catch(() => {});
      }

      function drop() {
        if (ctl) ctl.destroy();
        ctl = null;
        shownSig = null;
      }

      function render() {
        if (gone) return;
        const data = store.get();
        const tvs = data ? data.tvs : [];
        if (!tvs.some((t) => t.id === selectedId)) selectedId = tvs.length ? tvs[0].id : null;
        const tabs = nextTabsMarkup(shownTabs, tabsHtml(tvs, selectedId));
        if (tabs !== null) {
          tabsEl.innerHTML = tabs;
          shownTabs = tabs;
        }
        for (const b of segEl.querySelectorAll("button")) b.classList.toggle("on", b.dataset.view === view);
        const tv = tvs.find((t) => t.id === selectedId);
        if (!tv) {
          drop();
          shownSig = null;
          viewEl.innerHTML = `<div class="card"><p class="note">${data ? "No Roku TVs saved yet. Open Settings › Roku to scan." : "Loading…"}</p></div>`;
          return;
        }
        if (refreshedFor !== selectedId) refreshSelected();
        const sig = view === "commands" ? commandsSignature(tv, shell, cmdState.key) : signature(tv, view);
        if (sig === shownSig && ctl) {
          ctl.tick(tv);
          return;
        }
        if (ctl && typingIn(viewEl)) return; // the Type text box has focus: redraw after the user leaves it
        if (ctl && ctl.busy()) return; // a key is being held: don't pull the button out from under the pointer
        drop();
        shownSig = sig;
        if (view === "control") {
          ctl = renderControl(viewEl, tv, api);
        } else {
          ctl = renderCommands(viewEl, tv, {
            shell,
            state: cmdState,
            toast,
            onShell(next) {
              shell = next;
              writePref(KEY_SHELL, next);
              drop();
              render();
            },
          });
        }
      }

      function select(id) {
        if (id === selectedId) return;
        selectedId = id;
        writePref(KEY_TV, id);
        drop();
        refreshSelected();
        render();
      }

      const onClick = (e) => {
        const tab = e.target.closest && e.target.closest("[role=tab]");
        if (tab && tab.dataset.id) return select(tab.dataset.id);
        const seg = e.target.closest && e.target.closest("[data-view]");
        if (seg && seg.dataset.view !== view) {
          view = seg.dataset.view;
          writePref(KEY_VIEW, view);
          drop();
          render();
        }
      };
      el.addEventListener("click", onClick);

      const unsubscribe = store.subscribe(render);
      const poll = setInterval(() => store.load(), POLL_MS);
      render();
      store.load();

      return {
        update() {
          store.load();
        },
        destroy() {
          gone = true;
          clearInterval(poll);
          for (const id of timers) clearTimeout(id);
          timers.clear();
          unsubscribe();
          el.removeEventListener("click", onClick);
          drop();
        },
      };
    },
  };
}
