// The Admin page on the blade layout: a side menu of sections (each shown only to someone who may use it),
// a page with a command bar, and child blades for editing.
import { createBlade } from "../../blade.js";
import { adjustments, users as usersIcon, idBadge, layoutDashboard } from "../../icons.js";
import { mountUsers } from "./users.js";
import { mountRoles } from "./roles.js";
import { mountGeneral } from "./general.js";
import { mountDefaultDashboard } from "./default-dashboard.js";

const SECTIONS = [
  { id: "general", label: "General", need: "core.system", icon: adjustments, mount: mountGeneral },
  { id: "users", label: "Users", group: "Identity", need: "core.users", icon: usersIcon, mount: mountUsers },
  { id: "roles", label: "Roles", group: "Identity", need: "core.users", icon: idBadge, mount: mountRoles },
  { id: "dashboard", label: "Default dashboard", group: "Dashboard", need: "core.system", icon: layoutDashboard, mount: mountDefaultDashboard },
];

/** The sections `auth` may open, in menu order: [{id, label, group?, icon}]. */
export function adminSections(auth) {
  return SECTIONS.filter((s) => auth.can(s.need)).map(({ id, label, group, icon }) => (group ? { id, label, group, icon } : { id, label, icon }));
}

/** The section a `/admin/<id>` path names, or the first section when it names none you may open. */
export function sectionFromPath(path, sections) {
  const id = String(path ?? "").split("/")[2] || "";
  const hit = sections.find((s) => s.id === id);
  return hit ? hit.id : sections.length ? sections[0].id : null;
}

/** The blade menu for `sections`: ungrouped items first, then one entry per group, in order. */
function bladeMenu(sections) {
  const menu = [];
  for (const s of sections) {
    const group = s.group || undefined;
    const last = menu[menu.length - 1];
    const item = { id: s.id, label: s.label, icon: s.icon };
    if (last && last.group === group) last.items.push(item);
    else menu.push({ group, items: [item] });
  }
  return menu;
}

export function mountAdmin(el, ctx) {
  const auth = ctx.auth;
  const sections = adminSections(auth);
  if (!sections.length) {
    el.innerHTML = `<div class="card"><p class="note">You don't have access to anything here.</p></div>`;
    return { destroy() {} };
  }
  let handle = null;
  const stop = () => {
    if (handle && handle.destroy) handle.destroy();
    handle = null;
  };

  const blade = createBlade(el, {
    crumbRoot: "Admin",
    menu: bladeMenu(sections),
    initial: sectionFromPath(ctx.path, sections),
    storageKey: "netview.admin.menu",
    onSelect: (id, page, api, { push }) => {
      stop();
      if (push) history.pushState(null, "", "#/admin/" + id);
      const section = SECTIONS.find((s) => s.id === id);
      handle = section ? section.mount(page, { auth, blade: api }) : null;
    },
  });
  return {
    destroy() {
      stop();
      blade.destroy();
    },
  };
}
