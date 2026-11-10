// Dashboard: core tiles plus every dashboard.tile and dashboard.card a plugin contributes.
import { esc, fmtAgo } from "../util.js";

function coreTiles(state) {
  const counts = { online: 0, quiet: 0, offline: 0 };
  for (const d of state.devices) if (d.status in counts) counts[d.status]++;
  const sweep = state.jobs.find((j) => j.owner === "core" && j.name === "scan");
  return [
    { id: "online", k: "Devices online", v: `${counts.online}<small>/ ${state.devices.length}</small>`, s: "online / total" },
    { id: "quiet", k: "Quiet", v: String(counts.quiet), s: "answer ARP, not ping" },
    { id: "offline", k: "Offline", v: String(counts.offline), s: "not seen recently" },
    {
      id: "sweep",
      k: "Last sweep",
      v: sweep && sweep.last_run_ms ? esc(fmtAgo(sweep.last_run_ms)) : "–",
      s: sweep && sweep.last_ok === false ? esc(sweep.last_error || "failed") : "",
    },
  ];
}

function safe(plugin, fn, fallback) {
  try {
    return fn();
  } catch (e) {
    console.error(`Plugin "${plugin}" dashboard slot failed`, e);
    return fallback(e);
  }
}

export function mountDashboard(el, ctx) {
  const root = document.createElement("div");
  el.appendChild(root);

  function render(state) {
    const tiles = coreTiles(state).map(
      (t) => `<div class="tile" data-tile="${esc(t.id)}"><div class="k">${esc(t.k)}</div><div class="v">${t.v}</div><div class="s">${t.s ? esc(t.s) : "&nbsp;"}</div></div>`,
    );
    for (const spec of ctx.host.get("dashboard.tile")) {
      tiles.push(
        safe(
          spec.pluginId,
          () => `<div class="tile" data-plugin="${esc(spec.pluginId)}">${spec.render(state)}</div>`,
          (e) => `<div class="tile"><div class="k">${esc(spec.pluginId)}</div><div class="s err">${esc(e.message)}</div></div>`,
        ),
      );
    }
    const cards = ctx.host.get("dashboard.card").map((spec) =>
      safe(
        spec.pluginId,
        () => `<section class="card" data-plugin="${esc(spec.pluginId)}">${spec.title ? `<h2>${esc(spec.title)}</h2>` : ""}${spec.render(state)}</section>`,
        (e) => `<section class="card"><h2>${esc(spec.pluginId)}</h2><p class="err">${esc(e.message)}</p></section>`,
      ),
    );
    const failed = Object.entries(ctx.host.errors).map(
      ([id, msg]) => `<section class="card" data-plugin="${esc(id)}"><h2>${esc(id)}</h2><p class="err">Its interface failed to load: ${esc(msg)}</p></section>`,
    );
    root.innerHTML = `<section class="tiles" aria-label="Summary">${tiles.join("")}</section>${cards.join("")}${failed.join("")}`;
  }

  return { update: render };
}
