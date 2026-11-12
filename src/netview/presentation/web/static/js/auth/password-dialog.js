// The change-password dialog. When `forced` it cannot be dismissed until the change succeeds.
import { apiGet, apiSend } from "../api.js";
import { wirePasswordChecks } from "../auth.js";
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
        <ul class="pw-checks" data-checks aria-live="polite"></ul>
        <p class="err" role="alert" data-msg></p>
      </div>
      <div class="dlg-foot">
        ${forced ? '<button type="button" data-signout>Sign out</button>' : '<button type="button" data-cancel>Cancel</button>'}
        <button type="submit" class="primary" data-submit disabled>Change password</button>
      </div>
    </form>`;
  document.body.appendChild(dlg);
  const state = { forced, dlg };
  open = state;
  const form = dlg.querySelector("form");
  const msg = dlg.querySelector("[data-msg]");
  let done = false;
  const close = () => {
    done = true;
    dlg.close();
    dlg.remove();
    open = null;
  };
  // Chromium can close a modal on a second Esc even after preventDefault; a forced dialog comes straight back.
  dlg.addEventListener("close", () => {
    if (state.forced && !done) dlg.showModal();
    else if (!done) {
      dlg.remove();
      open = null;
    }
  });
  dlg.addEventListener("cancel", (e) => {
    if (state.forced) e.preventDefault();
    else close();
  });
  const cancel = dlg.querySelector("[data-cancel]");
  if (cancel) cancel.addEventListener("click", close);
  const signout = dlg.querySelector("[data-signout]");
  if (signout) {
    signout.addEventListener("click", async () => {
      try {
        await apiSend("POST", "/api/v1/auth/logout");
      } catch (err) {
        /* leave for the sign-in page regardless */
      }
      location.href = "/login";
    });
  }
  const submitButton = dlg.querySelector("[data-submit]");
  // The username and the minimum come from /auth/me (allowed even while a change is pending).
  const who = { username: "", minLength: 12 };
  const recheck = wirePasswordChecks({
    root: form,
    list: dlg.querySelector("[data-checks]"),
    button: submitButton,
    read: () => ({
      password: form.elements.new.value,
      confirm: form.elements.confirm.value,
      current: form.elements.current.value,
      username: who.username,
      minLength: who.minLength,
    }),
    ready: () => form.elements.current.value !== "",
  });
  apiGet("/api/v1/auth/me")
    .then((me) => {
      who.username = me.username || "";
      who.minLength = me.password_min_length || 12;
      recheck();
    })
    .catch(() => {});
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (submitButton.disabled) return;
    msg.textContent = "";
    try {
      await apiSend("POST", "/api/v1/auth/password", {
        current: form.elements.current.value,
        new: form.elements.new.value,
      });
      const wasForced = state.forced;
      close();
      toast("Password changed");
      if (wasForced) location.reload(); // the shell started without plugins while the change was pending
    } catch (err) {
      msg.textContent = err.fields ? Object.values(err.fields).join(" ") : err.message;
    }
  });
  dlg.showModal();
}
