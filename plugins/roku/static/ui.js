// Roku UI module: the Roku page (tabs, Control view) and the Roku settings section (no title of its own: the plugin heading above it already says Roku).
import { toast } from "/static/js/toast.js";
import { createStore } from "./store.js";
import { renderRokuSettings } from "./settings.js";
import { createPage } from "./page.js";

export default function register(ui) {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `/plugins/${ui.pluginId}/static/roku.css`;
  document.head.appendChild(link);

  const store = createStore(ui);
  store.load();

  ui.slot("page", createPage(ui, store, { toast }));

  ui.slot("settings.section", {
    render: (body, ctx) => renderRokuSettings(body, ctx, store),
  });
}
