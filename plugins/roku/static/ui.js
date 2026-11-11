// Roku UI module: the Roku page (body arrives with the remote UI) and the "Roku" settings section.
import { createStore } from "./store.js";
import { renderRokuSettings } from "./settings.js";

export default function register(ui) {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `/plugins/${ui.pluginId}/static/roku.css`;
  document.head.appendChild(link);

  const store = createStore(ui);
  store.load();

  ui.slot("page", {
    id: "tv",
    title: "Roku",
    unavailable: () => store.unavailable(),
    mount(el) {
      el.innerHTML = `<div class="card"></div>`;
      return { update() {}, destroy() {} };
    },
  });

  ui.slot("settings.section", {
    title: "Roku",
    render: (body, ctx) => renderRokuSettings(body, ctx, store),
  });
}
