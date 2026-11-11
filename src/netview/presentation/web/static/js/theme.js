// Theme choice: which stylesheet is active. "system" keeps the two media-query links; a theme id swaps in one link.
const KEY = "netview-theme";
const MEDIA = { "theme-light": "(prefers-color-scheme: light)", "theme-dark": "(prefers-color-scheme: dark)" };

/** The themes that ship with NetView, usable before the theme list has been fetched. */
export const BUILTIN_THEMES = ["daylight", "graphite", "harbor", "contrast"].map((id) => ({
  id,
  url: `/static/themes/${id}.css`,
  error: null,
}));

/** {mode: "system"} or {mode: "fixed", theme}. An unknown or broken theme id falls back to system. */
export function resolveTheme(pref, themes) {
  const theme = (themes || []).find((t) => t.id === pref);
  if (!theme || theme.error) return { mode: "system" };
  return { mode: "fixed", theme };
}

/** Point the document's theme links at the resolved choice. */
export function applyTheme(resolved, doc = document) {
  const explicit = doc.getElementById("theme");
  if (resolved.mode === "fixed") {
    let link = explicit;
    if (!link) {
      link = doc.createElement("link");
      link.setAttribute("rel", "stylesheet");
      link.id = "theme";
      doc.head.appendChild(link);
    }
    if (link.getAttribute("href") !== resolved.theme.url) link.setAttribute("href", resolved.theme.url);
    link.removeAttribute("media");
    for (const id of Object.keys(MEDIA)) {
      const el = doc.getElementById(id);
      if (el) el.setAttribute("media", "not all");
    }
    doc.documentElement.dataset.theme = resolved.theme.id;
  } else {
    if (explicit) explicit.remove();
    for (const [id, media] of Object.entries(MEDIA)) {
      const el = doc.getElementById(id);
      if (el) el.setAttribute("media", media);
    }
    delete doc.documentElement.dataset.theme;
  }
}

/** The saved choice: "system" (the default) or a theme id. Storage can be blocked, so this never throws. */
export function loadThemePref() {
  try {
    return globalThis.localStorage.getItem(KEY) || "system";
  } catch (e) {
    return "system";
  }
}

export function saveThemePref(id) {
  try {
    globalThis.localStorage.setItem(KEY, id);
  } catch (e) {
    /* not persisted */
  }
}
