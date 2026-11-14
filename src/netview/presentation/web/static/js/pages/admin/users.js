// Admin -> Users: the user table; "Add local user", edit and password reset open as child blades.
import { apiGet, apiSend } from "../../api.js";
import { esc, fmtAgo } from "../../util.js";
import { toast } from "../../toast.js";
import { showError } from "./errors.js";
import { pageHeadHtml } from "../../blade.js";
import { plus, refresh } from "../../icons.js";
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

const SUB = "People who can sign in to NetView, the roles they hold, and how they sign in.";
const COMMANDS = [
  { id: "add", label: "Add local user", icon: plus },
  { id: "refresh", label: "Refresh", icon: refresh },
];

/** The element password rules listen on: the child blade's body, which is rebuilt on every open so no listener outlives it. */
const childRoot = (pane) => pane;

export function mountUsers(el, { auth, blade }) {
  const minLength = () => (auth && auth.passwordMinLength) || 12;
  let users = [];
  let roles = [];
  let dead = false;

  el.innerHTML = `${pageHeadHtml({ title: "Users", sub: SUB, commands: COMMANDS })}
    <div class="tablewrap"><table class="admin-table"><thead><tr>
      <th>User</th><th>Signs in with</th><th>Roles</th><th>Last sign-in</th></tr></thead>
      <tbody data-rows></tbody></table></div>
    <p class="err" role="alert" data-msg></p>`;
  const body = el.querySelector("[data-rows]");
  const msg = el.querySelector("[data-msg]");

  async function load() {
    msg.textContent = "";
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
        const lock = isOwnRow(u, auth) ? null : userLock(u, byId, auth);
        const off = lock ? ` disabled title="${esc(lock)}"` : "";
        const flag = u.builtin ? ' <span class="role-tag">built-in</span>' : u.enabled ? "" : ' <span class="chip bad">Disabled</span>';
        return `<tr class="${lock ? "" : "row-open"}" data-row="${u.builtin ? "pw" : "edit"}" data-id="${u.id}"><td><button type="button" class="linkish" data-open${off}><b>${esc(u.display_name || u.username)}</b></button>${flag}<div class="sub">${esc(u.username)}</div></td>
          <td>${u.provider === "local" ? "NetView account" : esc(u.provider)}</td>
          <td>${pills}</td><td>${esc(fmtAgo(u.last_sign_in_ms))}</td></tr>`;
      })
      .join("");
  }

  const onClick = (e) => {
    const cmd = e.target.closest("[data-cmd]");
    if (cmd) {
      if (cmd.dataset.cmd === "add") addBlade(cmd);
      else if (cmd.dataset.cmd === "refresh") load();
      return;
    }
    const row = e.target.closest("tr[data-row]");
    if (!row) return;
    const opener = row.querySelector("[data-open]");
    if (opener.disabled) return;
    const user = users.find((u) => u.id === Number(row.dataset.id));
    if (row.dataset.row === "pw") changePassword(user, opener);
    else editBlade(user, opener);
  };
  el.addEventListener("click", onClick);

  function addBlade(opener) {
    let pane = null;
    blade.openChild({
      title: "Add local user",
      opener,
      body: (p) => {
        pane = p;
        p.innerHTML = `<form data-form autocomplete="off">
          <label for="nu-name">Username</label><input id="nu-name" type="text" required>
          <label for="nu-display">Display name</label><input id="nu-display" type="text">
          <label for="nu-pw">Initial password</label><input id="nu-pw" type="password" autocomplete="new-password" required>
          <ul class="pw-checks" data-checks aria-live="polite"></ul>
          <p class="note">They must choose a new password at first sign-in.</p>
          <div class="lbl">Roles</div>${roleBoxes(roles, new Set(["default"]))}
          <p class="err" role="alert" data-msg></p></form>`;
      },
      foot: (foot, close) => {
        foot.innerHTML = `<button type="button" class="primary" data-ok disabled>Add user</button><button type="button" data-cancel>Cancel</button>`;
        const m = pane.querySelector("[data-msg]");
        const ok = foot.querySelector("[data-ok]");
        wirePasswordChecks({
          root: childRoot(pane),
          list: pane.querySelector("[data-checks]"),
          button: ok,
          read: () => ({
            password: pane.querySelector("#nu-pw").value,
            username: pane.querySelector("#nu-name").value,
            minLength: minLength(),
          }),
          ready: () => pane.querySelector("#nu-name").value.trim() !== "",
        });
        const submit = async () => {
          if (ok.disabled) return;
          m.textContent = "";
          try {
            await apiSend("POST", "/api/v1/admin/users", {
              username: pane.querySelector("#nu-name").value,
              display_name: pane.querySelector("#nu-display").value,
              password: pane.querySelector("#nu-pw").value,
              role_ids: pickedRoles(pane),
            });
            close();
            toast("User added");
            await load();
          } catch (err) {
            showError(m, err);
          }
        };
        foot.querySelector("[data-cancel]").addEventListener("click", close);
        ok.addEventListener("click", submit);
        pane.querySelector("[data-form]").addEventListener("submit", (ev) => {
          ev.preventDefault();
          submit();
        });
      },
    });
  }

  function editBlade(user, opener) {
    if (!user) return;
    let pane = null;
    blade.openChild({
      title: `Edit ${user.username}`,
      opener,
      body: (p) => {
        pane = p;
        p.innerHTML = `<form data-form autocomplete="off">
          <label for="eu-display">Display name</label><input id="eu-display" type="text" value="${esc(user.display_name)}">
          <div class="lbl">Roles</div>${roleBoxes(roles, new Set(user.role_ids))}
          <label class="perm-row"><input type="checkbox" id="eu-enabled"${user.enabled ? " checked" : ""}>
            <span class="perm-label">Account enabled</span></label>
          ${
            user.provider === "local" && !isOwnRow(user, auth)
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
      foot: (foot, close) => {
        foot.innerHTML = `<button type="button" class="primary" data-ok>Save</button><button type="button" data-cancel>Cancel</button>
          <button type="button" class="danger" data-delete>Delete</button>`;
        const m = pane.querySelector("[data-msg]");
        const confirmBox = pane.querySelector("[data-confirm]");
        const url = `/api/v1/admin/users/${user.id}`;
        const attempt = async (fn, done) => {
          m.textContent = "";
          try {
            await fn();
            close();
            toast(done);
            await load();
          } catch (err) {
            showError(m, err);
          }
        };
        foot.querySelector("[data-cancel]").addEventListener("click", close);
        const ok = foot.querySelector("[data-ok]");
        const pw = pane.querySelector("#eu-pw");
        if (pw) {
          wirePasswordChecks({
            root: childRoot(pane),
            list: pane.querySelector("[data-checks]"),
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
              display_name: pane.querySelector("#eu-display").value,
              role_ids: pickedRoles(pane),
              enabled: pane.querySelector("#eu-enabled").checked,
            });
            if (password) await apiSend("POST", `${url}/password`, { password });
          }, password ? "User saved and password reset" : "User saved");
        });
        foot.querySelector("[data-delete]").addEventListener("click", () => (confirmBox.hidden = false));
        pane.querySelector("[data-nope]").addEventListener("click", () => (confirmBox.hidden = true));
        pane.querySelector("[data-really]").addEventListener("click", () => attempt(() => apiSend("DELETE", url), "User deleted"));
      },
    });
  }

  /** Your own password goes through the self-service dialog, which keeps your session; others get an admin reset. */
  function changePassword(user, opener) {
    if (!user) return;
    if (isOwnRow(user, auth)) openPasswordDialog();
    else passwordBlade(user, opener);
  }

  function passwordBlade(user, opener) {
    let pane = null;
    blade.openChild({
      title: `Change password for ${user.username}`,
      opener,
      body: (p) => {
        pane = p;
        p.innerHTML = `<form data-form autocomplete="off"><label for="pu-pw">New password</label>
          <input id="pu-pw" type="password" autocomplete="new-password" required>
          <ul class="pw-checks" data-checks aria-live="polite"></ul>
          <p class="err" role="alert" data-msg></p></form>`;
      },
      foot: (foot, close) => {
        foot.innerHTML = `<button type="button" class="primary" data-ok disabled>Change password</button><button type="button" data-cancel>Cancel</button>`;
        const m = pane.querySelector("[data-msg]");
        const ok = foot.querySelector("[data-ok]");
        wirePasswordChecks({
          root: childRoot(pane),
          list: pane.querySelector("[data-checks]"),
          button: ok,
          read: () => ({ password: pane.querySelector("#pu-pw").value, username: user.username, minLength: minLength() }),
        });
        const submit = async () => {
          if (ok.disabled) return;
          m.textContent = "";
          try {
            await apiSend("POST", `/api/v1/admin/users/${user.id}/password`, {
              password: pane.querySelector("#pu-pw").value,
            });
            close();
            toast("Password changed");
            await load();
          } catch (err) {
            showError(m, err);
          }
        };
        foot.querySelector("[data-cancel]").addEventListener("click", close);
        ok.addEventListener("click", submit);
        pane.querySelector("[data-form]").addEventListener("submit", (ev) => {
          ev.preventDefault();
          submit();
        });
      },
    });
  }

  load();
  return {
    destroy() {
      dead = true;
      el.removeEventListener("click", onClick); // the page element outlives the section
    },
  };
}
