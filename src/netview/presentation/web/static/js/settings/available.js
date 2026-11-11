// The Available gallery: plugins in the GitHub catalog that are not installed, with Install and its progress.
import { apiGet, apiSend } from "../api.js";
import { toast } from "../toast.js";
import { availableCardHtml, catalogLine, emptyAvailableText, matchesFilter } from "./gallery.js";

const POLL_MS = 300;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** Draw the Available gallery into `pane`. `ctx.reloadPlugins()` and `ctx.setAvailable(n)` keep the dialog's rail current. */
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
  const jobs = new Map(); // plugin id -> {job, state, percent, error}
  const queue = []; // plugin ids waiting to be polled, in order
  let polling = false;

  const alive = () => pane.isConnected && !!pane.closest("dialog[open]");

  const draw = () => {
    const sc = pane.closest(".dlg-pane");
    const top = sc ? sc.scrollTop : 0;
    const list = cat.plugins.filter((p) => matchesFilter(p, filter.value));
    grid.innerHTML = list.map((p) => availableCardHtml(p, jobs.get(p.id))).join("");
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

  const finish = async (id) => {
    const entry = cat.plugins.find((p) => p.id === id);
    jobs.delete(id);
    cat = { ...cat, plugins: cat.plugins.filter((p) => p.id !== id) };
    if (ctx.reloadPlugins) await ctx.reloadPlugins();
    if (ctx.setAvailable) ctx.setAvailable(cat.plugins.length);
    toast(`${entry ? entry.name : id} installed. Restart netview to load it.`);
    if (alive()) draw();
  };

  const runQueue = async () => {
    if (polling) return;
    polling = true;
    try {
      while (queue.length && alive()) {
        const id = queue.shift();
        const mine = jobs.get(id);
        if (!mine || !mine.job) continue;
        for (;;) {
          let job;
          try {
            job = await apiGet(`/api/v1/plugins/install/${encodeURIComponent(mine.job)}`);
          } catch (e) {
            jobs.set(id, { job: mine.job, state: "failed", percent: null, error: e.message });
            break;
          }
          if (!alive()) return;
          jobs.set(id, { job: mine.job, state: job.state, percent: job.percent, error: job.error });
          if (job.state === "done") {
            await finish(id);
            break;
          }
          draw();
          if (job.state === "failed") break;
          await wait(POLL_MS);
        }
        if (alive()) draw();
      }
    } finally {
      polling = false;
    }
  };

  const install = async (id) => {
    const cur = jobs.get(id);
    if (cur && cur.state !== "failed") return;
    jobs.set(id, { job: null, state: "queued", percent: null, error: null });
    draw();
    try {
      const job = await apiSend("POST", "/api/v1/plugins/install", { id });
      jobs.set(id, { job: job.job, state: job.state, percent: job.percent, error: job.error });
      queue.push(id);
      runQueue();
    } catch (e) {
      jobs.set(id, { job: null, state: "failed", percent: null, error: e.message || "Install failed" });
    }
    if (alive()) draw();
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
