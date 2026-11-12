// The Admin page: a sidebar of sections, each shown only to someone who may use it.
import { esc } from "../../util.js";
import { mountUsers } from "./users.js";
import { mountRoles } from "./roles.js";
import { mountGeneral } from "./general.js";

const SECTIONS = [
  { id: "users", label: "Users", need: "core.users", mount: mountUsers },
  { id: "roles", label: "Roles", need: "core.users", mount: mountRoles },
  { id: "general", label: "General", need: "core.system", mount: mountGeneral },
];

/** The sections `auth` may open, in sidebar order: [{id, label}]. */
export function adminSections(auth) {
  return SECTIONS.filter((s) => auth.can(s.need)).map(({ id, label }) => ({ id, label }));
}

export function mountAdmin(el, ctx) {
  const auth = ctx.auth;
  const sections = adminSections(auth);
  let active = sections.length ? sections[0].id : null;
  let handle = null;

  el.innerHTML = `<div class="admin">
    <nav class="admin-side" aria-label="Admin sections"></nav>
    <section class="admin-main"></section></div>`;
  const side = el.querySelector(".admin-side");
  const main = el.querySelector(".admin-main");

  const draw = () => {
    side.innerHTML = sections
      .map(
        (s) =>
          `<button type="button" data-section="${esc(s.id)}" class="${s.id === active ? "on" : ""}"${s.id === active ? ' aria-current="page"' : ""}>${esc(s.label)}</button>`,
      )
      .join("");
    if (handle && handle.destroy) handle.destroy();
    main.innerHTML = "";
    const section = SECTIONS.find((s) => s.id === active);
    handle = section ? section.mount(main, { auth }) : null;
    if (!section) main.innerHTML = `<div class="card"><p class="note">You don't have access to anything here.</p></div>`;
  };
  side.addEventListener("click", (e) => {
    const b = e.target.closest("[data-section]");
    if (!b || b.dataset.section === active) return;
    active = b.dataset.section;
    draw();
  });
  draw();
  return { destroy: () => handle && handle.destroy && handle.destroy() };
}
