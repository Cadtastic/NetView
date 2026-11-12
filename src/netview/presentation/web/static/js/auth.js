// Who is signed in: the safe post-sign-in redirect, the permission helper, and the account menu.
import { esc } from "./util.js";

/** The same-origin path to go to after sign-in, or "/" for anything that would leave NetView. */
export function safeNext(raw, origin = location.origin) {
  if (typeof raw !== "string" || raw === "" || raw[0] !== "/") return "/";
  let url;
  try {
    url = new URL(raw, origin); // the browser's own parser: tabs/newlines stripped, "\" read as "/"
  } catch (e) {
    return "/";
  }
  if (url.origin !== origin) return "/";
  if (url.pathname === "/login" || url.pathname === "/setup") return "/";
  const out = url.pathname + url.search + url.hash;
  // Dot segments can collapse into a "//host" pathname ("/.//evil" -> "//evil"), which a browser reads as
  // another site. Check the string we hand back, not just the input.
  if (out.startsWith("//") || out.startsWith("/\\")) return "/";
  if (new URL(out, origin).origin !== origin) return "/";
  return out;
}

/** The signed-in user from the /auth/me body: {user, provider, can(id), isAdmin, mustChange}. */
export function createAuth(me) {
  const isAdmin = !!(me && me.is_admin);
  const granted = new Set((me && me.permissions) || []);
  return {
    user: { username: (me && me.username) || "", displayName: (me && (me.display_name || me.username)) || "" },
    provider: (me && me.provider) || "local",
    can: (id) => isAdmin || granted.has(id),
    isAdmin,
    mustChange: !!(me && me.must_change_password),
  };
}

/** The account menu's markup: name, how they signed in, Change password (local accounts only), Sign out. */
export function accountMenuHtml(auth) {
  const local = auth.provider === "local";
  return [
    `<div class="acct-name">${esc(auth.user.displayName)}</div>`,
    local ? `<div class="acct-note">Signed in with NetView account</div>` : "",
    local ? `<button type="button" data-acct="password">Change password</button>` : "",
    `<button type="button" data-acct="signout">Sign out</button>`,
  ].join("");
}
