// Appearance tab: a radio grid of theme cards ("Match system" first).
import { apiGet } from "../api.js";
import { esc } from "../util.js";
import { applyTheme, loadThemePref, resolveTheme, saveThemePref } from "../theme.js";

const SYSTEM_BARS = ["#ffffff", "#22272e", "#3987e5"];

function bars(colors) {
  return `<span class="bars">${colors.map((c) => `<span style="background:${esc(c)}"></span>`).join("")}</span>`;
}

function card(id, name, sub, colors, selected, error) {
  return `<button type="button" class="swatch${selected ? " on" : ""}" role="radio" aria-checked="${selected}" data-theme-id="${esc(id)}" tabindex="${selected ? 0 : -1}" ${error ? "disabled" : ""}>
    ${bars(colors)}
    <span><b>${esc(name)}</b>${sub ? ` <span class="scope">${esc(sub)}</span>` : ""}</span>
    ${error ? `<span class="err">${esc(error)}</span>` : ""}
  </button>`;
}

/** Fill `pane` with the theme picker. */
export async function renderAppearance(pane) {
  pane.innerHTML = '<h3>Appearance</h3><p class="empty">Loading themes…</p>';
  let data;
  try {
    data = await apiGet("/api/v1/themes");
  } catch (e) {
    pane.innerHTML = `<h3>Appearance</h3><p class="err">Could not load themes: ${esc(e.message)}</p>`;
    return;
  }
  const themes = data.themes;
  let pref = loadThemePref();
  if (resolveTheme(pref, themes).mode === "system") pref = "system";

  function render() {
    const cards = [card("system", "Match system", "Light or dark to suit this device", SYSTEM_BARS, pref === "system", null)]
      .concat(
        themes.map((t) =>
          card(t.id, t.name, `${t.scheme}${t.source === "user" ? ", yours" : ""}`, t.preview, pref === t.id, t.error),
        ),
      )
      .join("");
    pane.innerHTML = `<h3>Appearance</h3>
      <p class="note">Choose how netview looks. The choice is kept in this browser.</p>
      <div class="swatches" role="radiogroup" aria-label="Theme">${cards}</div>
      <p class="note">Add your own themes as CSS files in <code>${esc(data.user_dir)}</code>. Start from a copy of <code>graphite.css</code>; the header comment and every colour setting are described in the themes README.</p>`;
  }

  function choose(id) {
    pref = id;
    saveThemePref(id);
    applyTheme(resolveTheme(id, themes));
    render();
    const on = pane.querySelector(`[data-theme-id="${CSS.escape(id)}"]`);
    if (on) on.focus();
  }

  pane.addEventListener("click", (e) => {
    const b = e.target.closest("[data-theme-id]");
    if (b && !b.disabled) choose(b.dataset.themeId);
  });
  pane.addEventListener("keydown", (e) => {
    const b = e.target.closest("[data-theme-id]");
    if (!b || !["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const all = [...pane.querySelectorAll("[data-theme-id]:not([disabled])")];
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
    const next = all[(all.indexOf(b) + step + all.length) % all.length];
    choose(next.dataset.themeId);
  });
  render();
}
