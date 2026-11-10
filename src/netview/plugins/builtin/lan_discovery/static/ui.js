// lan_discovery UI: a dashboard tile showing how much of the subnet answered the last sweep.
export default function register(ui) {
  const { esc } = ui.util;
  let summary = null;
  let loading = false;
  let lastState = null;

  function refresh() {
    if (loading) return;
    loading = true;
    ui.apiGet(`${ui.apiBase}/summary`)
      .then((s) => {
        summary = s;
      })
      .catch(() => {})
      .finally(() => {
        loading = false;
        ui.requestRender(); // draw the value that just arrived, not the previous one
      });
  }
  refresh();

  ui.slot("dashboard.tile", {
    render(state) {
      // Refetch once per state update. The re-render requested above passes the same state object,
      // so it does not start another fetch.
      if (state !== lastState) {
        lastState = state;
        refresh();
      }
      if (!summary || summary.last_ms == null) {
        return `<div class="k">Sweep coverage</div><div class="v">–</div><div class="s">no sweep yet</div>`;
      }
      const seconds = (Number(summary.duration_ms) / 1000).toFixed(1);
      return (
        `<div class="k">Sweep coverage</div>` +
        `<div class="v">${esc(summary.replied)}<small>of ${esc(summary.hosts)} answered</small></div>` +
        `<div class="s">took ${esc(seconds)} s</div>`
      );
    },
  });
}
