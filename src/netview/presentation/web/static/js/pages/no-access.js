// Shown to a signed-in user who holds no permission at all.

export const NO_ACCESS_TEXT = "You don't have access to anything yet. Ask a NetView admin to give you a role.";

/** True when `me` (the /auth/me body) grants nothing: no permissions and not an administrator. */
export function hasNoAccess(me) {
  return !!me && !me.is_admin && (me.permissions || []).length === 0;
}

export function mountNoAccess(el) {
  const card = document.createElement("div");
  card.className = "card";
  const p = document.createElement("p");
  p.className = "note";
  p.textContent = NO_ACCESS_TEXT;
  card.appendChild(p);
  el.appendChild(card);
  return {};
}
