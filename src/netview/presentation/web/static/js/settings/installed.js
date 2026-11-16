// The Installed gallery: a filterable grid of plugin cards; a card opens the plugin's child blade.
import { toggle } from "./plugins-tab.js";
import { findByKey, installedCardHtml, matchesFilter, sortInstalled } from "./gallery.js";
import { openPluginBlade } from "./plugin-blade.js";

/** Draw the Installed gallery into `pane`. With `overlayId` (a card key, or a plugin's id), that plugin's child blade opens straight away. */
export function renderInstalled(pane, ctx, { blade, overlayId = null } = {}) {
  pane.innerHTML = `<div class="gtools"><input type="search" class="gfilter" placeholder="Filter plugins" aria-label="Filter installed plugins"></div>
    <div class="pgrid"></div><div class="empty gempty" hidden></div>`;
  const grid = pane.querySelector(".pgrid");
  const empty = pane.querySelector(".gempty");
  const filter = pane.querySelector(".gfilter");
  const scroller = () => pane.closest(".blade-page");

  const draw = () => {
    const sc = scroller();
    const top = sc ? sc.scrollTop : 0;
    const list = sortInstalled(ctx.plugins()).filter((p) => matchesFilter(p, filter.value));
    grid.innerHTML = list.map((p) => installedCardHtml(p, ctx.can("core.plugins"))).join("");
    empty.hidden = list.length > 0;
    empty.textContent = ctx.plugins().length ? "No plugins found." : "No plugins are installed.";
    if (sc) sc.scrollTop = top;
  };

  // The grid sits under the child blade, so a change made there (enable switch, settings, uninstall) shows at once.
  const live = {
    ...ctx,
    replacePlugin(info) {
      ctx.replacePlugin(info);
      draw();
    },
    removePlugin(info) {
      ctx.removePlugin(info);
      draw();
    },
    finishUninstall(info) {
      ctx.finishUninstall(info);
      draw();
    },
    async reloadPlugins() {
      await ctx.reloadPlugins();
      draw();
    },
  };

  // Every close path (Cancel, X, Esc, the crumb) ends in the opener's focus(): redraw first, then focus the card that shows the plugin now.
  const open = (key) => {
    const back = {
      focus() {
        draw();
        const info = findByKey(ctx.plugins(), key);
        const card = info && grid.querySelector(`[data-key="${CSS.escape(info.card_key)}"]`);
        if (card) card.focus();
      },
    };
    return openPluginBlade(blade, live, key, back);
  };

  filter.addEventListener("input", draw);
  grid.addEventListener("click", (e) => {
    if (e.target.closest(".switch")) return;
    const card = e.target.closest(".pcard");
    if (card) open(card.dataset.key);
  });
  grid.addEventListener("keydown", (e) => {
    if (e.target.classList && e.target.classList.contains("pcard") && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      open(e.target.dataset.key);
    }
  });
  grid.addEventListener("change", async (e) => {
    const id = e.target.dataset && e.target.dataset.enable;
    if (!id) return;
    const info = await toggle(ctx, id, e.target.checked, null);
    if (info) draw();
    else e.target.checked = !e.target.checked;
  });

  draw();
  if (overlayId) open(overlayId); // an id that is not installed opens nothing
}
