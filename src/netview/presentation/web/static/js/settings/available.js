// The Available gallery: plugins in the GitHub catalog that are not installed, with Install and its progress.
import { apiGet, apiSend } from "../api.js";
import { availableCardHtml, availableFooter, catalogLine, emptyAvailableText, matchesFilter } from "./gallery.js";

/** Draw the Available gallery into `pane`. `ctx.installer` holds install jobs for the whole dialog; `ctx.setAvailable(n)` keeps the rail current. */
export function renderAvailable(pane, ctx) {
  pane.innerHTML = `<h3>Available plugins</h3>
    <p class="sub gline" role="status"></p>
    <div class="gtools"><input type="search" class="gfilter" placeholder="Filter plugins" aria-label="Filter available plugins">
      <button type="button" class="small" data-refresh>Refresh</button></div>
    <div class="pgrid"></div><div class="empty gempty" hidden></div>`;
  const grid = pane.querySelector(".pgrid");
  const empty = pane.querySelector(".gempty");
  const line = pane.querySelector(".gline");
  const filter = pane.querySelector(".gfilter");
  const refreshBtn = pane.querySelector("[data-refresh]");
  let cat = { source: "", fetched_at_ms: null, error: null, stale: false, plugins: [] };
  const alive = () => pane.isConnected && !!pane.closest("dialog[open]");

  const draw = () => {
    const sc = pane.closest(".dlg-pane");
    const top = sc ? sc.scrollTop : 0;
    const list = cat.plugins.filter((p) => matchesFilter(p, filter.value));
    grid.innerHTML = list.map((p) => availableCardHtml(p, installer.get(p.id))).join("");
    empty.hidden = list.length > 0;
    empty.textContent = emptyAvailableText(cat, filter.value.trim() !== "" && cat.plugins.length > 0);
    line.textContent = catalogLine(cat, Date.now());
    if (sc) sc.scrollTop = top;
  };

  const apply = (next) => {
    cat = next;
    if (ctx.setAvailable) ctx.setAvailable(cat.plugins.length);
    draw();
  };

  const refresh = async () => {
    refreshBtn.disabled = true;
    try {
      apply(await apiSend("POST", "/api/v1/plugins/catalog/refresh"));
    } catch (e) {
      cat = { ...cat, error: e.message || "Couldn't reach GitHub" };
      draw();
    } finally {
      refreshBtn.disabled = false;
    }
  };

  const installer = ctx.installer;
  const cardFoot = (id) => grid.querySelector(`[data-id="${CSS.escape(id)}"] .pfoot`);

  // Install state lives in the dialog's installer; this pane only draws it. Per-tick progress touches one card's footer.
  const unsubscribe = installer.subscribe((e) => {
    if (!pane.isConnected) {
      unsubscribe();
      return;
    }
    if (e.type === "done") {
      cat = { ...cat, plugins: cat.plugins.filter((p) => p.id !== e.id) };
      if (ctx.setAvailable) ctx.setAvailable(cat.plugins.length);
      draw();
      return;
    }
    const foot = cardFoot(e.id);
    const entry = cat.plugins.find((p) => p.id === e.id);
    if (foot && entry) foot.innerHTML = availableFooter(entry, installer.get(e.id));
    else draw();
  });

  const install = (id) => {
    const entry = cat.plugins.find((p) => p.id === id);
    return installer.install(id, entry ? entry.name : id);
  };

  filter.addEventListener("input", draw);
  refreshBtn.addEventListener("click", refresh);
  grid.addEventListener("click", (e) => {
    const b = e.target.closest("[data-install]");
    if (b && !b.disabled) install(b.dataset.install);
  });

  (async () => {
    try {
      apply(await apiGet("/api/v1/plugins/catalog"));
    } catch (e) {
      cat = { ...cat, error: e.message || "Couldn't reach GitHub" };
      draw();
      return;
    }
    if (cat.stale && alive()) await refresh(); // in the background: the cached list is already on screen
  })();
  draw();
}
