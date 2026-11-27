// GeoTrace UI module: the GeoTrace page (globe, rail, blades). Later modules register blade contents and the globe on `shell`.
import { openSettings } from "/static/js/settings/dialog.js";
import { createGtApi } from "./api.js";
import { createPage } from "./page.js";
import { registerGlobe } from "./globe.js";
import { shell } from "./shell.js";
import { renderHome, renderLocationData, renderGlobe } from "./settings.js";
import "./targets.js"; // each of these registers its blade on `shell` when loaded
import "./route.js";
import "./once.js";
import "./compare.js";
import "./trends.js";

export default function register(ui) {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `/plugins/${ui.pluginId}/static/geotrace.css`;
  document.head.appendChild(link);

  const api = createGtApi(ui.pluginId);
  registerGlobe(ui.pluginId);
  ui.slot("page", createPage(ui, { api, shell, openSettings }));

  // Settings sections for what the form cannot do. Each sits on the tab of the fields it goes with.
  const reopen = () => openSettings(`plugin:${ui.pluginId}`);
  ui.slot("settings.section", { title: "Find your home", tab: "General", render: (body, ctx) => renderHome(body, ctx, { reopen }) });
  ui.slot("settings.section", { title: "Globe files", tab: "Map", render: renderGlobe });
  ui.slot("settings.section", { title: "Location data status", tab: "Location data", render: renderLocationData });
}
