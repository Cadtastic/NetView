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

/**
 * Where to go after signing in. The server redirect can't see the part after # (the browser never sends it),
 * so it arrives as this page's own hash; an explicit # inside `next` wins.
 */
export function afterSignIn(search, hash, origin = location.origin) {
  const next = new URLSearchParams(search).get("next") || "/";
  return safeNext(next.includes("#") ? next : next + (hash || ""), origin);
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
    passwordMinLength: (me && me.password_min_length) || 12,
  };
}

/**
 * The rules a new password must meet, each with whether it is met. The server checks the same rules; these let a
 * form say what's missing as you type. `username`, `current` and `confirm` add their rule only when given.
 */
export function passwordChecks({ password = "", confirm, username = "", minLength = 12, current }) {
  const filled = password !== "";
  const rows = [{ id: "length", text: `At least ${minLength} characters`, ok: [...password].length >= minLength }];
  const name = username.trim().toLowerCase();
  if (name) rows.push({ id: "username", text: "Not the same as the username", ok: filled && password.trim().toLowerCase() !== name });
  if (current !== undefined) rows.push({ id: "current", text: "Different from your current password", ok: filled && password !== current });
  if (confirm !== undefined) rows.push({ id: "confirm", text: "Both passwords match", ok: filled && password === confirm });
  return rows;
}

/** True when every rule passes. */
export const passwordReady = (rows) => rows.every((r) => r.ok);

/** The checklist markup: one line per rule, marked met or not. */
export function checksHtml(rows) {
  return rows
    .map((r) => `<li class="${r.ok ? "ok" : "no"}"><span aria-hidden="true">${r.ok ? "✓" : "•"}</span> ${esc(r.text)}</li>`)
    .join("");
}

/**
 * Keep a checklist and a button in step with a form: on every input, redraw `list` and enable `button` only when
 * `ready()` is true. `read()` returns the passwordChecks arguments. With `optional`, an empty password shows no
 * checklist and doesn't hold the button back. Returns a function that re-runs the check.
 */
export function wirePasswordChecks({ root, list, button, read, optional = false, ready = () => true }) {
  const update = () => {
    const args = read();
    const skip = optional && !args.password;
    const rows = skip ? [] : passwordChecks(args);
    list.innerHTML = checksHtml(rows);
    list.hidden = skip;
    button.disabled = !(ready() && (skip || passwordReady(rows)));
  };
  root.addEventListener("input", update);
  root.addEventListener("change", update);
  update();
  return update;
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
