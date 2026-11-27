// The GeoTrace page: a globe host, a rail of buttons, blades stacked left to right beside it, notices and a HUD.
import { createBladeStack, createBladeController, bladeTitle, loadBlades, saveBlades } from "./blades.js";
import { createSubscriptions } from "./subscriptions.js";
import { bannersFor } from "./banners.js";

const POLL_MS = 30000;
const RAIL = [
  { key: "targets", label: "Targets", glyph: "◎" },
  { key: "compare", label: "Compare", glyph: "⇄" },
  { key: "trends", label: "Trends", glyph: "∿" },
  { key: "trace", label: "Trace once", glyph: "➤" },
];
const TITLES = { targets: "Targets", compare: "Compare", trends: "Trends", trace: "Trace once" };

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function button(cls, label, text) {
  const b = h("button", cls, text);
  b.type = "button";
  b.setAttribute("aria-label", label);
  b.title = label;
  return b;
}

const base = (key) => key.split(":")[0];

/** The page spec for ui.slot("page"). deps: {api: {gtGet, gtSend}, shell, openSettings(section), storage?}. */
export function createPage(ui, deps) {
  const { api, shell, openSettings, storage } = deps;
  return {
    id: "geotrace",
    title: "GeoTrace",
    mount(el) {
      const stack = createBladeStack(loadBlades(storage));
      let snap = { status: null, targets: null };
      const subs = createSubscriptions();
      const controller = createBladeController((state) => {
        if (gone) return;
        saveBlades(state, storage);
        renderBlades();
      });
      const change = (op) => {
        if (!gone) controller.run(op);
      };
      const live = new Map(); // blade key -> {el, handle}
      let globeHandle = null;
      let timer = null;
      let gone = false;

      const root = h("div", "gt-page");
      const globeHost = h("div", "gt-globe");
      globeHost.dataset.role = "globe";
      const banners = h("div", "gt-banners");
      banners.setAttribute("role", "status");
      const hud = h("div", "gt-hud");
      const bladeBox = h("div", "gt-blades");
      const rail = h("nav", "gt-rail");
      rail.setAttribute("aria-label", "GeoTrace");
      root.append(globeHost, banners, hud, rail, bladeBox);
      el.replaceChildren(root);

      // Shared by every blade; drawBlade adds the blade's own key, params, setTitle and onChange.
      const ctx = {
        api,
        snapshot: () => snap,
        open: (key, opts = {}) => {
          if (gone) return;
          change(() => stack.open(key, opts));
        },
        close: (key) => {
          if (gone) return;
          change(() => stack.close(key));
        },
      };

      const railButtons = new Map();
      for (const item of RAIL) {
        const b = button("gt-rail-btn", item.label);
        b.append(h("span", "gt-rail-glyph", item.glyph), h("span", "gt-rail-label", item.label));
        b.addEventListener("click", () => {
          const open = stack.state().blades.some((x) => x.key === item.key);
          change(() => (open ? stack.close(item.key) : stack.open(item.key, { level: 0, wide: item.key === "targets" })));
        });
        railButtons.set(item.key, b);
        rail.appendChild(b);
      }
      rail.appendChild(h("div", "gt-rail-gap"));
      const settingsBtn = button("gt-rail-btn", "Settings");
      settingsBtn.append(h("span", "gt-rail-glyph", "⚙"), h("span", "gt-rail-label", "Settings"));
      settingsBtn.addEventListener("click", () => openSettings(`plugin:${ui.pluginId}`));
      rail.appendChild(settingsBtn);

      function drawBlade(blade) {
        const spec = shell.blade(base(blade.key));
        const box = h("section", "gt-blade");
        const head = h("header", "gt-blade-head");
        const fallback = TITLES[base(blade.key)] || blade.key;
        const titleBox = h("div", "gt-blade-titles");
        const title = h("h2", "gt-blade-title", bladeTitle(spec && spec.title, blade.key, snap, fallback));
        const sub = h("p", "gt-blade-sub");
        sub.hidden = true;
        titleBox.append(title, sub);
        const min = button("gt-blade-btn", "Minimise", "–");
        const close = button("gt-blade-btn", "Close", "×");
        min.addEventListener("click", () => change(() => stack.minimise(blade.key)));
        close.addEventListener("click", () => change(() => stack.close(blade.key)));
        head.append(titleBox, min, close);
        const body = h("div", "gt-blade-body");
        const strip = h("button", "gt-blade-strip", title.textContent);
        strip.type = "button";
        strip.addEventListener("click", () => change(() => stack.restore(blade.key)));
        box.append(strip, head, body);
        const scope = subs.forBlade();
        const entryRef = { custom: false };
        const setTitle = (text, subtitle) => {
          entryRef.custom = true;
          title.textContent = text;
          strip.textContent = text;
          sub.textContent = subtitle || "";
          sub.hidden = !subtitle;
        };
        const bladeCtx = { ...ctx, key: blade.key, params: blade.key.split(":").slice(1), onChange: scope.onChange, setTitle };
        let handle = null;
        if (spec && spec.render) {
          try {
            handle = spec.render(body, bladeCtx) || null;
          } catch (e) {
            console.error(`GeoTrace blade ${blade.key} failed`, e);
            body.replaceChildren(h("p", "gt-muted", `This panel failed: ${e.message}`));
          }
        } else {
          body.replaceChildren(h("p", "gt-muted", "Not available yet."));
        }
        return Object.assign(entryRef, { el: box, handle, scope, spec, title, strip, key: blade.key });
      }

      function destroyBlade(entry) {
        entry.scope.dispose();
        try {
          if (entry.handle && entry.handle.destroy) entry.handle.destroy();
        } catch (e) {
          console.error("GeoTrace blade destroy failed", e);
        }
        entry.el.remove();
      }

      function renderBlades() {
        const { blades } = stack.state();
        const wanted = new Set(blades.map((b) => b.key));
        for (const [key, entry] of [...live]) {
          if (!wanted.has(key)) {
            destroyBlade(entry);
            live.delete(key);
          }
        }
        blades.forEach((b, i) => {
          let entry = live.get(b.key);
          if (!entry) {
            entry = drawBlade(b);
            live.set(b.key, entry);
          }
          entry.el.classList.toggle("gt-min", b.min);
          entry.el.classList.toggle("gt-wide", b.wide);
          if (bladeBox.children[i] !== entry.el) bladeBox.insertBefore(entry.el, bladeBox.children[i] || null);
        });
        for (const [key, b] of railButtons) {
          const on = blades.some((x) => x.key === key);
          b.classList.toggle("gt-on", on);
          b.setAttribute("aria-pressed", String(on));
        }
      }

      function renderBanners() {
        const count = snap.targets ? snap.targets.length : null;
        banners.replaceChildren(...bannersFor(snap.status, count).map((b) => h("div", `gt-banner gt-${b.kind}`, b.text)));
        hud.replaceChildren();
        if (count !== null) hud.append(h("span", "gt-chip", `${count} ${count === 1 ? "target" : "targets"}`));
      }

      function notify() {
        renderBanners();
        subs.emit(snap);
        // A title given as a function follows the data; one set with ctx.setTitle is left alone.
        for (const entry of live.values()) {
          if (entry.spec && typeof entry.spec.title === "function" && !entry.custom) {
            const text = bladeTitle(entry.spec.title, entry.key, snap, entry.title.textContent);
            entry.title.textContent = text;
            entry.strip.textContent = text;
          }
          try {
            if (entry.handle && entry.handle.update) entry.handle.update(snap);
          } catch (e) {
            console.error("GeoTrace blade update failed", e);
          }
        }
        try {
          if (globeHandle && globeHandle.update) globeHandle.update(snap);
        } catch (e) {
          console.error("GeoTrace globe update failed", e);
        }
      }

      async function refresh() {
        const [status, targets] = await Promise.allSettled([api.gtGet("/status"), api.gtGet("/targets")]);
        if (gone) return;
        if (status.status === "fulfilled") snap = { ...snap, status: status.value };
        if (targets.status === "fulfilled" && Array.isArray(targets.value)) snap = { ...snap, targets: targets.value };
        notify();
      }

      function start() {
        if (timer === null) timer = setInterval(refresh, POLL_MS);
      }
      function stop() {
        if (timer !== null) clearInterval(timer);
        timer = null;
      }
      // Poll only while the page is visible: a hidden tab neither polls nor keeps a timer.
      function onVisibility() {
        if (document.visibilityState === "visible") {
          refresh();
          start();
        } else stop();
      }

      const globeSpec = shell.globe();
      if (globeSpec && globeSpec.mount) {
        try {
          globeHandle = globeSpec.mount(globeHost, { ...ctx, onChange: subs.forBlade().onChange }) || null;
        } catch (e) {
          console.error("GeoTrace globe failed", e);
        }
      }
      change(() => stack.state()); // through the controller: a blade opening another from render is queued
      renderBanners();
      document.addEventListener("visibilitychange", onVisibility);
      onVisibility();

      return {
        update() {},
        destroy() {
          gone = true;
          stop();
          document.removeEventListener("visibilitychange", onVisibility);
          for (const entry of live.values()) destroyBlade(entry);
          live.clear();
          try {
            if (globeHandle && globeHandle.destroy) globeHandle.destroy();
          } catch (e) {
            console.error("GeoTrace globe destroy failed", e);
          }
        },
      };
    },
  };
}
