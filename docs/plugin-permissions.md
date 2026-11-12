# Plugin user permissions (SDK 1.5)

NetView users sign in and hold roles; roles grant permissions. This guide says how a plugin takes part:
which permissions it gets for free, how to declare its own, how its routes are guarded, and how to ask who
the caller is.

## The two meanings of "permissions"

A plugin has two unrelated sets of permissions.

- **Manifest `permissions`** (`Permission.API`, `Permission.NETWORK_PROBE`, ...) are what the *plugin* may do
  to the NetView core. The host checks them when the plugin loads.
- **`user_permissions`** are what *users* may do inside the plugin. Administrators grant them to roles in the
  Admin page.

This guide is about the second kind.

## Automatic permissions

Every plugin gets these without declaring anything, so a plugin written for SDK 1.3 or 1.4 keeps working:

| ID | Label | Exists when |
|---|---|---|
| `<id>.view` | View *Plugin name* | the plugin has the `api` or `web_ui` capability |
| `<id>.use` | Use *Plugin name* | the plugin has the `api` capability |
| `<id>.configure` | Change *Plugin name* settings | the plugin has a settings model |

A plugin's routes, static files and UI need `<id>.view` to read. Routes that change something need `<id>.use`.
Changing the plugin's settings needs `<id>.configure`.

## Declaring your own

List extra permissions on the class. IDs are relative to the plugin: `console` becomes `<plugin_id>.console`.

```python
from netview.sdk import Plugin, UserPermission


class SwitchPlugin(Plugin):
    user_permissions = (
        UserPermission("console", "Open the switch console", "Runs commands on the switch.", dangerous=True),
        UserPermission("use", "Poll and tag ports"),  # relabels the automatic "use" permission
    )
```

- An ID must match `[a-z0-9_.-]+` and may be declared once.
- Declaring `view`, `use` or `configure` does not add a permission; it relabels the automatic one. You may only
  do that when the automatic one exists (for example, `configure` needs a settings model).
- A bad declaration fails the plugin load with state `failed` and the reason.
- A disabled plugin still lists its permissions in the role editor, greyed out ("off").

## Guarding routes: `ctx.require`

The host attaches a default guard to every plugin router when it mounts it: `GET`, `HEAD` and `OPTIONS` need
`<id>.view`, every other method needs `<id>.use`. You do nothing to get it.

A route that needs something else says so with `ctx.require(...)`. An explicit guard **replaces** the default
for that route (it does not add to it), so a user holding only `demo.console` can open the console without
also holding `demo.use`.

```python
def router(self) -> APIRouter:
    router = APIRouter()

    @router.post("/console", dependencies=[self.ctx.require("console")])
    def open_console() -> dict[str, bool]:
        return {"opened": True}

    return router
```

- A relative ID gets your plugin ID prepended. A `core.*` ID is used as it is (`ctx.require("core.scan")`).
- A caller without the permission gets `403`; an anonymous one never reaches the route (`401`).
- Guards run before your code. Do not rely on the UI hiding a control: the server decides.

## The caller: `ctx.principal()`

`ctx.principal()` returns a `Principal` (`username`, `display_name`, `provider`, `can(permission_id)`).

- Inside a request it is the signed-in user.
- Outside a request (a job, an event handler) it is the system principal, which holds every permission.

```python
who = self.ctx.principal().username
if self.ctx.principal().can("demo.console"):
    ...
```

## Audit: `ctx.audit`

`ctx.audit(action, target=None, ok=True, detail=None)` hands an entry (time, caller, action, target, outcome,
detail) to NetView's audit sink. In stage 1 the sink discards entries; the audit plugin arrives later, so it is
safe to call now.

## In the browser: `can()` and slot `permission`

The UI API a plugin module receives gains (see the web UI notes for the full shape):

- `user`: the signed-in user.
- `can(rel)`: whether the user holds the permission. A relative ID resolves to `<pluginId>.<rel>`; `core.*`
  passes through.
- a `permission` field on a slot contribution: the slot is hidden from users who lack it.

These hide controls for tidiness only; every action is checked again by the server.

## Testing

`FakePluginContext` in `netview.sdk.testing.fakes` implements `require` as a dependency that lets everyone
through, `principal()` as the system principal and `audit` as a no-op, so plugin unit tests need no sign-in.
