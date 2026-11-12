// The change-password dialog. When `forced` it cannot be dismissed until the change succeeds.
import { apiSend } from "../api.js";
import { toast } from "../toast.js";

let open = null;

/** Show the dialog (one at a time). A forced dialog stays until the password has been changed. */
export function openPasswordDialog({ forced = false } = {}) {
  if (open) {
    if (forced) open.forced = true;
    return;
  }
  const dlg = document.createElement("dialog");
  dlg.className = "dlg small";
  dlg.setAttribute("aria-labelledby", "pw-title");
  dlg.innerHTML = `
    <form class="pwform" autocomplete="off">
      <div class="dlg-head"><h2 id="pw-title">Change password</h2></div>
      <div class="dlg-pane">
        ${forced ? '<p class="note" data-forced>You must choose a new password before you continue.</p>' : ""}
        <label for="pw-current">Current password</label>
        <input id="pw-current" name="current" type="password" autocomplete="current-password" required>
        <label for="pw-new">New password</label>
        <input id="pw-new" name="new" type="password" autocomplete="new-password" required>
        <label for="pw-confirm">Confirm new password</label>
        <input id="pw-confirm" name="confirm" type="password" autocomplete="new-password" required>
        <p class="err" role="alert" data-msg></p>
      </div>
      <div class="dlg-foot">
        ${forced ? "" : '<button type="button" data-cancel>Cancel</button>'}
        <button type="submit" class="primary">Change password</button>
      </div>
    </form>`;
  document.body.appendChild(dlg);
  const state = { forced, dlg };
  open = state;
  const form = dlg.querySelector("form");
  const msg = dlg.querySelector("[data-msg]");
  const close = () => {
    dlg.close();
    dlg.remove();
    open = null;
  };
  dlg.addEventListener("cancel", (e) => {
    if (state.forced) e.preventDefault();
    else close();
  });
  const cancel = dlg.querySelector("[data-cancel]");
  if (cancel) cancel.addEventListener("click", close);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "";
    if (form.elements.new.value !== form.elements.confirm.value) {
      msg.textContent = "The passwords don't match";
      return;
    }
    try {
      await apiSend("POST", "/api/v1/auth/password", {
        current: form.elements.current.value,
        new: form.elements.new.value,
      });
      close();
      toast("Password changed");
    } catch (err) {
      msg.textContent = err.message;
    }
  });
  dlg.showModal();
}
