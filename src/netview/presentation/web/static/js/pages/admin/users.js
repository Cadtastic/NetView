// Admin -> Users: the user table, "Add local user", and the edit dialog.
import { apiGet, apiSend } from "../../api.js";
import { esc, fmtAgo } from "../../util.js";
import { toast } from "../../toast.js";
import { openAdminDialog, showError } from "./dialog.js";
import { openPasswordDialog } from "../../auth/password-dialog.js";
import { wirePasswordChecks } from "../../auth.js";

/** One role checkbox per role, ticked for the ids in `held`. */
function roleBoxes(roles, held) {
  return roles
    .map(
      (r) => `<label class="perm-row"><input type="checkbox" data-role="${esc(r.id)}"${held.has(r.id) ? " checked" : ""}>
        <span class="perm-label">${esc(r.name)}</span></label>`,
    )
    .join("");
}

const pickedRoles = (root) => [...root.querySelectorAll("[data-role]")].filter((c) => c.checked).map((c) => c.dataset.role);

/** True for the signed-in user's own row: their password goes through self-service, which keeps their session. */
export function isOwnRow(user, auth) {
  return !!(auth && auth.user && user && user.username === auth.user.username);
}

/**
 * Why the signed-in admin can't manage `user`, or null when they can. Mirrors the server's rule: someone who
 * isn't an Administrator can only manage users with no more power than their own, and never an administrator.
 */
export function userLock(user, rolesById, auth) {
  if (!auth || auth.isAdmin) return null;
  if (user.builtin || user.role_ids.includes("administrator")) return "Only an administrator can manage administrators";
  const held = user.role_ids.flatMap((id) => (rolesById.get(id) || { permissions: [] }).permissions);
  const unheld = [...new Set(held)].filter((p) => !auth.can(p)).sort();
  return unheld.length ? `Has permissions you don't: ${unheld.join(", ")}` : null;
}

export function mountUsers(el, ctx = {}) {
  const minLength = () => (ctx.auth && ctx.auth.passwordMinLength) || 12;
  let users = [];
  let roles = [];
  let dead = false;

  el.innerHTML = `<div class="card"><div class="card-head"><h2>Users</h2><span class="spacer"></span>
      <button type="button" class="primary" data-add>Add local user</button></div>
      <div class="tablewrap"><table class="admin-table"><thead><tr>
        <th>User</th><th>Signs in with</th><th>Roles</th><th>Last sign-in</th><th></th></tr></thead>
        <tbody data-rows></tbody></table></div>
      <p class="err" role="alert" data-msg></p></div>`;
  const body = el.querySelector("[data-rows]");
  const msg = el.querySelector("[data-msg]");

  async function load() {
    try {
      [users, roles] = await Promise.all([apiGet("/api/v1/admin/users"), apiGet("/api/v1/admin/roles")]);
    } catch (e) {
      msg.textContent = e.message;
      return;
    }
    if (!dead) draw();
  }

  function draw() {
    const names = new Map(roles.map((r) => [r.id, r.name]));
    const byId = new Map(roles.map((r) => [r.id, r]));
    body.innerHTML = users
      .map((u) => {
        const pills = u.role_ids.map((id) => `<span class="pill">${esc(names.get(id) || id)}</span>`).join(" ");
        const lock = isOwnRow(u, ctx.auth) ? null : userLock(u, byId, ctx.auth);
        const off = lock ? ` disabled title="${esc(lock)}"` : "";
        const action = u.builtin
          ? `<span class="role-tag">built-in</span> <button type="button" class="small" data-pw="${u.id}"${off}>Change password</button>`
          : `${u.enabled ? "" : '<span class="chip bad">Disabled</span> '}<button type="button" class="small" data-edit="${u.id}"${off}>Edit</button>`;
        return `<tr><td><b>${esc(u.display_name || u.username)}</b><div class="sub">${esc(u.username)}</div></td>
          <td>${u.provider === "local" ? "NetView account" : esc(u.provider)}</td>
          <td>${pills}</td><td>${esc(fmtAgo(u.last_sign_in_ms))}</td><td class="act">${action}</td></tr>`;
      })
      .join("");
  }

  el.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add]");
    const edit = e.target.closest("[data-edit]");
    const pw = e.target.closest("[data-pw]");
    if (add) addDialog(add);
    else if (edit) editDialog(users.find((u) => u.id === Number(edit.dataset.edit)), edit);
    else if (pw) changePassword(users.find((u) => u.id === Number(pw.dataset.pw)), pw);
  });

  function addDialog(returnFocus) {
    openAdminDialog({
      title: "Add local user",
      returnFocus,
      body: (pane) => {
        pane.innerHTML = `<form data-form autocomplete="off">
          <label for="nu-name">Username</label><input id="nu-name" type="text" required>
          <label for="nu-display">Display name</label><input id="nu-display" type="text">
          <label for="nu-pw">Initial password</label><input id="nu-pw" type="password" autocomplete="new-password" required>
          <ul class="pw-checks" data-checks aria-live="polite"></ul>
          <p class="note">They must choose a new password at first sign-in.</p>
          <div class="lbl">Roles</div>${roleBoxes(roles, new Set(["default"]))}
          <p class="err" role="alert" data-msg></p></form>`;
      },
      foot: (foot, dlg) => {
        foot.innerHTML = `<button type="button" data-cancel>Cancel</button><button type="button" class="primary" data-ok disabled>Add user</button>`;
        const m = dlg.querySelector("[data-msg]");
        const ok = foot.querySelector("[data-ok]");
        wirePasswordChecks({
          root: dlg,
          list: dlg.querySelector("[data-checks]"),
          button: ok,
          read: () => ({
            password: dlg.querySelector("#nu-pw").value,
            username: dlg.querySelector("#nu-name").value,
            minLength: minLength(),
          }),
          ready: () => dlg.querySelector("#nu-name").value.trim() !== "",
        });
        const submit = async () => {
          if (ok.disabled) return;
          m.textContent = "";
          try {
            await apiSend("POST", "/api/v1/admin/users", {
              username: dlg.querySelector("#nu-name").value,
              display_name: dlg.querySelector("#nu-display").value,
              password: dlg.querySelector("#nu-pw").value,
              role_ids: pickedRoles(dlg),
            });
            dlg.close();
            toast("User added");
            await load();
          } catch (err) {
            showError(m, err);
          }
        };
        foot.querySelector("[data-cancel]").addEventListener("click", () => dlg.close());
        foot.querySelector("[data-ok]").addEventListener("click", submit);
        dlg.querySelector("[data-form]").addEventListener("submit", (ev) => {
          ev.preventDefault();
          submit();
        });
      },
    });
  }

  function editDialog(user, returnFocus) {
    if (!user) return;
    openAdminDialog({
      title: `Edit ${user.username}`,
      returnFocus,
      body: (pane) => {
        pane.innerHTML = `<form data-form autocomplete="off">
          <label for="eu-display">Display name</label><input id="eu-display" type="text" value="${esc(user.display_name)}">
          <div class="lbl">Roles</div>${roleBoxes(roles, new Set(user.role_ids))}
          <label class="perm-row"><input type="checkbox" id="eu-enabled"${user.enabled ? " checked" : ""}>
            <span class="perm-label">Account enabled</span></label>
          ${
            user.provider === "local" && !isOwnRow(user, ctx.auth)
              ? `<label for="eu-pw">Reset password</label>
                 <input id="eu-pw" type="password" autocomplete="new-password" placeholder="Leave empty to keep the current one">
                 <ul class="pw-checks" data-checks aria-live="polite" hidden></ul>
                 <p class="note">Saving with a new password ends their sessions; they must choose their own at next sign-in.</p>`
              : ""
          }
          <p class="err" role="alert" data-msg></p>
          <div data-confirm hidden class="confirm"><p>Delete <b>${esc(user.username)}</b>? This can't be undone.</p>
            <button type="button" class="danger" data-really>Delete ${esc(user.username)}</button>
            <button type="button" data-nope>Keep</button></div></form>`;
      },
      foot: (foot, dlg) => {
        foot.innerHTML = `<button type="button" class="danger" data-delete>Delete</button><span class="spacer"></span>
          <button type="button" data-cancel>Cancel</button><button type="button" class="primary" data-ok>Save</button>`;
        const m = dlg.querySelector("[data-msg]");
        const confirmBox = dlg.querySelector("[data-confirm]");
        const url = `/api/v1/admin/users/${user.id}`;
        const attempt = async (fn, done) => {
          m.textContent = "";
          try {
            await fn();
            dlg.close();
            toast(done);
            await load();
          } catch (err) {
            showError(m, err);
          }
        };
        foot.querySelector("[data-cancel]").addEventListener("click", () => dlg.close());
        const ok = foot.querySelector("[data-ok]");
        const pw = dlg.querySelector("#eu-pw");
        if (pw) {
          wirePasswordChecks({
            root: dlg,
            list: dlg.querySelector("[data-checks]"),
            button: ok,
            optional: true,
            read: () => ({ password: pw.value, username: user.username, minLength: minLength() }),
          });
        }
        ok.addEventListener("click", () => {
          if (ok.disabled) return;
          const password = pw ? pw.value : "";
          attempt(async () => {
            await apiSend("PATCH", url, {
              display_name: dlg.querySelector("#eu-display").value,
              role_ids: pickedRoles(dlg),
              enabled: dlg.querySelector("#eu-enabled").checked,
            });
            if (password) await apiSend("POST", `${url}/password`, { password });
          }, password ? "User saved and password reset" : "User saved");
        });
        foot.querySelector("[data-delete]").addEventListener("click", () => (confirmBox.hidden = false));
        dlg.querySelector("[data-nope]").addEventListener("click", () => (confirmBox.hidden = true));
        dlg.querySelector("[data-really]").addEventListener("click", () =>
          attempt(() => apiSend("DELETE", url), "User deleted"),
        );
      },
    });
  }

  /** Your own password goes through the self-service dialog, which keeps your session; others get an admin reset. */
  function changePassword(user, returnFocus) {
    if (!user) return;
    if (isOwnRow(user, ctx.auth)) openPasswordDialog();
    else passwordDialog(user, returnFocus);
  }

  function passwordDialog(user, returnFocus) {
    if (!user) return;
    openAdminDialog({
      title: `Change password for ${user.username}`,
      returnFocus,
      body: (pane) => {
        pane.innerHTML = `<form data-form autocomplete="off"><label for="pu-pw">New password</label>
          <input id="pu-pw" type="password" autocomplete="new-password" required>
          <ul class="pw-checks" data-checks aria-live="polite"></ul>
          <p class="err" role="alert" data-msg></p></form>`;
      },
      foot: (foot, dlg) => {
        foot.innerHTML = `<button type="button" data-cancel>Cancel</button><button type="button" class="primary" data-ok disabled>Change password</button>`;
        const m = dlg.querySelector("[data-msg]");
        const ok = foot.querySelector("[data-ok]");
        wirePasswordChecks({
          root: dlg,
          list: dlg.querySelector("[data-checks]"),
          button: ok,
          read: () => ({ password: dlg.querySelector("#pu-pw").value, username: user.username, minLength: minLength() }),
        });
        const submit = async () => {
          if (ok.disabled) return;
          m.textContent = "";
          try {
            await apiSend("POST", `/api/v1/admin/users/${user.id}/password`, {
              password: dlg.querySelector("#pu-pw").value,
            });
            dlg.close();
            toast("Password changed");
            await load();
          } catch (err) {
            showError(m, err);
          }
        };
        foot.querySelector("[data-cancel]").addEventListener("click", () => dlg.close());
        foot.querySelector("[data-ok]").addEventListener("click", submit);
        dlg.querySelector("[data-form]").addEventListener("submit", (ev) => {
          ev.preventDefault();
          submit();
        });
      },
    });
  }

  load();
  return { destroy: () => (dead = true) };
}
