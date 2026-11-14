// Admin -> General: sign-in and session policy numbers, and the read-only mode line.
import { apiGet, apiSend } from "../../api.js";
import { esc } from "../../util.js";
import { toast } from "../../toast.js";
import { showError } from "./errors.js";
import { pageHeadHtml } from "../../blade.js";
import { save, undo } from "../../icons.js";

// key, label, seconds per displayed unit (1 = shown as is), default in displayed units, minimum
const FIELDS = [
  { key: "password_min_length", label: "Password minimum length", unit: 1, def: 12, min: 8 },
  { key: "session_idle_s", label: "Session idle timeout (hours)", unit: 3600, def: 8, min: 1 },
  { key: "session_max_s", label: "Session lifetime (days)", unit: 86400, def: 7, min: 1 },
  { key: "lockout_failures", label: "Sign-in failures allowed", unit: 1, def: 5, min: 1 },
  { key: "lockout_window_s", label: "Within (minutes)", unit: 60, def: 15, min: 1 },
  { key: "lockout_s", label: "Locked for (minutes)", unit: 60, def: 15, min: 1 },
];

/** Form rows for a policy (seconds as the server holds them): [{key, label, unit, value, default, min}]. */
export function generalFormModel(policy) {
  return FIELDS.map((f) => ({
    key: f.key,
    label: f.label,
    unit: f.unit,
    value: policy[f.key] / f.unit,
    default: f.def,
    min: f.min,
  }));
}

/** The policy (in seconds) a list of form rows describes. */
export function secondsFromForm(rows) {
  return Object.fromEntries(rows.map((r) => [r.key, Math.round(Number(r.value) * r.unit)]));
}

export const modeLine = (mode) =>
  `Mode: ${mode === "home" ? "Home" : "Enterprise"}. To change it, set mode in netview.toml or start netview serve with --mode.`;

const SUB = "Password and session rules. Changes apply at once.";
const COMMANDS = [
  { id: "save", label: "Save", icon: save },
  { id: "discard", label: "Discard changes", icon: undo },
];

export function mountGeneral(el) {
  el.innerHTML = `${pageHeadHtml({ title: "General", sub: SUB })}<p class="note" data-loading>Loading…</p>`;
  let dead = false;

  apiGet("/api/v1/admin/general")
    .then((g) => !dead && draw(g))
    .catch((e) => !dead && (el.querySelector("[data-loading]").textContent = e.message));

  function draw(g) {
    const rows = generalFormModel(g);
    el.innerHTML = `${pageHeadHtml({ title: "General", sub: SUB, commands: COMMANDS })}
      <form class="admin-form" autocomplete="off">
        ${rows
          .map(
            (r) => `<div class="field"><label class="lbl" for="gen-${esc(r.key)}">${esc(r.label)}</label>
              <div class="inline"><input id="gen-${esc(r.key)}" type="number" min="${r.min}" step="1" value="${esc(r.value)}" data-key="${esc(r.key)}" required>
              <span class="hint">Default ${esc(r.default)}</span>
              <button type="button" class="quiet small" data-reset="${esc(r.key)}">Reset to default</button></div></div>`,
          )
          .join("")}
        <p class="err" role="alert" data-msg></p>
      </form>
      <p class="note" data-mode></p>`;
    el.querySelector("[data-mode]").textContent = modeLine(g.mode);
    const form = el.querySelector("form");
    const msg = el.querySelector("[data-msg]");
    form.addEventListener("click", (e) => {
      const b = e.target.closest("[data-reset]");
      if (!b) return;
      const row = rows.find((r) => r.key === b.dataset.reset);
      form.querySelector(`[data-key="${row.key}"]`).value = row.default;
    });
    const submit = async () => {
      msg.textContent = "";
      if (!form.reportValidity()) return;
      const edited = rows.map((r) => ({ ...r, value: form.querySelector(`[data-key="${r.key}"]`).value }));
      try {
        const out = await apiSend("PATCH", "/api/v1/admin/general", secondsFromForm(edited));
        toast("Settings saved");
        if (!dead) draw(out);
      } catch (err) {
        showError(msg, err);
      }
    };
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      submit();
    });
    el.querySelector(".blade-cmd").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cmd]");
      if (!b) return;
      if (b.dataset.cmd === "save") submit();
      else if (b.dataset.cmd === "discard") draw(g);
    });
  }
  return { destroy: () => (dead = true) };
}
