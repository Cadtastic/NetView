// Admin -> Roles: the roles table; a row opens the permission editor (grouped by owner, NetView core first) in a child blade.
import { apiGet, apiSend } from "../../api.js";
import { esc } from "../../util.js";
import { toast } from "../../toast.js";
import { showError } from "./errors.js";
import { pageHeadHtml } from "../../blade.js";
import { plus } from "../../icons.js";

const ADMIN_ROLE = "administrator";

/**
 * The checkbox rows for `role` over the catalog `groups` (from /admin/permissions).
 * -> {groups: [{title, off, rows: [{id, label, description, dangerous, checked, disabled, title}]}]}
 * Administrator: every box checked and disabled. A locked permission: disabled, unchecked, its reason as the title.
 */
export function roleEditorModel(role, groups, auth = null) {
  const limited = !!auth && !auth.isAdmin;
  const unheld = limited ? (role.permissions || []).filter((p) => !auth.can(p)).sort() : [];
  const lock = !limited
    ? null
    : role.id === ADMIN_ROLE
      ? "Only an administrator can manage administrators"
      : unheld.length
        ? `Has permissions you don't: ${unheld.join(", ")}`
        : null;
  const model = roleEditorModelFor(role, groups);
  model.lock = lock;
  if (limited) {
    for (const row of model.groups.flatMap((g) => g.rows)) {
      if (lock) {
        row.disabled = true;
        row.title = row.title || lock;
      } else if (!row.disabled && !auth.can(row.id)) {
        row.disabled = true;
        row.title = "You don't have this permission, so you can't grant it";
      }
    }
  }
  return model;
}

function roleEditorModelFor(role, groups) {
  const isAdmin = role.id === ADMIN_ROLE;
  const held = new Set(role.permissions || []);
  const known = new Set(groups.flatMap((g) => g.permissions.map((p) => p.id)));
  // Permissions still on the role from a plugin that is no longer installed: shown so they can be revoked.
  const leftover = isAdmin ? [] : [...held].filter((id) => !known.has(id)).sort();
  const extra = leftover.length
    ? [
        {
          title: "Uninstalled plugins",
          off: true,
          rows: leftover.map((id) => ({
            id,
            label: id,
            description: "From a plugin that is no longer installed. Untick to remove it from this role.",
            dangerous: false,
            checked: true,
            disabled: false,
            title: "",
          })),
        },
      ]
    : [];
  return {
    groups: [...groups.map((g) => ({
      title: g.off ? `${g.title} (off)` : g.title,
      off: !!g.off,
      rows: g.permissions.map((p) => ({
        id: p.id,
        label: p.label,
        description: p.description || "",
        dangerous: !!p.dangerous,
        checked: isAdmin || (p.locked ? false : held.has(p.id)),
        disabled: isAdmin || !!p.locked,
        title: p.locked || "",
      })),
    })), ...extra],
  };
}

/** The permission ids ticked in `model`, locked rows excluded. */
export function permissionsFromModel(model) {
  return model.groups
    .flatMap((g) => g.rows)
    .filter((r) => r.checked && !r.disabled)
    .map((r) => r.id);
}

function editorHtml(model) {
  return model.groups
    .map(
      (g) => `<fieldset class="perm-group${g.off ? " off" : ""}"><legend>${esc(g.title)}</legend>
        ${g.rows
          .map(
            (r) => `<label class="perm-row" title="${esc(r.title)}">
              <input type="checkbox" data-perm="${esc(r.id)}"${r.checked ? " checked" : ""}${r.disabled ? " disabled" : ""}>
              <span><span class="perm-label">${esc(r.label)}</span>${r.dangerous ? ' <span class="chip warn" title="Powerful permission">careful</span>' : ""}
              ${r.description ? `<span class="perm-desc">${esc(r.description)}</span>` : ""}</span></label>`,
          )
          .join("")}</fieldset>`,
    )
    .join("");
}

const SUB = "What each role allows. A user holds one or more roles.";
const COMMANDS = [{ id: "new", label: "New role", icon: plus }];

export function mountRoles(el, { auth, blade }) {
  let roles = [];
  let groups = [];
  let dead = false;

  el.innerHTML = `${pageHeadHtml({ title: "Roles", sub: SUB, commands: COMMANDS })}
    <div class="tablewrap"><table class="admin-table"><thead><tr><th>Role</th><th>Users</th></tr></thead>
      <tbody data-rows></tbody></table></div>
    <p class="err" role="alert" data-msg></p>`;
  const body = el.querySelector("[data-rows]");
  const pageMsg = el.querySelector("[data-msg]");

  async function load() {
    try {
      [roles, groups] = await Promise.all([apiGet("/api/v1/admin/roles"), apiGet("/api/v1/admin/permissions")]);
    } catch (e) {
      pageMsg.textContent = e.message;
      return;
    }
    if (!dead) draw();
  }

  function draw() {
    body.innerHTML = roles
      .map(
        (r) => `<tr class="row-open" data-id="${esc(r.id)}"><td><button type="button" class="linkish" data-open><b>${esc(r.name)}</b></button>
          ${r.builtin ? ' <span class="role-tag">built-in</span>' : ""}</td>
          <td>${r.user_count} ${r.user_count === 1 ? "user" : "users"}</td></tr>`,
      )
      .join("");
  }

  el.addEventListener("click", (e) => {
    const cmd = e.target.closest("[data-cmd]");
    if (cmd) {
      if (cmd.dataset.cmd === "new") {
        nameBlade(
          "New role",
          "",
          async (name) => {
            await apiSend("POST", "/api/v1/admin/roles", { name });
            toast("Role created");
            await load();
          },
          cmd,
        );
      }
      return;
    }
    const row = e.target.closest("tr[data-id]");
    if (!row) return;
    editorBlade(roles.find((r) => r.id === row.dataset.id), row.querySelector("[data-open]"));
  });

  function editorBlade(role, opener) {
    if (!role) return;
    const model = roleEditorModel(role, groups, auth);
    const off = model.lock ? ` disabled title="${esc(model.lock)}"` : "";
    let pane = null;
    blade.openChild({
      title: role.name,
      opener,
      body: (p) => {
        pane = p;
        p.innerHTML = `<p class="sub">${role.id === ADMIN_ROLE ? "Administrator always has every permission." : "Tick what this role allows."}</p>
          <div class="perm-groups">${editorHtml(model)}</div>
          ${model.lock && role.id !== ADMIN_ROLE ? `<p class="note">${esc(model.lock)}, so you can't change this role.</p>` : ""}
          <p class="err" role="alert" data-msg></p>
          <div data-confirm hidden class="confirm"><p>Delete the role <b>${esc(role.name)}</b>? ${role.user_count ? `${role.user_count} user(s) will lose it.` : ""}</p>
            <button type="button" class="danger" data-really>Delete ${esc(role.name)}</button>
            <button type="button" data-nope>Keep</button></div>`;
      },
      foot: (foot, close) => {
        const msg = pane.querySelector("[data-msg]");
        const confirmBox = pane.querySelector("[data-confirm]");
        foot.innerHTML = `${role.id === ADMIN_ROLE ? "" : `<button type="button" class="primary" data-save${off}>Save</button>`}
          <button type="button" data-cancel>Cancel</button>
          ${role.builtin ? "" : `<button type="button" data-rename${off}>Rename</button><button type="button" class="danger" data-delete${off}>Delete</button>`}`;
        foot.querySelector("[data-cancel]").addEventListener("click", close);
        foot.querySelector("[data-save]")?.addEventListener("click", async () => {
          msg.textContent = "";
          const permissions = [...pane.querySelectorAll("[data-perm]")].filter((c) => c.checked && !c.disabled).map((c) => c.dataset.perm);
          try {
            await apiSend("PATCH", `/api/v1/admin/roles/${encodeURIComponent(role.id)}`, { permissions });
            close();
            toast("Role saved");
            await load();
          } catch (err) {
            showError(msg, err);
          }
        });
        foot.querySelector("[data-rename]")?.addEventListener("click", () =>
          nameBlade(
            "Rename role",
            role.name,
            async (name) => {
              await apiSend("PATCH", `/api/v1/admin/roles/${encodeURIComponent(role.id)}`, { name });
              toast("Role renamed");
              await load();
            },
            opener,
          ),
        );
        foot.querySelector("[data-delete]")?.addEventListener("click", () => (confirmBox.hidden = false));
        pane.querySelector("[data-nope]").addEventListener("click", () => (confirmBox.hidden = true));
        pane.querySelector("[data-really]").addEventListener("click", async () => {
          try {
            await apiSend("DELETE", `/api/v1/admin/roles/${encodeURIComponent(role.id)}`);
            close();
            toast("Role deleted");
            await load();
          } catch (err) {
            showError(msg, err);
          }
        });
      },
    });
  }

  /** A one-field child blade for a role name; `onSubmit(name)` does the call and may throw. */
  function nameBlade(title, value, onSubmit, opener) {
    let pane = null;
    blade.openChild({
      title,
      opener,
      body: (p) => {
        pane = p;
        p.innerHTML = `<form data-form><label for="role-name">Role name</label>
          <input id="role-name" type="text" maxlength="64" value="${esc(value)}" required>
          <p class="err" role="alert" data-msg></p></form>`;
      },
      foot: (foot, close) => {
        foot.innerHTML = `<button type="button" class="primary" data-ok>Save</button><button type="button" data-cancel>Cancel</button>`;
        const input = pane.querySelector("#role-name");
        const msg = pane.querySelector("[data-msg]");
        const submit = async () => {
          msg.textContent = "";
          try {
            await onSubmit(input.value.trim());
            close();
          } catch (err) {
            showError(msg, err);
          }
        };
        foot.querySelector("[data-cancel]").addEventListener("click", close);
        foot.querySelector("[data-ok]").addEventListener("click", submit);
        pane.querySelector("[data-form]").addEventListener("submit", (ev) => {
          ev.preventDefault();
          submit();
        });
      },
    });
  }

  load();
  return { destroy: () => (dead = true) };
}
