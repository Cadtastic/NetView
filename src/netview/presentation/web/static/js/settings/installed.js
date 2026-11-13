// The Installed gallery: a filterable grid of plugin cards; a card opens the settings overlay.
import { toggle } from "./plugins-tab.js";
import { findByKey, installedCardHtml, matchesFilter, sortInstalled } from "./gallery.js";
import { openPluginOverlay } from "./overlay.js";

/** Draw the Installed gallery into `pane`. With `overlayId` (a card key, or a plugin's id), that plugin's overlay opens straight away. */
export function renderInstalled(pane, ctx, { overlayId = null } = {}) {
  pane.innerHTML = `<h3>Installed plugins</h3>
    <div class="gtools"><input type="search" class="gfilter" placeholder="Filter plugins" aria-label="Filter installed plugins"></div>
    <div class="pgrid"></div><div class="empty gempty" hidden></div>`;
  const grid = pane.querySelector(".pgrid");
  const empty = pane.querySelector(".gempty");
  const filter = pane.querySelector(".gfilter");
  const scroller = () => pane.closest(".dlg-pane");

  const draw = () => {
    const sc = scroller();
    const top = sc ? sc.scrollTop : 0;
    const list = sortInstalled(ctx.plugins()).filter((p) => matchesFilter(p, filter.value));
    grid.innerHTML = list.map((p) => installedCardHtml(p, ctx.can("core.plugins"))).join("");
    empty.hidden = list.length > 0;
    empty.textContent = ctx.plugins().length ? "No plugins found." : "No plugins are installed.";
    if (sc) sc.scrollTop = top;
  };

  const open = (key, card) =>
    openPluginOverlay(ctx, key, card, {
      onClose: () => {
        draw();
        const info = findByKey(ctx.plugins(), key);
        const back = info && grid.querySelector(`[data-key="${CSS.escape(info.card_key)}"]`);
        if (back) back.focus();
      },
    });

  filter.addEventListener("input", draw);
  grid.addEventListener("click", (e) => {
    if (e.target.closest(".switch")) return;
    const card = e.target.closest(".pcard");
    if (card) open(card.dataset.key, card);
  });
  grid.addEventListener("keydown", (e) => {
    if (e.target.classList && e.target.classList.contains("pcard") && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      open(e.target.dataset.key, e.target);
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
  if (overlayId) open(overlayId, null); // an id that is not installed opens nothing
}
