// lan_discovery UI: a dashboard tile showing the last sweep.
export default function register(ui) {
  const { esc } = ui.util;
  let summary = null;
  let loading = false;

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
      });
  }
  refresh();

  ui.slot("dashboard.tile", {
    render() {
      refresh(); // shows the previous value now and the new one at the next dashboard refresh
      if (!summary || summary.last_ms == null) {
        return `<div class="k">Last sweep</div><div class="v">–</div><div class="s">no sweep yet</div>`;
      }
      return (
        `<div class="k">Last sweep</div>` +
        `<div class="v">${esc(summary.replied)}<small>/ ${esc(summary.hosts)}</small></div>` +
        `<div class="s">replied, ${esc(summary.duration_ms)} ms</div>`
      );
    },
  });
}
