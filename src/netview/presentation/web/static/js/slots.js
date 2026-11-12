// Slots: the places a plugin's UI module can contribute to.
//
//   Every spec the host stores carries `pluginId` (the plugin's source id, used in URLs and routes), `pluginGuid`
//   (used in permission ids and saved report sections) and `pluginDisplayName`.
//   Any spec may carry `permission`: a relative id ("use" means "<pluginGuid>.use") or a core one; the spec is
//   left out for a user who lacks it.
//
//   dashboard.tile        {id, order = 50, render(state) -> html}
//   dashboard.card        {id, title?, sub?, order = 30, span = "half" | "full" | "third",
//                          render(state) -> html  or  draw(el, state)}   (cards are persistent, see pages/dashboard.js)
//   devices.column        {id, label, sub?, render(d, state) -> html | text(d, state), sortKey?(d, state), groupKey?(d),
//                          available?(state) -> bool}   (while available() is false the column is not offered at all)
//   report.live-section   {id, draw(el, {ip, device, state})}              (redrawn on every state update)
//   report.section        {section: <section id>, draw(el, section, report)}   (matched on plugin id and section id)
//   page                  {id, title, mount(el, ctx), unavailable?() -> string | null}   (a reason disables the page's
//                          nav tab and is shown as its tooltip; a click opens the plugin's settings)
//   settings.section      {title?, tab?, render(body, {pluginId, apiBase, apiGet, apiSend, util})}   (tab: a tab of the
//                          plugin's settings form, see settings_layout.py; without one the section always shows)
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

/** The permission id a plugin's relative one stands for: "use" -> "<guid>.use"; a "core.*" id passes through. */
export function resolvePermission(pluginGuid, rel) {
  if (typeof rel !== "string" || rel === "") return null;
  if (rel.startsWith("core.") || rel.startsWith(pluginGuid + ".")) return rel;
  return `${pluginGuid}.${rel}`;
}

const ALLOW_ALL = { user: { username: "", displayName: "" }, provider: "local", can: () => true, isAdmin: true, mustChange: false };

/** `auth` (see auth.js createAuth) decides which plugin UI is loaded and which slot specs are offered. */
export function createUiHost(auth = ALLOW_ALL) {
  let renderer = null;
  let reportOpener = null;
  const slots = new Map(SLOT_NAMES.map((n) => [n, []]));
  const host = {
    /** Plugin ids whose UI module failed to load, with the message. */
    errors: {},
    /** Set by the shell once it knows who is signed in. */
    setAuth(next) {
      auth = next;
    },
    /** Set by the shell: how to redraw the current page. */
    setRenderer(fn) {
      renderer = fn;
    },
    /** Set by the shell: how to open the report dialog. */
    setReportOpener(fn) {
      reportOpener = fn;
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
      return slots.get(name).filter((spec) => {
        if (spec.permission == null) return true;
        const id = resolvePermission(spec.pluginGuid ?? spec.pluginId, spec.permission);
        return id === null || auth.can(id);
      });
    },
    /**
     * Drop everything an uninstalled plugin contributed (pages, tiles, cards, columns, sections) and its load error.
     * Returns true when `currentPath` is one of its pages, so the shell can leave it; otherwise the shell is asked to redraw.
     */
    removePlugin(pluginId, currentPath = "") {
      const id = String(pluginId);
      for (const [name, list] of slots) slots.set(name, list.filter((spec) => String(spec.pluginId) !== id));
      delete host.errors[id];
      const onItsPage = String(currentPath).startsWith(`/p/${id}/`);
      if (!onItsPage) host.requestRender();
      return onItsPage;
    },
    /** Import each active plugin's UI module and let it register its slots. */
    async loadPlugins(pluginInfos) {
      for (const info of pluginInfos) {
        if (info.state !== "active" || !info.ui_module) continue;
        const id = info.id; // the source id, as the server keys URLs and routes
        const guid = info.guid; // permissions and saved sections use the guid
        if (!auth.can(guid + ".view")) continue;
        try {
          const mod = await import(info.ui_module);
          const uiApi = {
            slot: (name, spec) => host.slot(name, { ...spec, pluginId: id, pluginGuid: guid, pluginDisplayName: info.display_name }),
            apiBase: "/api/v1/plugins/" + id,
            apiGet,
            apiSend,
            util,
            pluginId: id,
            user: auth.user,
            can: (rel) => auth.can(resolvePermission(guid, rel) || ""),
            requestRender: () => host.requestRender(),
            openReport: (ip, options) => (reportOpener ? reportOpener(ip, options) : undefined),
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
