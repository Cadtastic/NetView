// Admin -> Users: the user table, "Add local user", and the edit dialog.
import { apiGet, apiSend } from "../../api.js";
import { esc, fmtAgo } from "../../util.js";
import { toast } from "../../toast.js";
import { openAdminDialog, showError } from "./dialog.js";

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

export function mountUsers(el) {
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
    body.innerHTML = users
      .map((u) => {
        const pills = u.role_ids.map((id) => `<span class="pill">${esc(names.get(id) || id)}</span>`).join(" ");
        const action = u.builtin
          ? `<span class="role-tag">built-in</span> <button type="button" class="small" data-pw="${u.id}">Change password</button>`
          : `${u.enabled ? "" : '<span class="chip bad">Disabled</span> '}<button type="button" class="small" data-edit="${u.id}">Edit</button>`;
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
    else if (pw) passwordDialog(users.find((u) => u.id === Number(pw.dataset.pw)), pw);
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
          <p class="note">They must choose a new password at first sign-in.</p>
          <div class="lbl">Roles</div>${roleBoxes(roles, new Set(["default"]))}
          <p class="err" role="alert" data-msg></p></form>`;
      },
      foot: (foot, dlg) => {
        foot.innerHTML = `<button type="button" data-cancel>Cancel</button><button type="button" class="primary" data-ok>Add user</button>`;
        const m = dlg.querySelector("[data-msg]");
        const submit = async () => {
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
            user.provider === "local"
              ? `<label for="eu-pw">Reset password</label>
                 <div class="inline"><input id="eu-pw" type="password" autocomplete="new-password" placeholder="New password">
                 <button type="button" data-reset>Reset</button></div>
                 <p class="note">They must choose a new password at next sign-in.</p>`
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
        foot.querySelector("[data-ok]").addEventListener("click", () =>
          attempt(
            () =>
              apiSend("PATCH", url, {
                display_name: dlg.querySelector("#eu-display").value,
                role_ids: pickedRoles(dlg),
                enabled: dlg.querySelector("#eu-enabled").checked,
              }),
            "User saved",
          ),
        );
        foot.querySelector("[data-delete]").addEventListener("click", () => (confirmBox.hidden = false));
        dlg.querySelector("[data-nope]").addEventListener("click", () => (confirmBox.hidden = true));
        dlg.querySelector("[data-really]").addEventListener("click", () =>
          attempt(() => apiSend("DELETE", url), "User deleted"),
        );
        const reset = dlg.querySelector("[data-reset]");
        if (reset) {
          reset.addEventListener("click", async () => {
            m.textContent = "";
            try {
              await apiSend("POST", `${url}/password`, { password: dlg.querySelector("#eu-pw").value });
              dlg.querySelector("#eu-pw").value = "";
              toast("Password reset");
            } catch (err) {
              showError(m, err);
            }
          });
        }
      },
    });
  }

  function passwordDialog(user, returnFocus) {
    if (!user) return;
    openAdminDialog({
      title: `Change password for ${user.username}`,
      returnFocus,
      body: (pane) => {
        pane.innerHTML = `<form data-form autocomplete="off"><label for="pu-pw">New password</label>
          <input id="pu-pw" type="password" autocomplete="new-password" required>
          <p class="err" role="alert" data-msg></p></form>`;
      },
      foot: (foot, dlg) => {
        foot.innerHTML = `<button type="button" data-cancel>Cancel</button><button type="button" class="primary" data-ok>Change password</button>`;
        const m = dlg.querySelector("[data-msg]");
        const submit = async () => {
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
