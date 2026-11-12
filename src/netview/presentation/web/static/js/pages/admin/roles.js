// Admin -> Roles: the roles list and a permission editor grouped by owner (NetView core first).
import { apiGet, apiSend } from "../../api.js";
import { esc } from "../../util.js";
import { toast } from "../../toast.js";
import { openAdminDialog, showError } from "./dialog.js";

const ADMIN_ROLE = "administrator";

/**
 * The checkbox rows for `role` over the catalog `groups` (from /admin/permissions).
 * -> {groups: [{title, off, rows: [{id, label, description, dangerous, checked, disabled, title}]}]}
 * Administrator: every box checked and disabled. A locked permission: disabled, unchecked, its reason as the title.
 */
export function roleEditorModel(role, groups) {
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

export function mountRoles(el) {
  let roles = [];
  let groups = [];
  let selected = null;
  let dead = false;

  el.innerHTML = `<div class="roles"><div class="card roles-list"></div><div class="card roles-edit"></div></div>`;
  const listEl = el.querySelector(".roles-list");
  const editEl = el.querySelector(".roles-edit");

  async function load(select) {
    try {
      [roles, groups] = await Promise.all([apiGet("/api/v1/admin/roles"), apiGet("/api/v1/admin/permissions")]);
    } catch (e) {
      listEl.innerHTML = `<p class="err">${esc(e.message)}</p>`;
      return;
    }
    if (dead) return;
    selected = (roles.find((r) => r.id === (select || selected)) || roles[0] || {}).id || null;
    drawList();
    drawEditor();
  }

  function drawList() {
    listEl.innerHTML = `<h2>Roles</h2><ul class="role-items">${roles
      .map(
        (r) => `<li><button type="button" data-role="${esc(r.id)}" class="${r.id === selected ? "on" : ""}">
          <span>${esc(r.name)}</span>
          <span class="role-tag">${r.builtin ? "built-in · " : ""}${r.user_count} ${r.user_count === 1 ? "user" : "users"}</span></button></li>`,
      )
      .join("")}</ul><button type="button" data-new>+ New role</button>`;
  }

  function drawEditor() {
    const role = roles.find((r) => r.id === selected);
    if (!role) {
      editEl.innerHTML = `<p class="note">Pick a role.</p>`;
      return;
    }
    const model = roleEditorModel(role, groups);
    editEl.innerHTML = `<div class="card-head"><h2>${esc(role.name)}</h2>
        <span class="sub">${role.id === ADMIN_ROLE ? "Administrator always has every permission." : "Tick what this role allows."}</span></div>
      <div class="perm-groups">${editorHtml(model)}</div>
      <p class="err" role="alert" data-msg></p>
      <div class="editor-foot">
        ${role.id === ADMIN_ROLE ? "" : '<button type="button" class="primary" data-save>Save</button>'}
        ${role.builtin ? "" : '<button type="button" data-rename>Rename</button><button type="button" class="danger" data-delete>Delete</button>'}
      </div>`;
  }

  listEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-role]");
    if (b) {
      selected = b.dataset.role;
      drawList();
      drawEditor();
      return;
    }
    const add = e.target.closest("[data-new]");
    if (add) {
      nameDialog(
        "New role",
        "",
        async (name) => {
          const made = await apiSend("POST", "/api/v1/admin/roles", { name });
          toast("Role created");
          await load(made.id);
        },
        add,
      );
    }
  });

  editEl.addEventListener("click", async (e) => {
    const role = roles.find((r) => r.id === selected);
    if (!role) return;
    const msg = editEl.querySelector("[data-msg]");
    const rename = e.target.closest("[data-rename]");
    const del = e.target.closest("[data-delete]");
    if (e.target.closest("[data-save]")) {
      msg.textContent = "";
      const permissions = [...editEl.querySelectorAll("[data-perm]")]
        .filter((c) => c.checked && !c.disabled)
        .map((c) => c.dataset.perm);
      try {
        await apiSend("PATCH", `/api/v1/admin/roles/${encodeURIComponent(role.id)}`, { permissions });
        toast("Role saved");
        await load(role.id);
      } catch (err) {
        showError(msg, err);
      }
    } else if (rename) {
      nameDialog(
        "Rename role",
        role.name,
        async (name) => {
          await apiSend("PATCH", `/api/v1/admin/roles/${encodeURIComponent(role.id)}`, { name });
          toast("Role renamed");
          await load(role.id);
        },
        rename,
      );
    } else if (del) {
      confirmDelete(role, del);
    }
  });

  function nameDialog(title, value, onSubmit, returnFocus) {
    openAdminDialog({
      title,
      returnFocus,
      body: (pane) => {
        pane.innerHTML = `<form data-form><label for="role-name">Role name</label>
          <input id="role-name" type="text" maxlength="64" value="${esc(value)}" required>
          <p class="err" role="alert" data-msg></p></form>`;
      },
      foot: (foot, dlg) => {
        foot.innerHTML = `<button type="button" data-cancel>Cancel</button><button type="button" class="primary" data-ok>Save</button>`;
        const input = dlg.querySelector("#role-name");
        const msg = dlg.querySelector("[data-msg]");
        const submit = async () => {
          msg.textContent = "";
          try {
            await onSubmit(input.value.trim());
            dlg.close();
          } catch (err) {
            showError(msg, err);
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

  function confirmDelete(role, returnFocus) {
    openAdminDialog({
      title: "Delete role",
      returnFocus,
      body: (pane) => {
        pane.innerHTML = `<p>Delete the role <b>${esc(role.name)}</b>? ${role.user_count ? `${role.user_count} user(s) will lose it.` : ""}</p>
          <p class="err" role="alert" data-msg></p>`;
      },
      foot: (foot, dlg) => {
        foot.innerHTML = `<button type="button" data-cancel>Cancel</button><button type="button" class="danger" data-ok>Delete ${esc(role.name)}</button>`;
        foot.querySelector("[data-cancel]").addEventListener("click", () => dlg.close());
        foot.querySelector("[data-ok]").addEventListener("click", async () => {
          try {
            await apiSend("DELETE", `/api/v1/admin/roles/${encodeURIComponent(role.id)}`);
            dlg.close();
            toast("Role deleted");
            selected = null;
            await load();
          } catch (err) {
            showError(dlg.querySelector("[data-msg]"), err);
          }
        });
      },
    });
  }

  load();
  return { destroy: () => (dead = true) };
}
