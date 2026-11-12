// Uninstall: the section in a plugin's overlay, its confirm dialog, and what happens after the server answers.
import { apiGet, apiSend } from "../api.js";
import { esc } from "../util.js";
import { toast } from "../toast.js";

const BODY = "Its folder is deleted. It stops now and is fully gone after netview restarts.";
const DATA_LABEL = "Also delete its saved settings and data";
const FAIL_PREFIX = "Uninstall didn't finish:";

/** The name shown in the dialog and toast: display_name, falling back to name. */
export function uninstallName(info) {
  return info.display_name || info.name;
}

/** "" unless the plugin can be uninstalled (a folder directly in the data folder; a stopped retry card counts). */
export function uninstallSectionHtml(info) {
  if (!info || !info.uninstallable) return "";
  return `<section class="uninstall"><h4>Uninstall</h4>
    <p class="sub">Remove this plugin from netview.</p>
    <button type="button" class="danger" data-uninstall>Uninstall</button>
    <div class="err uninstall-err" role="status"></div></section>`;
}

/** The inside of the confirm dialog. The data checkbox appears only for a card that owns its data. */
export function confirmUninstallHtml(info) {
  const data = info.owns_data
    ? `<label class="perm-row"><input type="checkbox" data-delete-data> ${esc(DATA_LABEL)}</label>`
    : "";
  return `<div class="dlg-head"><h2 id="uninstall-title">Uninstall ${esc(uninstallName(info))}?</h2></div>
    <div class="admin-dlg uninstall-body"><p>${esc(BODY)}</p>${data}
      <div class="err uninstall-dlg-err" role="status"></div>
      <div class="inline uninstall-actions"><button type="button" data-cancel>Cancel</button>
        <button type="button" class="danger" data-confirm>Uninstall</button></div></div>`;
}

/** The message for an uninstall that couldn't move the folder. */
export function failureText(reason) {
  const r = String(reason ?? "").trim();
  if (r.startsWith(FAIL_PREFIX)) return r; // the server's own text, already complete
  return `${FAIL_PREFIX} ${r || "the folder is in use"}. It will be removed when netview restarts`;
}

export function toastText(info) {
  return `${uninstallName(info)} uninstalled`;
}

/** Ask the server to uninstall. Data is only deleted for a card that owns it. Resolves {finished, error}. */
export function runUninstall(info, deleteData, send = apiSend) {
  return send("POST", "/api/v1/plugins/uninstall", { folder: info.folder, delete_data: !!(deleteData && info.owns_data) });
}

/** Show the confirm dialog on top of the overlay; resolves {cancelled} or {answer} once the server replied. */
function confirmDialog(info) {
  return new Promise((resolve) => {
    const el = document.createElement("dialog");
    el.className = "dlg small uninstall-dlg";
    el.setAttribute("aria-labelledby", "uninstall-title");
    el.innerHTML = confirmUninstallHtml(info);
    const err = el.querySelector(".uninstall-dlg-err");
    const confirmBtn = el.querySelector("[data-confirm]");
    let result = { cancelled: true };
    el.addEventListener("close", () => {
      el.remove();
      resolve(result);
    });
    el.querySelector("[data-cancel]").addEventListener("click", () => el.close());
    confirmBtn.addEventListener("click", async () => {
      const box = el.querySelector("[data-delete-data]");
      confirmBtn.disabled = true;
      err.textContent = "";
      try {
        result = { answer: await runUninstall(info, !!(box && box.checked)) };
        el.close();
      } catch (e) {
        err.textContent = e.message; // 404 and 409 stay in the dialog so the reason can be read
        confirmBtn.disabled = false;
      }
    });
    document.body.appendChild(el);
    el.showModal();
    el.querySelector("[data-cancel]").focus();
  });
}

/**
 * Run the whole flow for `info`. `ctx.finishUninstall(info)` removes the plugin everywhere on success;
 * `ctx.reloadPlugins()` brings back the stopped card after an unfinished one; `showError(text)` writes into the overlay.
 */
export async function startUninstall(ctx, info, showError) {
  showError("");
  const { cancelled, answer } = await confirmDialog(info);
  if (cancelled) return;
  if (answer.finished) {
    await ctx.finishUninstall(info);
    ctx.redraw(); // the overlay finds its plugin gone and closes; the Installed grid then drops the card
    toast(toastText(info));
    return;
  }
  showError(failureText(answer.error));
  await ctx.reloadPlugins(); // the plugin is listed again as a stopped card that can be uninstalled again
  ctx.redraw();
}

/** The Available count after an uninstall (the plugin may be offered there again). Resolves null on failure. */
export async function availableCount() {
  try {
    return (await apiGet("/api/v1/plugins/catalog")).plugins.length;
  } catch (e) {
    return null;
  }
}
