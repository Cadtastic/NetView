import { test } from "node:test";
import assert from "node:assert/strict";
import { adminSections } from "../../src/netview/presentation/web/static/js/pages/admin/admin.js";
import { roleEditorModel, permissionsFromModel } from "../../src/netview/presentation/web/static/js/pages/admin/roles.js";
import { generalFormModel, secondsFromForm } from "../../src/netview/presentation/web/static/js/pages/admin/general.js";
import { createAuth } from "../../src/netview/presentation/web/static/js/auth.js";

const GROUPS = [
  {
    owner: "core",
    title: "NetView",
    off: false,
    permissions: [
      { id: "core.view", label: "View devices and dashboard", description: "", dangerous: false, locked: null },
      { id: "core.install", label: "Install plugins", description: "", dangerous: false, locked: "Administrator only: installing runs downloaded code" },
    ],
  },
  {
    owner: "gsm7248",
    title: "GSM7248",
    off: true,
    permissions: [{ id: "gsm7248.console", label: "Open console", description: "full CLI access", dangerous: true, locked: null }],
  },
];
const role = (o = {}) => ({ id: "helpdesk", name: "Helpdesk", builtin: false, permissions: ["core.view"], user_count: 0, ...o });
const rows = (model) => model.groups.flatMap((g) => g.rows);

test("roleEditorModel locks every row for Administrator and checks them all", () => {
  const m = roleEditorModel(role({ id: "administrator", builtin: true, permissions: [] }), GROUPS);
  assert.ok(rows(m).every((r) => r.disabled && r.checked));
});

test("roleEditorModel disables locked rows with the lock reason as their title", () => {
  const m = roleEditorModel(role(), GROUPS);
  const install = rows(m).find((r) => r.id === "core.install");
  assert.equal(install.disabled, true);
  assert.equal(install.checked, false);
  assert.match(install.title, /installing runs downloaded code/);
  const view = rows(m).find((r) => r.id === "core.view");
  assert.equal(view.disabled, false);
  assert.equal(view.checked, true);
});

test("roleEditorModel marks off groups and keeps core first", () => {
  const m = roleEditorModel(role(), GROUPS);
  assert.equal(m.groups[0].off, false);
  assert.equal(m.groups[0].title, "NetView");
  assert.equal(m.groups[1].off, true);
  assert.equal(m.groups[1].title, "GSM7248 (off)");
  assert.equal(rows(m).find((r) => r.id === "gsm7248.console").dangerous, true);
});

test("permissionsFromModel returns the checked, unlocked ids", () => {
  const m = roleEditorModel(role({ permissions: ["core.view", "gsm7248.console"] }), GROUPS);
  assert.deepEqual(permissionsFromModel(m).sort(), ["core.view", "gsm7248.console"]);
});

test("generalFormModel converts seconds to hours, days and minutes", () => {
  const form = generalFormModel({
    password_min_length: 12, session_idle_s: 28800, session_max_s: 604800,
    lockout_failures: 5, lockout_window_s: 900, lockout_s: 900,
  });
  const by = Object.fromEntries(form.map((r) => [r.key, r]));
  assert.equal(by.session_idle_s.value, 8);
  assert.equal(by.session_max_s.value, 7);
  assert.equal(by.lockout_window_s.value, 15);
  assert.equal(by.password_min_length.value, 12);
  assert.equal(by.session_idle_s.label, "Session idle timeout (hours)");
  assert.equal(by.session_idle_s.default, 8);
  assert.equal(form.length, 6);
});

test("secondsFromForm round-trips", () => {
  const policy = {
    password_min_length: 12, session_idle_s: 28800, session_max_s: 604800,
    lockout_failures: 5, lockout_window_s: 900, lockout_s: 900,
  };
  assert.deepEqual(secondsFromForm(generalFormModel(policy)), policy);
});

test("adminSections for a core.users-only user leaves out General", () => {
  const auth = createAuth({ username: "u", permissions: ["core.users"] });
  assert.deepEqual(adminSections(auth).map((s) => s.id), ["users", "roles"]);
});

test("adminSections for core.system only shows General; admin sees all", () => {
  assert.deepEqual(adminSections(createAuth({ permissions: ["core.system"] })).map((s) => s.id), ["general"]);
  assert.deepEqual(adminSections(createAuth({ is_admin: true })).map((s) => s.id), ["users", "roles", "general"]);
});

import { isOwnRow } from "../../src/netview/presentation/web/static/js/pages/admin/users.js";

test("your own row uses the self-service password change, not an admin reset", () => {
  const auth = createAuth({ username: "admin", display_name: "A", provider: "local", permissions: [], is_admin: true });
  assert.equal(isOwnRow({ username: "admin" }, auth), true);
  assert.equal(isOwnRow({ username: "bob" }, auth), false);
  assert.equal(isOwnRow({ username: "bob" }, null), false);
});

test("roleEditorModel shows a role's leftover permissions from uninstalled plugins so they can be revoked", () => {
  const m = roleEditorModel(role({ permissions: ["core.view", "gone.use"] }), GROUPS);
  const last = m.groups[m.groups.length - 1];
  assert.equal(last.title, "Uninstalled plugins");
  assert.deepEqual(last.rows.map((r) => [r.id, r.checked, r.disabled]), [["gone.use", true, false]]);
  assert.ok(permissionsFromModel(m).includes("gone.use"));
  last.rows[0].checked = false;
  assert.ok(!permissionsFromModel(m).includes("gone.use"));
});

test("roleEditorModel adds no Uninstalled group when nothing is left over", () => {
  const m = roleEditorModel(role(), GROUPS);
  assert.ok(m.groups.every((g) => g.title !== "Uninstalled plugins"));
});
