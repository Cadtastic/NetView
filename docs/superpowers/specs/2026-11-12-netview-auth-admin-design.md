# NetView sign-in, users, roles and administration: design

Date: 2026-11-12. Status: design, approved for planning once the user signs off.
Builds on `2026-11-10-netview-design.md` (the base spec). Section numbers below like "base §7.6" point into that file.

Marking: plain statements are the user's decisions. *(my call)* marks a choice made while writing this up, which the builder may revisit if they find a strong reason, and should say so.

## 1. Intent

NetView started as a single-user tool on `localhost`. The base spec listed "authentication, multiple users, exposing the app beyond localhost" as a later non-goal. This design is that "later".

Two kinds of installs share one app:

- **Enterprise:** NetView runs on a VM inside a company's trusted network. Many network admins and IT staff sign in, mostly with their company account (Microsoft Entra ID, Google Workspace, Okta…), and should see or do different things. For example, a helpdesk tech can look at the switch faceplate and device list, but only senior admins can open the GSM7248 serial console or change plugin credentials.
- **Home:** one person manages their own network. They create one admin account and get on with it.

The line that matters is **looking vs doing**, and plugin developers must be able to draw that line for their own plugin's features. An admin turns those per-plugin permissions into roles, and users get roles.

## 2. Goals, non-goals, anti-goals

**Goals**

1. App-managed users with roles and permissions, administered from a new **Admin** page.
2. Sign-in with local NetView accounts, Microsoft (Entra ID), Google, GitHub, and any generic OpenID Connect provider (Okta, Keycloak, Authentik…).
3. A plugin SDK that lets each plugin declare its own permissions, guard its API routes and hide its UI by permission, and write audit entries.
4. HTTPS, with a NetView-made certificate or the company's own.
5. An audit log of who did what, as a built-in plugin that can be turned off.
6. First-run setup that is safe on a shared network (Enterprise mode) and quick at home (Home mode).

**Non-goals (later; the design leaves room)**

- API keys for scripts, Home Assistant or other servers. Every request already resolves to a *principal* (§5), so a key can become a second kind of principal without reworking permissions.
- Mapping Entra / AD / IdP groups to NetView roles automatically. Roles are assigned in NetView for now.
- Two-factor authentication for local accounts. Outside providers bring their own.
- LDAP and SAML sign-in. The provider interface (§7.4) is built so they can be added later.
- Sign-in methods supplied by plugins. The provider list is built in.
- Pre-creating an outside user (e.g. "kdoe@corp.com via Microsoft, Helpdesk") before their first sign-in.
- The installer. It will set the Home/Enterprise mode later; for now it is a setting (§7.1).
- **A browser terminal for the GSM7248 serial console** (user: "plan for web terminal later"). For now the console is server-local only (§10.6). This work must leave room for it:
  - The later version streams the ssh session over a WebSocket to a vendored terminal library (e.g. xterm.js, served locally under the strict CSP).
  - It keeps the same `gsm7248.console` permission and the same audit entry.
  - So: the permission ID and description must not say "local", the principal must be resolvable on WebSocket connections (the session cookie works there), and the console route must keep its open logic separate from how the window is shown.

**Anti-goals (failure even if it "works")**

- **A permission that only hides a button.** Every check is enforced on the server. Hiding in the UI is a courtesy on top.
- **Locking the admin out.** There must always be a way back in: the built-in local admin, and a CLI reset from the server console.
- **Strangers walking in through an outside provider.** Turning on "Sign in with Google" must not let any Google account in the world view the network map (§7.3).
- **Breaking existing plugins.** A plugin written for SDK 1.4 keeps working, with safe default guards (§10.3).
- **Making a home install painful.** Home mode is: create an account, sign in, done.
- **A way to turn sign-in off.** There is none. A localhost-only dev server still signs in.

## 3. Decided by the user

- Users are assigned roles, and roles hold permissions. The Admin panel lists each installed plugin with the permissions it offers, and an admin ticks them per role.
- A user can hold more than one role, and their permissions add up.
- Permission IDs are prefixed with the plugin's ID so plugins can't collide.
- NetView's core has its own permissions (viewing devices, renaming, changing settings, managing users and roles…).
- The server enforces every check. The UI also hides what a user can't use.
- **Administrator** is a built-in role that always has every permission, including permissions from plugins installed later.
- **Default** is a built-in role, view-only out of the box. Every user created by an outside sign-in lands in Default. An admin can change what Default allows but cannot delete it. A new plugin's permissions never land in Default on their own.
- First run shows a **setup page that creates the admin account**. A **Home / Enterprise** switch (set by the future installer) decides whether setup also asks for a one-time **setup code** printed in the server console: Enterprise asks, Home skips.
- The built-in local admin can always sign in with a password, even if every outside provider is broken, and a `netview` CLI command resets its password from the server console.
- The sign-in provider list is fixed and built in, but built so new methods can be added later.
- Roles are assigned inside NetView. Group-to-role mapping is a possible future feature.
- HTTPS with either a NetView-made certificate or the company's own:
  - NetView generates a self-signed certificate on first start and prints its fingerprint in the console.
  - The company's certificate can be set in `netview.toml` or uploaded in the Admin page, and takes effect on restart.
  - Whenever NetView listens beyond localhost, HTTPS is required and cookies are secure-only. Localhost dev may stay plain HTTP.
- **Public address:** NetView works out its own address from how it is reached, and an admin can override it in Admin → General. Provider setup screens build the callback URL from it.
- **No landing-page setting.** After sign-in, people go back to the page they were trying to open, otherwise to the dashboard.
- **Audit log** is a built-in plugin that can be turned on and off. Its settings decide whether it shows as a dashboard card or as its own page. Everything below about what it records (§11) was agreed in conversation.
- API keys: possibly in the future. Two-factor: not for now.
- Administration lives on its own **Admin page** in the top nav, not in the Settings dialog. Its sections: Users, Roles, Sign-in providers, HTTPS certificate, General, Audit log. The mockups (sign-in page, setup page, Admin → Users, Admin → Roles) were approved as drawn; they are in `.superpowers/brainstorm/135-1794493547/content/` (git-ignored, local only) and are described in §9.

## 4. Constraints

- Clean Architecture layers and import-linter contracts as in base §5.1. Plugins import only `netview.sdk`.
- Keep today's protections: the Host allowlist, the required `X-Netview: 1` header on non-GET requests, and the strict CSP (no inline scripts, so the sign-in and setup pages use external JS modules like the rest of the UI).
- No build step for the UI. Plain ES modules, as today.
- Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, pydantic-settings, uv. `cryptography` is already a dependency.
- Plugin on/off still applies at the next restart (base §7.7).
- The repository is public. No secrets in code, fixtures or docs.
- Upgrading an existing install keeps its data. On the first start after the upgrade there are no users yet, so NetView shows the setup page, then everything is as before.

## 5. Concepts

| Concept | Meaning |
|---|---|
| **Principal** | Whoever is making a request. Today always a signed-in **user**. Later possibly an API key. Request handlers and plugins see a principal, never a raw session. |
| **User** | A NetView account: username, display name, email (optional), enabled flag, roles, last sign-in, created-by-setup flag. |
| **Identity** | How a user signs in. A local password, or a link to an outside account as (provider, subject). *(my call)* One identity per user in the first release. |
| **Role** | A named set of permissions. Two built-in roles: Administrator and Default. |
| **Permission** | An ID such as `core.rename` or `gsm7248.console`, with a label and a one-line description, owned by the core or by one plugin. |
| **Session** | A server-side record of a signed-in browser. |

**Naming clash to avoid.** Plugin manifests already have `permissions` (`devices:read`, `names:write`, `network:probe`, …). Those say what a *plugin* may do to NetView's core, base §7.8. They are unrelated to what a *user* may do, and stay as they are. *(my call)* In code and the SDK the new concept is called **user permissions** (`UserPermission`, `user_permissions()`); in the UI it is just "permissions". Docs for plugin developers must explain the difference in one paragraph.

## 6. Permissions model

### 6.1 Core permissions *(my call on the exact list; the user confirmed the kinds)*

| ID | Label | Covers |
|---|---|---|
| `core.view` | View devices and dashboard | `GET` state, devices, events, metrics, inspections, watches, plugins list; the live stream; `/docs` |
| `core.rename` | Rename devices | `PUT /devices/{key}/nickname` |
| `core.forget` | Forget devices | `DELETE /devices/{key}` |
| `core.watches` | Manage watches | `POST`/`DELETE /watches` |
| `core.scan` | Run scans and probes | `POST /scan`, `POST /devices/{ip}/probe`, `POST /inspections` |
| `core.plugins` | Turn plugins on or off | `PATCH /plugins/{id}` for the enabled flag |
| `core.users` | Manage users and roles | Admin → Users and Roles |
| `core.system` | Manage sign-in, HTTPS and general settings | Admin → Sign-in providers, HTTPS certificate, General |

**Installing plugins** (`POST /plugins/install`, catalog refresh) runs downloaded code, so it is **Administrator-only**. It is not a grantable permission, and the Roles screen shows it as a locked row with that reason *(my call, from the conversation)*.

The Default role starts with `core.view` only.

### 6.2 Permissions every plugin gets automatically *(my call)*

So that a plugin written for SDK 1.4 is safe without changes, and a new plugin gets sensible guards for free, NetView adds up to three permissions to every plugin:

| ID | Label | Shown when | Guards by default |
|---|---|---|---|
| `<id>.view` | View *Plugin name* | the manifest lists the `api` or `web_ui` capability | the plugin's `GET`/`HEAD` routes, and its static files at `/plugins/<id>/static/` (so its UI module never loads) |
| `<id>.use` | Use *Plugin name* | the manifest lists the `api` capability | the plugin's other routes (`POST`, `PUT`, `PATCH`, `DELETE`) |
| `<id>.configure` | Change *Plugin name* settings | the plugin class has a settings model | reading and changing its settings: the Settings dialog, `PATCH /plugins/{id}` for settings, and the `settings` field of `GET /plugins` and `GET /plugins/{id}` |

"Shown when" uses the manifest and class attributes, never `router()` or `ui()`. Those exist only after `setup()`, and only for enabled plugins (`infrastructure/plugins/host.py`).

**Plugins list responses are filtered.** Today `GET /plugins` and `GET /plugins/{id}` return each plugin's settings, with secrets masked but other values (SSH host and user, switch IPs) visible. After this work, the `settings` and `settings_schema` fields are left out for any plugin where the caller lacks `<id>.configure`.

**Static files are guarded separately.** Plugin static files are Starlette mounts outside `/api/v1/plugins/<id>/`, so a guard on the plugin's router never sees them. The authentication middleware (or a wrapped mount) checks `<id>.view` for `/plugins/<id>/static/…`.

**Which plugins appear on the Roles screen:**
- Enabled and disabled plugins both appear, because NetView imports both classes at start. A disabled plugin's group is marked "off", so an admin can prepare roles before turning it on. *(my call)*
- Plugins copied in or installed since start appear after the next restart, as everywhere else.

A plugin can override the default guard on any route with its own permission (§10.2). The Administrator role holds all of these. Default holds none of them.

Example, GSM7248 after this work: View NETGEAR GSM7248, Use NETGEAR GSM7248 (poll now, test connection), Change NETGEAR GSM7248 settings (SNMP and SSH credentials), and its own declared **Open serial console** (`gsm7248.console`).

### 6.3 Resolution

- A user's permissions = the union of their roles' permissions. Administrator = everything, computed, never stored as a list, so new plugins are covered automatically.
- Resolved on every request from a small in-memory cache that is cleared whenever a role, a user's roles, or the installed plugin set changes. A role change takes effect on the user's next request, with no sign-out needed.
- Permissions that belong to a plugin that is no longer installed stay stored on roles and are ignored, and they come back to life if the plugin is reinstalled.
  - The Roles screen lists them under **Uninstalled plugins**, ticked, so an admin can see and revoke them. Leaving one unticked removes it.
  - *(changed 2026-11-12 after a security review: hidden grants couldn't be revoked, and a different plugin reusing the ID would inherit them.)*

### 6.4 Built-in roles and the built-in admin

- **Administrator** and **Default** cannot be renamed or deleted. Administrator's permissions cannot be edited.
- The **built-in admin** is the local account created on the setup page. It cannot be deleted, disabled or removed from Administrator. Its password can be changed by itself, by another admin, or by the CLI.
- Other users can also be given Administrator.
- **No more power than you** *(added 2026-11-12 after security review)*. Someone who isn't an Administrator can only manage users and roles with no more power than their own, both before and after the change:
  - they can't grant, remove or rename around a permission they don't hold;
  - they can't reset the password of, edit or delete a user who holds such a permission;
  - only Administrators can grant or remove Administrator, or manage a user who holds it.

  Otherwise "reset their password, then sign in as them" would hand over that user's power. The Admin page shows such users and roles with their edit controls disabled and the reason.
- *(my call)* A user with no roles at all can sign in and sees a "You don't have access to anything yet; ask an admin" page.

## 7. Signing in

### 7.1 Mode and first run

- Setting `mode = "enterprise" | "home"` in `netview.toml`, `NETVIEW_MODE`, or `netview serve --mode`. **Default: enterprise** *(my call: the safe default; the future installer will set it explicitly)*.
- While the database has **no users**, every page redirects to `/setup` and every API call except the setup endpoints returns `409 {"error": "setup required"}`.
- **Enterprise:** on start with no users, NetView generates a random one-time setup code (e.g. 8 characters from an unambiguous alphabet), prints it prominently in the console and the log, and requires it on the setup page. A new code is generated on each start until setup is done. Wrong codes are rate-limited like passwords (§12).
- **Home:** no code.
- The setup form: admin username, password, confirm. Submitting it creates the built-in admin in Administrator, signs them in, and closes setup. Creation is atomic: a second, racing setup request fails.
- The setup page says outside sign-in can be added afterwards in Admin.

### 7.2 Local accounts

- Created on the setup page (the built-in admin) or by an admin in Admin → Users ("Add local user": username, display name, initial password, roles).
- *(my call)* An admin-set password is marked "must change at next sign-in".
- Passwords hashed with **Argon2id** (`argon2-cffi`) *(my call)*. No composition rules, and a password must not equal the username *(my call, NIST-style)*.
- **Minimum length: 12 by default, admin-configurable** in Admin → General (user's decision). *(my call)* NetView will not accept a minimum below 8. A new minimum applies to passwords set from then on, not to existing ones.
- Users change their own password from the account menu ("Change password", local accounts only).
- The username/password form is always on the sign-in page, so the built-in admin can always get in.

### 7.3 Outside sign-in (Microsoft, Google, GitHub, generic OpenID Connect)

- Configured in Admin → Sign-in providers. Each provider: on/off, button label, client ID, client secret (stored like plugin `SecretStr` settings: real value in the database, masked everywhere else), plus provider-specific fields below. The screen shows the exact **callback URL** to paste into the provider's app registration, built from the public address (§8.3), with a copy button.
- The sign-in page shows a button for each provider that is on.
- First successful sign-in with an outside account creates a NetView user in **Default**, using the provider's display name and email, with username = email (GitHub: login name). Later sign-ins match strictly on (provider, provider's stable subject ID), **never by email** *(my call: email matching lets one provider's account take over another's user)*.
- A disabled user is refused, and the refusal is audited.

**Who may sign in at all** *(my call; see anti-goals)*. Each provider has an allow-list, and NetView refuses to turn a provider on without one unless the admin ticks an explicit "Allow any account from this provider" with a warning:

| Provider | Protocol | Provider fields | Allow-list |
|---|---|---|---|
| Microsoft | OpenID Connect | Tenant (ID or domain) | the tenant itself; single-tenant by default |
| Google | OpenID Connect | none | allowed email domains (checked against the verified email and the `hd` claim) |
| GitHub | OAuth 2 (not OIDC) | none | allowed organizations (scope `read:org`) and/or allowed usernames |
| Generic OpenID Connect | OpenID Connect via discovery | issuer URL, scopes (default `openid profile email`), which claim is the username | allowed email domains (optional when the IdP is the company's own) |

Stable subject IDs: Microsoft `tid` + `oid`; Google and generic OIDC `iss` + `sub`; GitHub numeric user ID.

Flow details: authorization code flow with PKCE, `state` and (for OIDC) `nonce`, ID token signature and audience checked against the provider's published keys. *(my call)* Library: **Authlib** with httpx.

### 7.4 Provider interface (for future methods)

Internally every sign-in method implements one small interface in the application layer, roughly: a provider type ID; a settings model; `start(request) -> redirect` and `finish(request) -> ExternalIdentity(provider, subject, username, display_name, email)` for redirect-based methods, or `verify(username, password) -> ExternalIdentity` for form-based ones (local today, LDAP later). The registry of types is built in. Adding LDAP or SAML later means one new implementation and its settings form, nothing else.

### 7.5 Sessions

- A random 256-bit session token in a cookie `netview_session`: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` whenever served over HTTPS. Only a hash of the token is stored, in a `sessions` table, with user, created, last seen, expires, IP and user agent.
- Idle timeout **8 hours** and absolute lifetime **7 days** by default, both admin-configurable in Admin → General (defaults my call, configurability the user's).
- Signing out deletes the session. Disabling or deleting a user, or resetting their password, deletes all their sessions at once.
- **Security version** *(added 2026-11-12 after security review)*. Each user carries a number that a password reset or a password change bumps. Each session records the number it was created under, and a session from an older number is rejected and deleted on its next use.
  - This closes the gap where a session created a moment after "end all sessions" ran would survive.
  - Sign-in also re-reads the user just before creating the session, and fails if the password, the enabled flag or the provider changed while the password was being checked.
  - Changing your own password keeps the current session (carried over to the new number) and ends the others.
- *(my call)* A new session ID is issued at every sign-in (no fixation).

### 7.6 Getting back in

- The built-in admin's password form is always available (§7.2).
- CLI, run on the server, talking straight to the database as the CLI does today:
  - `netview users list`
  - `netview users reset-password USERNAME`: prompts for the new password twice, clears that user's sessions, and writes an audit entry if the audit plugin is on.
- *(my call)* `netview users enable USERNAME` re-enables a disabled user. It can't apply to the built-in admin, which can't be disabled.

### 7.7 After sign-in

People return to the page they were trying to open (a `next` path, which must be a same-site relative path), otherwise to the dashboard.

## 8. HTTPS, host allowlist and public address

### 8.1 When HTTPS is on

- If `bind` is a loopback address and no certificate is configured, NetView serves plain HTTP. This keeps today's dev server on 8766 working.
- If `bind` is anything else, NetView serves **HTTPS only**. It refuses to start on a non-loopback address without TLS *(my call)*. A reverse proxy on the same machine can terminate TLS and talk to NetView on loopback.
- Settings: `tls_cert_file` and `tls_key_file` (PEM; the cert file may hold the chain).
- **Reverse proxies** *(my call)*: a `trusted_proxies` list in `netview.toml` (addresses or CIDRs), empty by default. For requests whose direct peer is on that list, NetView takes the client IP, scheme and host from `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host`. For everyone else it ignores those headers.
  - Everything that needs the client's view uses these values: the sign-in lockout key (§12), audit source IPs, the cookie `Secure` flag, the derived public address (§8.3) and the Host allowlist (§8.4).
  - Without this, every request behind a proxy would come from 127.0.0.1 over HTTP. Lockout would then work per username only, so anyone could lock out the built-in admin.

### 8.2 Certificates

- **NetView-made:** on first HTTPS start without configured files, NetView generates a key and a self-signed certificate in `<data_dir>/tls/` using `cryptography`. Its Subject Alternative Names cover `localhost`, the machine's hostname and FQDN, its IP addresses, and the public address's host if set. *(my call)* 825-day validity, regenerated automatically at start when within 30 days of expiry. The SHA-256 fingerprint is printed in the console on every start.
- **Company certificate:** point `netview.toml` at the files, or upload a PEM certificate (with chain) and its key in Admin → HTTPS certificate. NetView checks that the key matches the certificate before saving them under `<data_dir>/tls/`. Configured files in `netview.toml` win over uploaded ones. Either change shows "restart to apply".
- Admin → HTTPS certificate shows the active certificate: source (NetView-made, uploaded, or file from `netview.toml`), subject, SANs, issuer, expiry, and fingerprint. It warns 30 days before expiry.
- *(my call)* The key file is written with owner-only permissions where the OS allows it.

### 8.3 Public address

- Admin → General → **Public address** (e.g. `https://netview.corp.local:8765`). Empty by default, which means "work it out from the request": scheme and Host of the current request.
- Used to build provider callback URLs (`<public address>/auth/<provider>/callback`) and any absolute link NetView emits.
- An admin should set it whenever a reverse proxy or DNS alias sits in front of NetView. The provider setup screen warns when it is empty.

### 8.4 Host allowlist

Today the allowlist is only `localhost`, `127.0.0.1`, `[::1]` and the bind address, so a VM bound to `0.0.0.0` would reject every request made by name or IP. The allowlist becomes:

- the loopback names;
- the bind address;
- the machine's hostname, FQDN and IP addresses;
- the public address's host;
- an `allowed_hosts` list in `netview.toml` for anything else.

## 9. Admin page and UI changes

### 9.1 Admin page

A top-nav **Admin** page, shown only to users holding `core.users` or `core.system` (or Administrator). It has a left sidebar of sections; each section is shown only to someone who may use it.

- **Users:** a table of user, "signs in with", role pills, last sign-in, and built-in/disabled markers. "Add local user". Edit lets an admin change roles, disable or re-enable, reset the password (local accounts), or delete. The built-in admin row offers only a password change.
- **Roles:** the roles list on the left (Administrator and Default marked built-in, others showing user counts) and "New role". On the right, the selected role's permissions are ticked in groups: **NetView core** first, then one group per installed plugin by name. Each permission has its label and description; dangerous ones carry a short warning in their description, e.g. "full CLI access to the switch". Administrator's ticks are all on and locked. The plugin-install row is locked (§6.1).
- **Sign-in providers:** one card per provider type (§7.3), with the callback URL and copy button, the allow-list, and a "Test sign-in" link that runs the flow in a new tab without changing the current session *(my call; nice-to-have, builder may drop)*.
- **HTTPS certificate:** §8.2.
- **General:**
  - public address;
  - password minimum length (default 12, floor 8);
  - session idle timeout (default 8 hours) and absolute lifetime (default 7 days);
  - sign-in lockout: failures allowed (5), within (15 minutes), locked for (15 minutes);
  - the mode, read-only, with how to change it.

  Every value shows its default and has a "reset to default" control. Changes apply immediately and are audited. *(my call)* Audit retention (default 90 days) stays in the audit plugin's own settings, Administrator-only (§11).
- **Audit log:** *(my call)* status (on or off, retention) and a link to the log wherever its setting puts it. When the plugin is off, it says plainly that **nothing is being recorded**.

### 9.2 Sign-in and setup pages

- `/login`: the NetView name, a button per enabled provider, then "or with a NetView account" and the username/password form. Errors are generic ("Username or password is wrong").
- `/setup`: "Welcome to NetView", a line explaining what happens, the setup-code field (Enterprise only), username, password, confirm, and "Create account and sign in".
- Both are small static pages with their own JS module, styled with the current theme tokens.

### 9.3 The shell

- Top-right **account menu**: the display name, "Signed in with Microsoft" (or the provider used), "Change password" for local accounts, and "Sign out".
- The shell fetches `GET /api/v1/auth/me` at start (user, provider, permission IDs) and hides what the user can't use:
  - core actions: rename, forget, watches, scan, probe buttons;
  - Settings dialog plugin tabs where the user lacks `<id>.configure`;
  - plugin UI modules where the user lacks `<id>.view` (not loaded at all);
  - individual slots with a `permission` (§10.4).
- Any `401` from the API sends the browser to `/login?next=<current path>`. A `403` shows a toast "You don't have permission to do that".

## 10. Plugin SDK (version 1.5)

### 10.1 Declaring permissions

```python
from netview.sdk import Plugin, UserPermission


class Gsm7248Plugin(Plugin):
    def user_permissions(self) -> list[UserPermission]:
        return [
            UserPermission(
                "console",
                "Open serial console",
                "Full CLI access to the switch over its serial port.",
                dangerous=True,
            ),
        ]
```

- The ID is plugin-relative; NetView prefixes it (`gsm7248.console`). IDs are lowercase `[a-z0-9_.-]`. The loader rejects duplicates, and IDs that clash with the automatic `view`/`use`/`configure`.
- `dangerous=True` only affects display (a warning marker on the Roles screen).
- The declaration is a **class-level** attribute (e.g. a `ClassVar` list), not something built in `setup()`. The Admin page must list it for disabled plugins too, which never run `setup()`. The example above as a method is illustrative only; the exact name is the builder's call.
- A plugin may **relabel** its automatic permissions, e.g. the audit plugin renames `audit.view` to "View audit log". It may not declare a new permission with the ID `view`, `use` or `configure`.

### 10.2 Guarding routes

- Every route under `/api/v1/plugins/<id>/` gets the default guard from §6.2 automatically, so an unguarded route is never open.
- A plugin replaces the default on a route with its own permission, e.g. `@router.post("/console/open", dependencies=[ctx.require("console")])`. `ctx.require` also accepts `core.*` IDs.
- A plugin that needs the caller inside a handler gets it from `ctx.principal()` (username, display name, `can(permission_id)`), backed by a request-scoped context variable. Outside a request (jobs) it returns a "system" principal.

### 10.3 Older plugins

Plugins built for SDK 1.4 or earlier load unchanged. They get the automatic permissions and default guards, and nothing else. `sdk_version` ranges such as `>=1.3,<2` keep matching.

### 10.4 UI

The object passed to a plugin's UI module gains:

- `user`: `{ username, displayName }`;
- `can(id)`: plugin-relative IDs resolve to this plugin; `core.*` IDs work too;
- an optional `permission` on any slot spec. The shell skips the slot when the user lacks it. For a `page` slot, the nav tab is hidden.

### 10.5 Audit hook

`ctx.audit(action, target=None, ok=True, detail=None)` writes an entry attributed to the current principal. It is a no-op when the audit plugin is off. Example: `ctx.audit("console.open", target="GSM7248 192.168.1.36")`.

### 10.6 Existing plugins to update in this work

- **GSM7248:** declare `console`; guard the console routes with it; use `ctx.audit` on console open.
  - **Server-local only** (user's decision). Today the console opens a Windows Terminal window on the NetView machine itself (`plugins/gsm7248/console.py`), so for anyone signed in from another PC nothing would appear on their screen.
  - The open route therefore also requires that the real client address is loopback, using the trusted-proxy rules in §8.1. Otherwise it returns `403` with "The serial console opens on the NetView server; use it there".
  - The UI shows the button disabled, with that reason as its tooltip, for remote users who hold the permission. It is hidden for users without the permission.
  - The browser terminal comes later (§2).
- **GS105E, Starlink, Roku, built-ins:** rely on the defaults. Review each for a route whose method gives the wrong default, e.g. a `GET` that changes something. Fix the route or guard it explicitly.
- Update the plugin developer docs and the catalog entries' `sdk_version`.

## 11. Audit log plugin

- A built-in plugin `audit` (entry point like the other built-ins), **on by default** *(my call)*. Turning it off or on applies at restart, like any plugin.
- Settings: **Show as** dashboard card or its own page; **Keep entries for** N days (default 90).
- Viewing the log is the automatic `audit.view` (§6.2), relabelled "View audit log". Only Administrator has it by default.
- *(my call)* **Turning the audit plugin off and changing its retention are Administrator-only.** Otherwise anyone holding `core.plugins` or `audit.configure` could hide what they did. Like plugin installing, those two show as locked rows on the Roles screen. `audit.configure` covers only "Show as".
- **What is recorded:**
  - sign-ins, including failures (with the username tried);
  - sign-outs and session expiry by admin action;
  - setup completed;
  - user, role and provider changes;
  - certificate and General changes;
  - plugin install, enable/disable and settings changes (setting names only; secret values never appear);
  - the core doing-actions: rename, forget, watches, scans, probes;
  - anything a plugin writes with `ctx.audit`.
- **Each entry:** time, principal (username at the time, kept even if the user is later deleted), source IP, action ID, target, outcome (ok/denied/failed), and a short detail.
- **Mechanism:** the core and plugins write through an application-layer `AuditSink` port. The audit plugin provides the real sink; without it the core uses a null sink. Audit entries do **not** go into the network Events feed. *(my call)* Permission-denied (`403`) responses on doing-routes are recorded as "denied".
- **Viewer:** a newest-first table, filterable by user, action and date range, in the card or page per the setting. *(builder's call)* CSV export.

## 12. Security details

- **CSRF:** the existing `X-Netview: 1` header rule on non-GET requests stays, together with `SameSite=Lax` cookies. The login, setup and password forms post via `fetch` with that header. The OAuth callbacks are `GET` and protected by `state`.
- **Unauthenticated routes:**
  - `/login`, `/setup`, and the core static assets and theme CSS they need;
  - `/auth/<provider>/start` and `/auth/<provider>/callback`;
  - `POST /api/v1/auth/login`, `GET /api/v1/auth/providers`;
  - the setup endpoints, only while setup is open.

  Everything else needs a session. That includes `/docs`, `/openapi.json` and plugin static files *(my call)*.
- **Failed sign-ins:** by default, after **5** failures for one username from one IP within **15 minutes**, that IP is refused for that username for **15 minutes**.
  - All three numbers are admin-configurable in Admin → General (defaults my call, configurability the user's).
  - The setup code uses the same defaults; it isn't configurable, because there is no admin yet.
  - All failures are audited.
  - *(added 2026-11-12 after security review)* **Per-address cap:** one address is locked after 4 × the limit (20 by default) failures across *any* usernames. This stops guessing one password against many accounts, and stops one source filling the table.
  - Each attempt reserves its place before the slow password check, so parallel guesses can't all slip under the limit.
  - "Change password" counts wrong current passwords the same way.
  - Live state (failures inside the window, locks, attempts in progress) is never forgotten to make room. When the table is full, only old per-username counts that aren't locked or in use are dropped. Address counts never are. If nothing can be dropped, new attempts are refused.
  - **Tiers**, each locking on its own within the window (L = the configured limit, 5 by default):
    - username + exact address: L;
    - exact address, any username: 4 × L;
    - IPv6 only, username + /64: 4 × L, so rotating through a /64 can't escape the limit for a targeted account;
    - IPv6 only, whole /64, any username: 50 × L. This is a high backstop: a LAN usually shares one /64, and five noisy privacy addresses must not lock out the neighbours.
  - An IPv4-mapped IPv6 address counts as the IPv4 one.
  - **Bounded bookkeeping:** a /64 keeps at most 8 exact-address counts, and a /48 at most 16 /64 counts. Past those, the overflow is counted together one level up: username + /48 at 4 × L, and the whole /48 at 100 × L. Rotation therefore can't fill the table, which holds 100,000 entries.
  - Cap counts (address, /64, /48, and a username's network-wide counts) and locks are never dropped to make room. Only unlocked, idle per-username exact-address counts may be, plus a username's network count once that network's backstop is locked *and* the count would expire before the lock lifts (the backstop refuses for it until then; with the lock set shorter than the window, the count is kept). If nothing can be dropped, new attempts are refused.
  - **A success clears only that exact address's count.** Network-wide counts expire with the window, so the owner signing in on the same LAN doesn't reset an attacker's progress.
  - **Known devices:** an exact address that signed in to an account within 30 days skips that account's network-wide username limit. Its own exact-address tiers always apply, even past the /64's address cap, and so does the /64 backstop. This stops someone on the same LAN locking the owner out of their usual device. Only a correct password makes a device known, and at most 16 per username (10,000 overall) are remembered, oldest dropped first.
  - `begin` returns the exact keys it reserved, and the attempt is settled on exactly those.
  - **Known trade-off:** everyone behind one shared proxy or NAT address shares its per-address count until stage 2's `trusted_proxies` gives NetView the real client address.
- **Secrets:** provider client secrets are stored like plugin secrets today (real in the database, masked in API responses and logs). Encryption at rest is out of scope, as it is for plugin secrets.
- **Live stream:** `/api/v1/stream` needs `core.view`, and is closed when the session ends or the user is disabled. The check runs at the next keep-alive *(my call)*.

## 13. API and data

### 13.1 Endpoints (new)

- `GET /api/v1/auth/me`
- `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `POST /api/v1/auth/password`
- `GET /api/v1/auth/providers`: enabled providers for the sign-in page
- `GET /auth/{provider}/start`, `GET /auth/{provider}/callback`
- `GET /api/v1/setup`: status and whether a code is needed. `POST /api/v1/setup`.
- `GET|POST /api/v1/admin/users`, `GET|PATCH|DELETE /api/v1/admin/users/{id}`
- `GET|POST /api/v1/admin/roles`, `GET|PATCH|DELETE /api/v1/admin/roles/{id}`
- `GET /api/v1/admin/permissions`: the catalog, grouped core first, then by plugin
- `GET|PUT /api/v1/admin/providers/{type}`
- `GET /api/v1/admin/certificate`, `POST /api/v1/admin/certificate`: upload
- `GET|PATCH /api/v1/admin/general`
- `GET /api/v1/plugins/audit/entries`: from the audit plugin

Existing core endpoints get the guards in §6.1. Unauthenticated → `401`, signed in without permission → `403`, both with the usual `{"error": …}` body.

### 13.2 Tables (indicative; new core migration `0004`, parent `0003_plugin_catalog`)

`users`, `identities` (user, provider type, subject, password hash for local), `roles`, `role_permissions` (role, permission ID), `user_roles`, `sessions`, `auth_providers` (type, enabled, settings JSON with secrets), `app_settings` (key/value for General). The audit plugin owns `audit_entries` in its own Alembic branch (base §7.5).

### 13.3 Layers

- **Domain:** user, role, the permission-set rules (Administrator = all, union of roles, built-in protections).
- **Application:**
  - use cases: setup, sign in, sign out, change password, manage users, manage roles, configure providers;
  - ports: password hasher, session store, sign-in provider interface, certificate store, audit sink;
  - the permission catalog built from the core list plus loaded plugins.
- **Infrastructure:** Argon2, Authlib, SQLAlchemy repositories, certificate generation and checking.
- **Presentation:**
  - an authentication middleware or dependency that resolves the principal and enforces the route's permission;
  - the new routers, the login and setup pages, the Admin page, and the account menu;
  - the `users` CLI commands and `serve --mode`.

## 14. Left to the builder

- Library choices beyond those marked (Authlib, argon2-cffi are my picks; swap only with reason).
- Exact SDK method names and signatures, keeping the shapes in §10.
- How the default guards in §6.2 are attached to plugin routers. A router-level dependency added at mount time is the obvious route.
- Table column details and the Admin page's exact layout within the approved mockups.
- Test strategy. It must include:
  - unauthenticated and forbidden calls to every core route;
  - a plugin route with and without an explicit guard;
  - an SDK 1.4-style plugin;
  - the setup race;
  - mocked provider flows;
  - browser checks of the sign-in, setup and Admin pages (the user expects these done by Claude, not left to them).
- **Order of delivery** *(suggestion)*:
  1. Users, roles, permissions, sessions, local sign-in, setup, the CLI, core route guards, SDK 1.5 hooks, the Admin page's Users, Roles and General sections, and UI hiding.
  2. HTTPS, certificates, the host allowlist and the public address.
  3. Outside providers.
  4. The audit plugin, and the existing plugin updates (§10.6).

  The `AuditSink` port with its null sink belongs in stage 1 so later stages can call it.
