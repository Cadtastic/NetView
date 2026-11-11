// The Roku page: one tab per saved TV, a Control | Commands toggle on the same line, and the selected view below.
import { esc } from "./html.js";
import { renderControl } from "./control.js";

const KEY_TV = "netview.roku.tv";
const KEY_VIEW = "netview.roku.view";
const POLL_MS = 5000;
const AFTER_COMMAND_MS = 1000;

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

/** What changes the Control view, leaving out the check time so a quiet poll doesn't redraw it. */
function signature(tv, view) {
  const status = { ...(tv.status || {}) };
  delete status.checked_at_ms;
  return JSON.stringify([view, { ...tv, status }]);
}

export function createPage(ui, store, { toast = () => {} } = {}) {
  return {
    id: "tvs",
    title: "Roku",
    unavailable: () => store.unavailable(),
    mount(el) {
      let selectedId = readPref(KEY_TV);
      let view = readPref(KEY_VIEW) === "commands" ? "commands" : "control";
      let ctl = null;
      let shownSig = null;
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
          const id = setTimeout(() => {
            timers.delete(id);
            if (!gone) store.load();
          }, AFTER_COMMAND_MS);
          timers.add(id);
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
        tabsEl.innerHTML = tabsHtml(tvs, selectedId);
        for (const b of segEl.querySelectorAll("button")) b.classList.toggle("on", b.dataset.view === view);
        const tv = tvs.find((t) => t.id === selectedId);
        if (!tv) {
          drop();
          shownSig = null;
          viewEl.innerHTML = `<div class="card"><p class="note">${data ? "No Roku TVs saved yet. Open Settings › Roku to scan." : "Loading…"}</p></div>`;
          return;
        }
        if (refreshedFor !== selectedId) refreshSelected();
        const sig = signature(tv, view);
        if (sig === shownSig && ctl) {
          ctl.tick();
          return;
        }
        if (ctl && ctl.busy()) return; // a key is being held: don't pull the button out from under the pointer
        drop();
        shownSig = sig;
        if (view === "control") {
          ctl = renderControl(viewEl, tv, api);
        } else {
          viewEl.innerHTML = `<div class="card"><p class="note">The Commands view is not available yet.</p></div>`;
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
