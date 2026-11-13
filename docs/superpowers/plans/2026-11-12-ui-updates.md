# NetView UI Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Admin into the account menu, give Admin and Settings a shared Azure-style blade layout, and make the dashboard a 12-column grid that each user can customize and save, starting from a default layout that administrators set.

**Architecture:**

- Backend:
  - A pure layout record and its validation in `domain/dashboard.py`.
  - A `layouts` repository on the existing auth unit of work, implemented in memory and in SQL, with Alembic migration 0007.
  - A `DashboardLayouts` use case, served by a new `/dashboard` router and three `/admin/dashboard` routes.
- Front end:
  - One shared blade module (`js/blade.js`), used by Admin and by Settings.
  - The dashboard splits into four modules under `js/dashboard/`:
    - a pure layout model;
    - a persistent grid that moves DOM nodes and never rebuilds them;
    - a Customize controller;
    - a small API client.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core, Alembic, SQLite; plain ES modules, `node --test`; uv.

**Spec:** `docs/superpowers/specs/2026-11-12-ui-updates-design.md`. The approved mockup is next to it: `2026-11-12-ui-updates-mockup.html`. Read both before any front-end task. The owner approved the Admin look "perfect", so match the mockup's spacing, menu, command bar and child blade.

## Global Constraints

- Work in the worktree `R:\source\claude projects\HomeLab\netview-ui-updates`, branch `feature/ui-updates`. Commit author is the configured no-reply email. Don't push.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Implementers using another model put their own model name in that line.
- These gates must pass at the end of every task:
  - `uv run pytest -q`
  - `npm test`
  - `uv run ruff check .`
  - `uv run mypy src plugins`
  - `uv run lint-imports`
  - `uv run python scripts/build_plugin_index.py --check`
- Import-linter layering:
  - `domain` imports nothing outside itself;
  - `application` imports no `infrastructure`, `presentation`, `sqlalchemy` or `fastapi`;
  - `presentation` imports no `infrastructure`.
- `static/css/app.css` uses theme variables only. No colour literals: `tests/integration/test_css_tokens.py` and `test_css_balance.py` enforce this. Shadows use `var(--shadow)`.
- No new front-end dependencies and no icon font. Icons go in `static/js/icons.js` as inline SVG strings, like the existing ones.
- Front-end tests import modules directly. A module under test can't touch `document` or `window` at import time.
- The layout key is `<owner>.<kind>.<id>`:
  - `owner` is `core` or the plugin's guid. Built-in plugins also use their guid.
  - `kind` is `tile` or `card`.
- The server's key regex is exactly `^(core|[0-9a-f-]{36})\.(tile|card)\.[A-Za-z0-9_.-]{1,100}$`.
- Layout record: `{"version": 1, "order": [...], "hidden": [...], "spans": {key: "third"|"half"|"full"}, "group": "none"|"plugin"|"plugin_type"}`.
  - At most 500 keys across `order`, `hidden` and `spans`.
  - The serialized record is at most 65536 bytes.
- `app_settings` key for the default: `dashboard.default_layout`.
- New permission: `PermissionInfo("core.dashboard", "Customize my dashboard", "Arrange, resize, hide and group dashboard cards and save the layout to your profile")`, placed right after `core.view`. Not granted to the Default role.
- Copy is fixed by the spec:
  - Banner: "Drag cards to move them. Changes are only yours, and only kept when you save."
  - Default-editing banner: "Editing the default layout for everyone. Users who saved their own layout keep it until they reset."
  - Toasts: "Saved to your profile. Only you see this layout.", "Saved as the default layout for everyone", "Changes discarded", "Cards stay in their own group".
  - Default dashboard subtitle: "The layout new users start with, and what anyone gets when they choose Reset to default."
- Grouping labels:
  - Built-in group: "NetView" under Plugin, "NetView (built in)" under Plugin type.
  - `plugin_type` labels: router→Router, switch→Switch, access_point→Access point, firewall→Firewall, modem→Modem, server→Server, nas→NAS, computer→Computer, tv→TV, printer→Printer, camera→Camera, ups→UPS, iot→IoT, software→Software, other or missing→Other.
- Never point a browser check or test at the real data in `network/netview-dev`. Use a scratch copy.

## Review Focus

1. **A plugin item id the key regex rejects** (a space, a slash). The item still shows, after the customizable items in its group. It is never written to a saved layout, and Save still succeeds. *Pinned in Task 8.*
2. **The "failed to load" placeholder card for a broken plugin.** It is never part of a layout: not draggable, not hideable, always last. *Pinned in Task 8 (model) and Task 9 (grid).*
3. **A plugin tile whose `render` returns ""** (today that means "hide me"). It is hidden in view mode, keeps its place in `order`, and gets no tray chip. *Pinned in Task 9.*
4. **A stored layout, user or default, that is corrupt JSON or has another `version`.** `GET` falls back as if it were absent (default, then built-in) and never returns 500. *Pinned in Task 3.*
5. **A hidden key whose item no longer exists** (plugin uninstalled). The tray shows no chip for it, and the next save drops it. *Pinned in Task 8.*

---

### Task 1: Layout record, validation and the new permission

**Files:**
- Create: `src/netview/domain/dashboard.py`
- Modify: `src/netview/application/auth/catalog.py` (`CORE_GROUP`)
- Test: `tests/unit/domain/test_dashboard_layout.py`; `tests/unit/application/test_permission_catalog.py` (add one test)

**Interfaces:**
- Produces, in `netview.domain.dashboard`:
  - `LAYOUT_VERSION = 1`, `GROUPS = ("none", "plugin", "plugin_type")`, `SPANS = ("third", "half", "full")`
  - `KEY_RE` (compiled from the Global Constraints regex), `MAX_KEYS = 500`, `MAX_BYTES = 65536`
  - `@dataclass(frozen=True) class DashboardLayout: order: tuple[str, ...]; hidden: tuple[str, ...]; spans: tuple[tuple[str, str], ...]; group: str`
  - `parse_layout(raw: object) -> DashboardLayout`. It raises `netview.domain.errors.ValidationError(fields={...})`, with field names `version`, `order`, `hidden`, `spans`, `group` or `layout`.
  - `layout_to_dict(layout: DashboardLayout) -> dict[str, object]`
  - `layout_to_json(layout: DashboardLayout) -> str`. Compact and sorted keys.

- [ ] **Step 1: Write the failing tests**

```python
def test_round_trip_keeps_order_hidden_spans_and_group():
    raw = {"version": 1, "order": ["core.tile.online", "9f4cd689-1a67-4c89-abff-ac9252568d97.card.latency"],
           "hidden": ["core.card.events"], "spans": {"9f4cd689-1a67-4c89-abff-ac9252568d97.card.latency": "half"},
           "group": "plugin_type"}
    layout = parse_layout(raw)
    assert layout_to_dict(layout) == raw

def test_bad_values_name_their_field():
    for raw, field in [({"version": 2, "order": [], "hidden": [], "spans": {}, "group": "none"}, "version"),
                       ({"version": 1, "order": [], "hidden": [], "spans": {}, "group": "type"}, "group"),
                       ({"version": 1, "order": [], "hidden": [], "spans": {"core.card.x": "wide"}, "group": "none"}, "spans"),
                       ({"version": 1, "order": ["core.widget.x"], "hidden": [], "spans": {}, "group": "none"}, "order"),
                       ({"version": 1, "order": [], "hidden": ["Core.tile.x"], "spans": {}, "group": "none"}, "hidden"),
                       ("not a dict", "layout")]:
        with pytest.raises(ValidationError) as e:
            parse_layout(raw)
        assert field in e.value.fields

def test_dots_and_dashes_in_the_item_id_are_allowed():
    parse_layout({"version": 1, "order": ["core.card.top-uploader", "core.tile.dns.v2"], "hidden": [], "spans": {}, "group": "none"})

def test_more_than_500_keys_is_refused():
    keys = [f"core.tile.t{i}" for i in range(501)]
    with pytest.raises(ValidationError):
        parse_layout({"version": 1, "order": keys, "hidden": [], "spans": {}, "group": "none"})

def test_a_record_over_64_kb_is_refused_even_within_500_keys():
    guid = "c66a564b-0254-44cf-bb74-1c7f6ebae6be"
    keys = [f"{guid}.card.{i:03d}{'x' * 97}" for i in range(500)]  # 500 keys, about 72 KB serialized
    with pytest.raises(ValidationError) as e:
        parse_layout({"version": 1, "order": keys, "hidden": [], "spans": {}, "group": "none"})
    assert "layout" in e.value.fields

def test_duplicate_keys_keep_their_first_position():
    layout = parse_layout({"version": 1, "order": ["core.tile.a", "core.tile.b", "core.tile.a"], "hidden": [], "spans": {}, "group": "none"})
    assert layout.order == ("core.tile.a", "core.tile.b")
```

Add to `test_permission_catalog.py`:

```python
def test_core_dashboard_follows_core_view():
    ids = [p.id for p in CORE_GROUP.permissions]
    assert ids[ids.index("core.view") + 1] == "core.dashboard"
    perm = next(p for p in CORE_GROUP.permissions if p.id == "core.dashboard")
    assert perm.label == "Customize my dashboard"
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/unit/domain/test_dashboard_layout.py tests/unit/application/test_permission_catalog.py -q`
Expected: FAIL with ImportError, and the catalog test fails.

- [ ] **Step 3: Implement**
  - Write `domain/dashboard.py` to the interface above, using only the standard library.
  - Add the `PermissionInfo` from the Global Constraints to `CORE_GROUP`.
  - Seeded roles don't change. The migrations do nothing with it.

- [ ] **Step 4: Run the tests and all gates**

Expected: PASS. Existing permission tests that list the core ids in order need `core.dashboard` added. Update them, and make no other change.

- [ ] **Step 5: Commit** `feat: dashboard layout record and Customize my dashboard permission`

---

### Task 2: Layout storage (port, memory store, SQL store, migration 0007)

**Files:**
- Modify: `src/netview/application/ports/auth_store.py`, `src/netview/infrastructure/auth/memory_store.py`, `src/netview/infrastructure/auth/sql_store.py`, `src/netview/infrastructure/db/models.py`
- Create: `src/netview/infrastructure/db/core_versions/0007_dashboard_layouts.py`
- Test: `tests/contract/auth_store_contract.py`, `tests/contract/test_auth_store.py`, `tests/integration/db/test_migrate.py` (its head assertions `"0006"` become `"0007"`)

**Interfaces:**
- Produces, in `auth_store.py`:
  - `@dataclass(frozen=True) class StoredLayout: layout_json: str; updated_ms: int`
  - `class DashboardLayoutRepository(Protocol)`:
    - `get(user_id: int) -> StoredLayout | None`
    - `put(user_id: int, layout_json: str, updated_ms: int) -> None`
    - `remove(user_id: int) -> bool`
    - `remove_all() -> int`
    - `count() -> int`
  - `AuthUnitOfWork.layouts: DashboardLayoutRepository`
- Table `user_dashboard_layouts`:
  - `user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE`
  - `layout TEXT NOT NULL`
  - `updated_ms INTEGER NOT NULL`
  - ORM row class `UserDashboardLayoutRow`.
- Migration revision `"0007"`, down_revision `"0006"`, with a working `downgrade` (drop the table). `infrastructure/db/backup.py` keeps `REVISION = "0006"`: that backup belongs to the guid re-key only.

- [ ] **Step 1: Write the failing contract checks** in `auth_store_contract.py`, and register each in `test_auth_store.py` for both stores, the same way the existing checks are registered:

```python
def check_layout_put_get_replace_and_count(factory):
    store = factory()
    with store() as uow:
        uid = uow.users.add(make_user("kim"), None).id
        uow.layouts.put(uid, '{"a":1}', 5); uow.commit()
    with store() as uow:
        assert uow.layouts.get(uid) == StoredLayout('{"a":1}', 5)
        uow.layouts.put(uid, '{"a":2}', 9); uow.commit()
    with store() as uow:
        assert uow.layouts.get(uid) == StoredLayout('{"a":2}', 9)
        assert uow.layouts.count() == 1

def check_layout_remove_and_remove_all(factory):
    # remove() returns True once, then False; remove_all() returns how many were removed, then count() == 0

def check_deleting_a_user_deletes_their_layout(factory):
    # put a layout for a user, uow.users.remove(user_id), commit; uow.layouts.get(user_id) is None and count() == 0

def check_layout_writes_roll_back_without_commit(factory):
    # put without commit inside `with`; a new uow sees get() is None
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/contract -q`
Expected: FAIL (`AttributeError: ... 'layouts'`).

- [ ] **Step 3: Implement**
  - The memory store keeps layouts in `_Data`, copies them on commit the way the other maps are copied, and drops a user's layout in `_Users.remove`.
  - The SQL store adds a `SqlDashboardLayoutRepository` using SQLAlchemy Core on the new table, the same way `SqlSettingsRepository` works.
  - `SqlAuthUnitOfWork` exposes it as `layouts`.
  - SQLite already runs with `PRAGMA foreign_keys=ON`, so the cascade is real there.

- [ ] **Step 4: Add the migration test** to `tests/integration/db/test_migrate.py`:

```python
def test_0007_creates_user_dashboard_layouts_with_cascade(tmp_path):
    # upgrade_core on a fresh db; PRAGMA foreign_key_list(user_dashboard_layouts) names users/id with on_delete CASCADE;
    # downgrade to 0006 drops the table (use the _upgrade_to/command helpers the auth migration test uses)
```

- [ ] **Step 5: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 6: Commit** `feat: per-user dashboard layout storage (migration 0007)`

---

### Task 3: DashboardLayouts use case and the API

**Files:**
- Create: `src/netview/application/usecases/dashboard.py`, `src/netview/presentation/api/routers/dashboard.py`
- Modify: `src/netview/application/services.py` (`AuthServices.dashboard`), `src/netview/bootstrap.py`, `src/netview/presentation/api/app.py` (register the router next to `auth, setup, admin`), `src/netview/presentation/api/routers/admin.py`, `src/netview/presentation/api/schemas.py`, `tests/integration/api/api_helpers.py` (wire the new service)
- Test: `tests/unit/application/test_dashboard_layouts.py`, `tests/integration/api/test_dashboard_api.py`

**Interfaces:**
- Consumes: Task 1's `parse_layout`, `layout_to_json` and `DashboardLayout`. Task 2's `uow.layouts`, plus `uow.settings` and `uow.roles`.
- Produces, in `netview.application.usecases.dashboard`:
  - `DEFAULT_KEY = "dashboard.default_layout"`
  - `@dataclass(frozen=True) class LayoutView: layout: DashboardLayout | None; source: Literal["user", "default", "builtin"]; updated_ms: int | None; default: DashboardLayout | None`. `default` is the stored administrator default, or None for built-in. The editor's Reset to default uses it.
  - `@dataclass(frozen=True) class DefaultView: layout: DashboardLayout | None; users_with_own_layout: int; roles_with_permission: list[str]`. Role **names**, sorted, with Administrator always included.
  - `class DashboardLayouts(store: AuthStore, clock: Clock)`:
    - `mine(actor: Principal) -> LayoutView`
    - `save_mine(actor, layout: DashboardLayout) -> LayoutView`
    - `reset_mine(actor) -> LayoutView`
    - `default() -> DefaultView`
    - `save_default(actor, layout: DashboardLayout, *, clear_mine: bool) -> DefaultView`
    - `reset_everyone() -> int`
  - `AuthServices.dashboard: DashboardLayouts`. It's a required field, so add it before the defaulted fields.
- HTTP (all under `/api/v1`):

  | Method and path | Guard | Body | Response |
  |---|---|---|---|
  | `GET /dashboard/layout` | `core.view` | | `LayoutOut {layout: dict \| None, source, updated_ms, default: dict \| None}` |
  | `PUT /dashboard/layout` | `core.dashboard` | the layout dict | `LayoutOut` |
  | `DELETE /dashboard/layout` | `core.view` | | `LayoutOut` (after deleting) |
  | `GET /admin/dashboard/default` | `core.system` | | `DefaultLayoutOut {layout, users_with_own_layout, roles_with_permission}` |
  | `PUT /admin/dashboard/default` | `core.system` | `DefaultLayoutIn {layout: dict, clear_mine: bool = False}` | `DefaultLayoutOut` |
  | `DELETE /admin/dashboard/layouts` | `core.system` | | `ResetLayoutsOut {removed: int}` |

- Rules:
  - `mine` uses your stored layout only when `actor.can("core.dashboard")`, then the stored default, then built-in (`layout=None`).
  - A stored record that fails `json.loads` or `parse_layout` is treated as absent and logged with `log.warning`.
  - `save_mine` and `reset_mine` with `actor.user_id is None` raise `ValidationError("Sign in to save a dashboard layout")`.
  - `save_default(..., clear_mine=True)` also removes the actor's own layout, in the same unit of work.

- [ ] **Step 1: Write the failing unit tests.** Use `InMemoryAuthStore` and a fixed clock, with the helpers in `tests/unit/application/auth_helpers.py`:

```python
def test_mine_prefers_own_then_default_then_builtin(): ...
    # builtin: source "builtin", layout None, default None; after save_default: source "default" and view.default == that layout;
    # after save_mine: source "user", updated_ms == clock now, and view.default still the admin default
def test_own_layout_is_ignored_without_core_dashboard(): ...
    # save_mine as a user with core.dashboard, then mine() for the same user id with only core.view -> source "default" or "builtin"
def test_reset_mine_deletes_and_returns_what_applies_now(): ...
def test_save_default_with_clear_mine_removes_only_the_actors_layout(): ...
    # two users with layouts; admin saves default with clear_mine=True -> admin's gone, the other's kept; users_with_own_layout == 1
def test_reset_everyone_returns_the_count(): ...
def test_corrupt_or_old_records_fall_back(): ...   # Review Focus 4
    # uow.settings.set(DEFAULT_KEY, "{not json") -> source "builtin"; uow.layouts.put(uid, '{"version": 7}', 1) -> falls through to default
def test_roles_with_permission_lists_names_and_always_administrator(): ...
def test_system_principal_cannot_save(): ...
```

- [ ] **Step 2: Run them and see them fail.** `uv run pytest tests/unit/application/test_dashboard_layouts.py -q`. Expected: ImportError.

- [ ] **Step 3: Implement the use case**, then wire it in `bootstrap.py` and `api_helpers.build_world` as `DashboardLayouts(auth_store, clock)`.

- [ ] **Step 4: Write the failing API tests** in `test_dashboard_api.py`. Use `ApiWorld.grant`, `ApiWorld.add_user` and the `client_for` pattern from `test_plugin_guards.py`:

```python
def test_viewer_gets_builtin_and_cannot_put(world): # GET 200 source builtin; PUT 403
def test_customizer_round_trip_and_reset(world):    # grant core.dashboard; PUT then GET source user; DELETE then source builtin
def test_bad_layout_is_422_with_field(world):       # PUT {"version":1,"order":["bad key"],...} -> 422, "order" in body fields
def test_admin_default_flow(world):                 # PUT default (clear_mine false) -> viewer GET source default;
                                                    # GET default shows users_with_own_layout; DELETE layouts -> {"removed": n}
def test_admin_routes_need_core_system(world):      # a core.dashboard-only user gets 403 on all three /admin/dashboard routes
```

- [ ] **Step 5: Implement the schemas and routes.** `routers/dashboard.py` has `router = APIRouter(prefix="/dashboard")`. The admin routes go in `routers/admin.py` with `_SYSTEM`. Bodies arrive as `dict[str, Any]` and go through `parse_layout`.

- [ ] **Step 6: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 7: Commit** `feat: dashboard layout API (mine, default, reset everyone)`

---

### Task 4: Top bar, account menu and the hidden Admin route

**Files:**
- Modify: `static/index.html`, `static/js/main.js`, `static/js/auth.js` (`accountMenuHtml`), `static/js/nav.js`, `static/js/slots.js`, `static/css/app.css` (remove the `.topbar .meta` rules)
- Test: `tests/js/auth.test.mjs`, `tests/js/nav.test.mjs`, `tests/js/slots.test.mjs`, `tests/integration/api/test_web_shell.py`

All `static/` paths are under `src/netview/presentation/web/`.

**Interfaces:**
- Produces:
  - `accountMenuHtml(auth, { canAdmin = false } = {})`. In order: name, the provider note, then:
    - `<button data-acct="admin">` (when `canAdmin`);
    - `<button data-acct="settings">`;
    - `<button data-acct="password">` (local accounts only);
    - `<button data-acct="signout">`.
    - Each button gets an `icons.js` icon: `shieldLock`, `gear`, `key`, `logout`. Add the ones that are missing.
  - `withAdminRoute(routes, auth, mount)` now adds `{ path: "/admin", label: "Admin", hidden: true, prefix: true, mount }`.
  - `navItems` passes `hidden` through, and `navHtml` skips hidden items.
  - `pickRoute(items, path)` matches `i.path === path`, or `i.prefix && path.startsWith(i.path + "/")`.
  - `main.js` mounts a route with `ctx.path` (the full current path), so Admin can read its section.
  - Slot specs gain `pluginType: info.plugin_type || null` and `pluginSource: info.source`, next to the existing `pluginGuid` and `pluginDisplayName`.

- [ ] **Step 1: Write the failing tests**

```js
test("account menu: Admin only when allowed, then Settings, then Change password, then Sign out", () => {
  const html = accountMenuHtml(createAuth({ username: "a", provider: "local", is_admin: true }), { canAdmin: true });
  const order = [...html.matchAll(/data-acct="(\w+)"/g)].map((m) => m[1]);
  assert.deepEqual(order, ["admin", "settings", "password", "signout"]);
  assert.ok(!accountMenuHtml(createAuth({ username: "b", provider: "local" })).includes('data-acct="admin"'));
});
test("the Admin route is hidden from the nav but /admin/users still picks it", () => {
  const routes = withAdminRoute([{ path: "/", label: "Dashboard" }], createAuth({ is_admin: true }), () => ({}));
  const items = navItems(routes, [], "/admin/users");
  assert.ok(!navHtml(items).includes("Admin"));
  assert.equal(pickRoute(items, "/admin/users").path, "/admin");
});
test("slot specs carry the plugin type and source", async () => { /* loadPlugins with a stub info {plugin_type:"switch", source:"folder"} -> spec.pluginType/pluginSource */ });
```

In `test_web_shell.py`, assert that `id="meta"` is not in the index HTML and that `btnSettings` is still there.

- [ ] **Step 2: Run them and see them fail.** `npm test` and `uv run pytest tests/integration/api/test_web_shell.py -q`.

- [ ] **Step 3: Implement**
  - Delete `#meta`, `renderMeta()` and its call.
  - The account menu handler in `main.js`:
    - `admin` → `location.hash = "#/admin"`;
    - `settings` → `openSettings("appearance")`.
  - Pass `canSeeAdmin(auth)` as `canAdmin`. The gear button stays.

- [ ] **Step 4: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: Admin and Settings in the account menu; drop the This device text`

---

### Task 5: The blade layout module

**Files:**
- Create: `static/js/blade.js`
- Modify: `static/css/app.css` (new `.blade-*` rules), `static/js/icons.js` (`chevronsLeft`, `chevronDown`, `close` if missing, plus the menu icons used in Tasks 6 and 7: `adjustments`, `users`, `idBadge`, `layoutDashboard`, `palette`, `puzzle`, `download`)
- Test: `tests/js/blade.test.mjs`

**Interfaces:**
- Produces, in `blade.js`:
  - Pure helpers:
    - `filterMenu(menu, query) -> menu`. Case-insensitive match on the label. Groups left empty are dropped.
    - `menuHtml(menu, activeId, collapsed: Set<string>) -> string`. Items are `<button data-blade-item="<id>">`. The active one gets `class="on"` and `aria-current="page"`. Group headings are `<button data-blade-group="<name>" aria-expanded>`.
    - `crumbHtml(parts: string[]) -> string`. Every part but the last is `<a data-crumb="<index>">`. The last is `<b>`. Separators are ` › `.
    - `pageHeadHtml({ title, sub = "", commands = [] }) -> string`. Commands are `[{id, label, icon}]`, rendered as `<button data-cmd="<id>">` inside `.blade-cmd`.
  - `createBlade(root, { crumbRoot, menu, initial, onSelect, crumbHost = null, storageKey = null })` returns:
    - `select(id, { push = true } = {})`: draws the menu, calls `onSelect(id, pageEl, api)`, and sets the crumb to `[crumbRoot, label]`.
    - `openChild({ title, body: (el) => void, foot: (el, close) => void, opener = null }) -> { close }`
    - `closeChild()`
    - `setMenu(menu)`, used for counts.
    - `destroy()`
  - `menu` is `[{ group?: string, items: [{ id, label, icon, count? }] }]`.
  - When `crumbHost` is given (the Settings dialog), the crumb renders there instead of at the top of `root`.
  - `storageKey` keeps which groups are collapsed in `localStorage`, wrapped in try/catch.
- DOM shape, matching the mockup:
  - `.blade-crumb`
  - `.blade-wrap` containing:
    - `nav.blade-menu`, which holds the "«" `.blade-collapse` button, `input.blade-search`, then the items;
    - `section.blade-page`;
    - `aside.blade-child[aria-hidden]` (420 px).
- Behaviour:
  - The child slides in with a transform over about 180 ms. Under `prefers-reduced-motion` there's no transition.
  - Opening a child moves focus to its first focusable element. Esc closes it, and focus returns to `opener`.
  - Opening a child adds `title` to the crumb. Closing it, or clicking the section crumb, restores the crumb.
  - The menu is white (`--surface`) and the page is `--bg`. The selected item has `--surface-2` and `box-shadow: inset 3px 0 0 var(--accent)`.
  - Command buttons are borderless, coloured `--accent`, with a hairline under the bar.
  - Collapsing makes the menu a 52 px icon rail with labels hidden.

- [ ] **Step 1: Write the failing tests**

```js
test("filterMenu keeps matching items and drops empty groups", () => {
  const menu = [{ items: [{ id: "general", label: "General" }] }, { group: "Identity", items: [{ id: "users", label: "Users" }, { id: "roles", label: "Roles" }] }];
  assert.deepEqual(filterMenu(menu, "RO"), [{ group: "Identity", items: [{ id: "roles", label: "Roles" }] }]);
});
test("menuHtml marks the active item and shows counts", () => { /* aria-current on users; count 2 rendered; a collapsed group renders no items and aria-expanded="false" */ });
test("crumbHtml links all but the last part", () => {
  assert.equal(crumbHtml(["Admin", "Users", "Edit Addam"]), '<a data-crumb="0">Admin</a> › <a data-crumb="1">Users</a> › <b>Edit Addam</b>');
});
test("crumbHtml and pageHeadHtml escape text", () => { /* "<x>" becomes &lt;x&gt; */ });
test("pageHeadHtml renders commands as data-cmd buttons", () => { /* ... */ });
```

- [ ] **Step 2: Run them and see them fail.** `npm test`.

- [ ] **Step 3: Implement `blade.js` and the CSS.** `createBlade` only touches the DOM when it's called, never at import.

- [ ] **Step 4: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: shared blade layout (menu, command bar, child blade)`

---

### Task 6: Admin on the blade layout, with the Default dashboard section

**Files:**
- Modify: `static/js/pages/admin/admin.js`, `users.js`, `roles.js`, `general.js`; delete `pages/admin/dialog.js`, moving `showError` into `admin.js` or a small `pages/admin/errors.js`
- Create: `static/js/pages/admin/default-dashboard.js`, `static/js/dashboard/api.js`
- Modify: `static/css/app.css` (remove the `.admin`, `.admin-side`, `.admin-main` and `.admin-dlg` rules)
- Test: `tests/js/admin.test.mjs`

**Interfaces:**
- Consumes:
  - Task 5's `createBlade`, `pageHeadHtml` and `openChild`.
  - Task 4's `ctx.path`.
  - Task 3's HTTP routes.
- Produces:
  - `adminSections(auth)` returns `[{id, label, group?, icon}]` in this order:
    - `general` (`core.system`), no group;
    - `users` and `roles` (`core.users`), group "Identity";
    - `dashboard` (`core.system`), group "Dashboard", label "Default dashboard".
  - `sectionFromPath(path, sections) -> id | null`: `/admin/<id>` when that id is in `sections`, otherwise the first section.
  - Each `mountUsers`, `mountRoles`, `mountGeneral` and `mountDefaultDashboard` takes `(el, { auth, blade })`. It returns `{ destroy }` and draws its own `pageHeadHtml`.
  - Selecting a section runs `history.pushState(null, "", "#/admin/" + id)`. Back triggers `hashchange`, and `main.js` re-mounts with the new path.
  - In `static/js/dashboard/api.js`, each function returns the JSON from Task 3:
    - `getLayout()`, `saveLayout(layout)`, `resetLayout()`;
    - `getDefault()`, `saveDefault(layout, clearMine)`, `resetEveryone()`.
  - In `static/js/pages/dashboard.js` (it is replaced in Task 9, but this export is defined now and kept): `requestDefaultEdit()` sets a module flag that the next `mountDashboard` reads and clears.
- Screens:
  - **Users:** command bar has `add` and `refresh`. A row click opens the Edit user child blade. The footer is Save (primary) / Cancel / Delete (danger, right-aligned, keeping today's inline confirm). Add local user and admin password reset are also child blades. Your own row still opens `openPasswordDialog()`.
  - **Roles:** command bar has `new`. A row click opens the role editor in a child blade.
  - **General:** command bar has `save` and `discard`.
  - **Default dashboard:**
    - the subtitle from the Global Constraints;
    - command bar: `edit` ("Edit default layout") and `reset` ("Reset everyone to the default", with an inline confirm before it calls `resetEveryone()`);
    - body: "Users may customize: <role names>" and "Customized layouts: <n> user(s) have their own layout".
  - Every field, validation rule and password-rules tooltip from today's dialogs stays. `wirePasswordChecks` takes `root` = the child blade element.

- [ ] **Step 1: Update the failing tests.** Change the two `adminSections` tests to the new order. Add:

```js
test("adminSections orders General, Users, Roles, Default dashboard with groups", () => {
  assert.deepEqual(adminSections(createAuth({ is_admin: true })).map((s) => [s.id, s.group || ""]),
    [["general", ""], ["users", "Identity"], ["roles", "Identity"], ["dashboard", "Dashboard"]]);
});
test("sectionFromPath falls back to the first allowed section", () => {
  const s = adminSections(createAuth({ permissions: ["core.users"] }));
  assert.equal(sectionFromPath("/admin/general", s), "users");
  assert.equal(sectionFromPath("/admin/roles", s), "roles");
  assert.equal(sectionFromPath("/admin", s), "users");
});
```

- [ ] **Step 2: Run them and see them fail.** `npm test`.

- [ ] **Step 3: Implement.**
  - Before starting, check whether `fix/password-rule-tooltips` has merged into main: `git log main --oneline | grep -i tooltip`.
  - If it has, rebase this branch onto main first. Its `USERNAME_HINT` and the `checksTitle` tooltips must survive in the child blades.

- [ ] **Step 4: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: Admin on the blade layout, with Default dashboard`

---

### Task 7: Settings on the blade layout, with My dashboard and the plugin child blade

**Files:**
- Modify: `static/js/settings/dialog.js`, `settings/installed.js`, `settings/overlay.js` (it becomes the child blade's body builder; keep the file name or rename it to `plugin-blade.js` and update the imports), `settings/gallery.js` (where the card opens the overlay)
- Create: `static/js/settings/my-dashboard.js`
- Modify: `static/css/app.css` (remove the `.dlg-rail` and `.pov` rules)
- Test: `tests/js/nav.test.mjs` (`tabsFor` becomes `settingsMenu`), `tests/js/uninstall.test.mjs` and `tests/js/gallery.test.mjs` if they import overlay names

**Interfaces:**
- Consumes: Task 5's `createBlade`, with `crumbHost` = a `.blade-crumb` element placed under the dialog title. Task 6's `dashboard/api.js`.
- Produces:
  - `settingsMenu(list, available = 0, canInstall = true)` returns:

    ```js
    [{ group: "Personal", items: [{id: "appearance", label: "Appearance", icon}, {id: "dashboard", label: "My dashboard", icon}] },
     { group: "Plugins", items: [{id: "plugins:installed", label: "Installed", count: list.length, icon}, ...(canInstall ? [{id: "plugins:available", label: "Available", count: available, icon}] : [])] }]
    ```

    "My dashboard" is left out when the auth can't do `core.dashboard`.
  - `resolveTab` also accepts `"dashboard"`. All existing ids still resolve as before.
  - `openPluginBlade(blade, ctx, key, opener, { onClose })`. It's the old overlay content (name, version, status dot, enable switch, settings form, Save / Cancel / Uninstall, the pending-uninstall body) inside `blade.openChild`. It returns null when `key` isn't an installed plugin.
  - The Plugins group's collapsed state uses `storageKey: "netview.settings.pluginsOpen"`, so existing preferences carry over. Keep the meaning: "0" means collapsed.
  - **My dashboard** page:
    - head: title "My dashboard", subtitle "Your saved layout. Change it on the dashboard with Customize.";
    - command `reset` ("Reset to default"), which calls `resetLayout()` and is disabled unless `source === "user"`;
    - body: "Layout: Your own (saved <ago>)" or "The default", plus grouping and the hidden count.
  - The dialog keeps its title bar and close button. The side menu is `--surface` and the page is `--bg`, as in Admin.

- [ ] **Step 1: Update the failing tests**

```js
test("settingsMenu groups Personal and Plugins with counts", () => {
  const m = settingsMenu([{}, {}], 3, true);
  assert.deepEqual(m.map((g) => g.group), ["Personal", "Plugins"]);
  assert.deepEqual(m[1].items.map((i) => [i.id, i.count]), [["plugins:installed", 2], ["plugins:available", 3]]);
});
test("settingsMenu without install rights has no Available", () => { /* ... */ });
test("resolveTab knows dashboard and keeps plugin:<id>", () => {
  assert.deepEqual(resolveTab("dashboard"), { tab: "dashboard", overlay: null });
  assert.deepEqual(resolveTab("plugin:7"), { tab: "plugins:installed", overlay: "7" });
});
```

- [ ] **Step 2: Run them and see them fail.** `npm test`.

- [ ] **Step 3: Implement.** `openSettings("plugin:<id>")` from a disabled nav tab must still open Installed with that plugin's child blade.

- [ ] **Step 4: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: Settings on the blade layout, with My dashboard`

---

### Task 8: Dashboard layout model (pure)

**Files:**
- Create: `static/js/dashboard/layout.js`
- Test: `tests/js/dashboard-model.test.mjs`

**Interfaces:**
- An **Item** is `{ runtimeKey, layoutKey: string | null, kind: "tile"|"card", owner, groupPlugin, groupType, defaultSpan: "third"|"half"|"full" | null, fixed: boolean }`.
  - `fixed` is true for failed-plugin placeholders and for any item whose layout key fails `KEY_RE`.
  - Fixed items have `layoutKey: null`.
- Produces:
  - `KEY_RE = /^(core|[0-9a-f-]{36})\.(tile|card)\.[A-Za-z0-9_.-]{1,100}$/`, `SPAN_COLS = { third: 4, half: 6, full: 12 }`, `TILE_COLS = 2`
  - `TYPE_LABELS` (Global Constraints), `BUILTIN_PLUGIN_GROUP = "NetView"`, `BUILTIN_TYPE_GROUP = "NetView (built in)"`
  - `itemFromSpec(spec, kind) -> Item`:
    - the owner is `"core"` when `spec.pluginId === "core"`, otherwise `spec.pluginGuid`;
    - built-in means `pluginId === "core"` or `pluginSource === "builtin"`. Built-ins group as `BUILTIN_*`. Others group by `pluginDisplayName`, or by `TYPE_LABELS[pluginType] || "Other"`;
    - a spec with `id === "failed"` and no guid is fixed.
  - `emptyLayout() -> {version: 1, order: [], hidden: [], spans: {}, group: "none"}`
  - `applyLayout(items, layout) -> { visible: Item[], hidden: Item[] }`:
    1. ordered keys first, in `layout.order`;
    2. then non-fixed items not in `order`, in the order of `items`;
    3. fixed items last;
    4. hidden keys are taken out of `visible`, and only items that exist appear in `hidden`.
  - `spanOf(item, layout) -> cols`. Tiles are 2. Cards use `layout.spans[key] || item.defaultSpan || "half"`.
  - `groupItems(visible, group) -> [{ name, items }]`:
    - `group` "none" gives one group with name `""`;
    - otherwise the built-in group comes first, then the others by `localeCompare`;
    - fixed items stay in their plugin's group and sort last within it.
  - `moveKey(order, key, targetKey, after) -> string[]`
  - `nudge(order, key, delta, groupKeys) -> string[]`. Moves one place within `groupKeys`, and stops at the ends.
  - `nextSpan(span) -> span`: third → half → full → third.
  - `dropSpot(rects, x, y) -> { key, after } | null`:
    - `rects` is `[{key, left, top, right, bottom}]`, excluding the dragged item;
    - inside a rect: `after` is `x > left + width / 2`;
    - otherwise, take the rects whose `top - 6 <= y <= bottom + 6`. Return the first of them with `left > x` (before it), or else the last of them (after it);
    - if no rect is in the row, return the last rect (after it). With no rects, return `null`.
  - `toSaved(items, layout) -> layout`:
    - `order` is every non-fixed present key, in the current display order;
    - `hidden` and `spans` are kept for present keys only;
    - `group` is kept.
  - `sameLayout(a, b) -> boolean`, comparing the normalized records.
  - `saveAction({ editingDefault, resetPressed, edited }) -> "put" | "delete" | "default"`:
    - "default" when `editingDefault`;
    - "delete" when `resetPressed && !edited`;
    - otherwise "put".

- [ ] **Step 1: Write the failing tests.** Include Review Focus 1, 2 and 5:

```js
test("applyLayout: saved order first, new items after, fixed last, unknown keys ignored", () => { /* ... */ });
test("a hidden key for a missing item makes no tray entry and is dropped by toSaved", () => { /* Review Focus 5 */ });
test("an item whose id fails KEY_RE is fixed, shown last and never saved", () => {   // Review Focus 1
  const it = itemFromSpec({ pluginId: "7", pluginGuid: "c66a564b-0254-44cf-bb74-1c7f6ebae6be", id: "my card", pluginSource: "folder" }, "card");
  assert.equal(it.fixed, true); assert.equal(it.layoutKey, null);
});
test("the failed-plugin placeholder is fixed", () => { /* {pluginId:"9", id:"failed"} with no guid */ });   // Review Focus 2
test("built-in plugins group under NetView; installed ones by name or type label", () => { /* source builtin vs folder; type "switch" -> "Switch"; missing -> "Other" */ });
test("groupItems puts the built-in group first, then alphabetical", () => { /* ... */ });
test("dropSpot: halves of a card, the gap mid-row, and the empty end of a row", () => {
  const r = [{ key: "a", left: 0, top: 0, right: 100, bottom: 50 }, { key: "b", left: 120, top: 0, right: 220, bottom: 50 }, { key: "c", left: 0, top: 70, right: 100, bottom: 120 }];
  assert.deepEqual(dropSpot(r, 30, 25), { key: "a", after: false });
  assert.deepEqual(dropSpot(r, 80, 25), { key: "a", after: true });
  assert.deepEqual(dropSpot(r, 110, 25), { key: "b", after: false });
  assert.deepEqual(dropSpot(r, 400, 25), { key: "b", after: true });   // the owner's case: after the last card in the row
  assert.deepEqual(dropSpot(r, 400, 95), { key: "c", after: true });
  assert.equal(dropSpot([], 1, 1), null);
});
test("moveKey, nudge and nextSpan", () => { /* ... */ });
test("saveAction: reset then save with no edits deletes", () => {
  assert.equal(saveAction({ editingDefault: false, resetPressed: true, edited: false }), "delete");
  assert.equal(saveAction({ editingDefault: false, resetPressed: true, edited: true }), "put");
  assert.equal(saveAction({ editingDefault: true, resetPressed: false, edited: true }), "default");
});
```

- [ ] **Step 2: Run them and see them fail.** `npm test`.

- [ ] **Step 3: Implement `layout.js`.** It has no DOM access.

- [ ] **Step 4: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: dashboard layout model`

---

### Task 9: The persistent 12-column grid and view mode

**Files:**
- Create: `static/js/dashboard/grid.js`
- Modify: `static/js/pages/dashboard.js` (keep `coreTiles`, `coreCardSpecs`, `orderCards`, `orderTiles` and `requestDefaultEdit`; move or delete `createCardGrid`, `spanClass` and `cardKey`), `static/css/app.css` (replace `.tiles`, `.cards` and `.span-*` with `.dash-*`)
- Test: `tests/js/dashboard-layout.test.mjs` (port the `createCardGrid` tests to `createDashboardGrid`, keeping the same fake DOM, and extend it with `insertBefore`, `classList` and `hidden` as needed)

**Interfaces:**
- Consumes: everything from Task 8; `getLayout()` from Task 6's `dashboard/api.js`; `spec.pluginType` and `spec.pluginSource` from Task 4.
- Produces:
  - `createDashboardGrid(doc, container)` returns `{ nodes: Map<runtimeKey, {el, body, error, item}>, update(entries, state, view) }`:
    - `entries` is `[{ item, spec }]`;
    - `view` is `{ groups: [{name, items}], editing: boolean }`.
    - Each runtime key gets **one** element for its whole life:
      - a tile is `<div class="tile dash-item">` whose inner HTML is the spec's render output. An empty render hides the element (`hidden = true`), and it keeps its slot;
      - a card is the existing `<section class="card dash-item">` with its persistent body.
    - Each group name gets one persistent `<section class="dash-group">`, with a `.dash-group-head` (chevron, name, count; a click toggles `collapsed`) and a `.dash-grid` inside. The head is left out when the name is `""`.
    - Nodes are put in place with `appendChild` or `insertBefore` only when their position or parent changes, so an `update` that changes nothing does no DOM writes.
    - Each item element gets the class `col-<n>` from `spanOf` and `data-layout-key`.
    - Fixed items get `data-fixed`.
    - Render and draw errors are caught per item, as `createCardGrid` does today.
  - `mountDashboard(el, ctx)`:
    - builds the entries from `coreTiles`, the `dashboard.tile` slot, `coreCardSpecs`, the `dashboard.card` slot and the failed specs, in today's default order;
    - fetches `getLayout()` once on mount. On failure, or when `layout` is null, it uses `emptyLayout()`, which gives the built-in default;
    - renders through the grid;
    - returns `{ update, destroy }`;
    - group collapse state lives in `localStorage` key `netview.dashboard.collapsed`.
  - CSS:
    - `.dash-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 12px; }`, with `.col-2 / .col-4 / .col-6 / .col-12` spans;
    - at `max-width: 900px`, tiles are `col-6` and cards `col-12` (builder's call).

- [ ] **Step 1: Write the failing tests**

```js
test("nodes are created once and survive regrouping and edit toggles", () => {  // anti-goal: live state
  const g = createDashboardGrid(doc, root); g.update(entries, state, viewNone);
  const before = [...g.nodes.values()].map((n) => n.el);
  g.update(entries, state, viewByPlugin); g.update(entries, state, { ...viewByPlugin, editing: true });
  assert.deepEqual([...g.nodes.values()].map((n) => n.el), before);
});
test("a tile whose render returns empty is hidden but keeps its slot", () => { /* Review Focus 3 */ });
test("a fixed (failed) card is rendered last and marked data-fixed", () => { /* Review Focus 2 */ });
test("an unchanged update does not move any node", () => { /* count appendChild/insertBefore calls on the fake DOM */ });
test("col classes follow spanOf", () => { /* tile col-2; card with spans[key] = "full" -> col-12 */ });
```

Also port the existing three `createCardGrid` tests (draw error isolation, persistence, recovery and removal) to the new grid.

- [ ] **Step 2: Run them and see them fail.** `npm test`.

- [ ] **Step 3: Implement the grid, the mount and the CSS.** Plugin-facing slot specs don't change.

- [ ] **Step 4: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: dashboard on a persistent 12-column grid with saved layouts`

---

### Task 10: Customize mode

**Files:**
- Create: `static/js/dashboard/customize.js`
- Modify: `static/js/pages/dashboard.js`, `static/js/icons.js` (`grip`, `eyeOff`, `eye`, `arrowsHorizontal`, `info`), `static/css/app.css` (`.dash-toolbar`, `.dash-banner`, `.dash-editing`, `.dash-tools`, `.dash-before`, `.dash-after`, `.dash-tray`)
- Test: `tests/js/dashboard-customize.test.mjs`

**Interfaces:**
- Consumes: Task 8's model and Task 9's grid. Task 6's `saveLayout`, `resetLayout`, `saveDefault` and `requestDefaultEdit`. `ctx.auth.can("core.dashboard")` and `ctx.auth.can("core.system")`.
- Produces:
  - `createCustomizer({ getItems, getLayout, setLayout, redraw, auth, api, toast })` returns `{ start({ editingDefault }), cancel(), save(), saveDefault(), reset(), hide(key), show(key), widen(key), move(key, targetKey, after), nudge(key, delta), editing, editingDefault }`.
  - It keeps a `backup` of the layout plus the flags `resetPressed` and `edited`. Every change except `reset()` sets `edited = true`.
  - `toolbarHtml({ editing, editingDefault, canCustomize, canDefault }) -> string`. A pure function:
    - not editing: one right-aligned `data-act="customize"` button, or `""` without `core.dashboard`;
    - editing, personal: a Group by `<select data-act="group">` (options None / Plugin / Plugin type, values `none`, `plugin`, `plugin_type`), then `save` (primary), `default` (only when `canDefault`), `reset` and `cancel`;
    - editing the default: Group by, `default` (primary), and `cancel`.
  - `bannerText(editingDefault) -> string`, returning the exact copy from the Global Constraints.
- Behaviour:
  - Save follows `saveAction`:
    - "put" calls `saveLayout(toSaved(...))`;
    - "delete" calls `resetLayout()`;
    - "default" calls `saveDefault(toSaved(...), clearMine)`, where `clearMine` is `!editingDefault`.
    - Each shows its toast, then leaves edit mode.
  - Cancel restores `backup` and shows "Changes discarded".
  - Reset loads `default` from the last `getLayout()` response, or `emptyLayout()` when that is null. Its grouping comes with it. It sets `resetPressed = true` and `edited = false`.
  - In edit mode each non-fixed item gets `.dash-tools`:
    - width (cards only), cycling with `nextSpan`;
    - hide.
    - It also gets `draggable="true"` and `tabindex="0"`.
  - The Hidden cards tray lists `applyLayout(...).hidden`. Clicking a chip shows that item.
  - Drag and drop uses HTML5 events on items and on each `.dash-grid`. The position comes from `dropSpot` over the rects of the same group's items, with the dragged one left out. The drop target shows `.dash-before` or `.dash-after`.
    - With a grouping, a drag over another group is refused: no `preventDefault`. The first refused dragover per drag shows the toast "Cards stay in their own group".
  - Keyboard: Ctrl+ArrowLeft and Ctrl+ArrowRight on a focused item call `nudge`. An `aria-live="polite"` region says "Moved <title> to position <n> of <m>".
  - `requestDefaultEdit()` makes the next mount start with `{ editingDefault: true }`, but only when `auth.can("core.system")`.
  - Leaving the page (`destroy`) while editing just discards the changes.

- [ ] **Step 1: Write the failing tests.** Use a stub `api` that records calls, and plain objects for the items:

```js
test("toolbarHtml: viewer sees nothing, customizer sees Customize, editing shows Group by and saves", () => { /* ... */ });
test("default editing shows only Group by, Save as default and Cancel", () => { /* ... */ });
test("save after reset with no edits calls resetLayout, not saveLayout", async () => { /* ... */ });
test("save as default from personal editing passes clearMine true; from default editing false", async () => { /* ... */ });
test("cancel restores the layout from before editing", () => { /* ... */ });
test("hide, show and widen mark the layout edited and change hidden/spans", () => { /* ... */ });
test("bannerText copy is exact", () => {
  assert.equal(bannerText(false), "Drag cards to move them. Changes are only yours, and only kept when you save.");
  assert.equal(bannerText(true), "Editing the default layout for everyone. Users who saved their own layout keep it until they reset.");
});
```

- [ ] **Step 2: Run them and see them fail.** `npm test`.

- [ ] **Step 3: Implement**, and wire it into `mountDashboard`.

- [ ] **Step 4: Run the tests and all gates.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: Customize mode (drag, width, hide, group, save)`

---

### Task 11: Check it end to end in the browser

**Files:** none, unless a fix is needed. If one is, it goes in the file that owns the behaviour and gets a test there first.

- [ ] **Step 1:** Copy `R:\source\claude projects\HomeLab\network\netview-dev` to a scratch folder. Add a `.claude/launch.json` entry `netview-ui-check` that serves this worktree against the copy on port 8775. Start it with the preview tools.
  - The copy goes through migration 0007 at start-up. Confirm `user_dashboard_layouts` exists.
- [ ] **Step 2:** Sign in as the copy's admin, then walk through each area.
  - Top bar and account menu:
    - the top bar has no "This device" text and no Admin tab;
    - the account menu has Admin and Settings.
  - Admin:
    - it opens on General;
    - the Users edit child blade slides in, the breadcrumb reads `Admin › Users › Edit <name>`, and Esc closes it;
    - Back goes back through the sections.
  - Settings:
    - same layout and colours as Admin;
    - My dashboard shows "The default";
    - an installed plugin opens a child blade with Save and Uninstall;
    - `openSettings("plugin:<id>")` from a disabled tab still works.
  - Dashboard:
    - Customize → drag a tile into the empty end of a row; it lands last in that row;
    - widen a card; hide one and bring it back from the tray;
    - Group by Plugin type shows NetView (built in) first;
    - Save, reload, and the layout is kept;
    - Settings › My dashboard › Reset to default goes back.
  - Default layout:
    - Admin › Default dashboard › Edit default layout opens default editing with the right banner;
    - save, then check as a second user with only `core.view`, created on the copy, that they see it with no Customize button.
  - Themes: switch through every built-in theme and check the blades and the dashboard look right.
- [ ] **Step 3:** Run all gates one last time. Stop the server. Leave the `launch.json` entry in place.
- [ ] **Step 4: Commit** any fixes, as `fix: <what>`.
