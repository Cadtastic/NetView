// Slots: the places a plugin's UI module can contribute to.
import { apiGet, apiSend } from "./api.js";
import * as util from "./util.js";

export const SLOT_NAMES = [
  "dashboard.tile",
  "dashboard.card",
  "devices.column",
  "report.live-section",
  "report.section",
  "page",
  "settings.section",
];

export function createUiHost() {
  let renderer = null;
  const slots = new Map(SLOT_NAMES.map((n) => [n, []]));
  const host = {
    /** Plugin ids whose UI module failed to load, with the message. */
    errors: {},
    /** Set by the shell: how to redraw the current page. */
    setRenderer(fn) {
      renderer = fn;
    },
    /** Ask the shell to redraw the current page (a plugin calls this when its data arrives). */
    requestRender() {
      if (renderer) renderer();
    },
    slot(name, spec) {
      if (!slots.has(name)) throw new Error(`Unknown slot "${name}"`);
      slots.get(name).push(spec);
    },
    get(name) {
      if (!slots.has(name)) throw new Error(`Unknown slot "${name}"`);
      return [...slots.get(name)];
    },
    /** Import each active plugin's UI module and let it register its slots. */
    async loadPlugins(pluginInfos) {
      for (const info of pluginInfos) {
        if (info.state !== "active" || !info.ui_module) continue;
        const id = info.id;
        try {
          const mod = await import(info.ui_module);
          const uiApi = {
            slot: (name, spec) => host.slot(name, { ...spec, pluginId: id }),
            apiBase: "/api/v1/plugins/" + id,
            apiGet,
            apiSend,
            util,
            pluginId: id,
            requestRender: () => host.requestRender(),
          };
          await mod.default(uiApi);
        } catch (e) {
          console.error(`Plugin "${id}" UI failed to load`, e);
          host.errors[id] = e && e.message ? e.message : String(e);
        }
      }
    },
  };
  return host;
}
