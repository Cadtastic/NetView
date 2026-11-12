# NetView Auth Stage 1 (core sign-in, roles, permissions, Admin page) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every NetView request is made by a signed-in user whose roles grant permissions. This stage adds local accounts, first-run setup, sessions, core and plugin permission guards, SDK 1.5 permission hooks, the `users` CLI, and the Admin page's Users, Roles and General sections.

**Architecture:** The domain holds the user, role and permission rules. The application layer holds the use cases, an `AuthStore` port (its own unit of work, separate from the network `UnitOfWork`), the permission catalog, and a context variable carrying the current `Principal`. Infrastructure adds SQLAlchemy tables (core migration `0004`) and an Argon2 hasher. Presentation adds a pure-ASGI `AuthMiddleware` (who is this; sign-in, setup and static gating) and a FastAPI dependency `require_permission(id)` (what may they do). Plugin routers get a default router-level guard at mount time, which a route can override with an explicit `ctx.require(...)`.

**Tech Stack:** Python ≥3.11, FastAPI, Starlette, SQLAlchemy 2, Alembic, Typer, pydantic, `argon2-cffi` (new dependency), plain ES modules with `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-12-netview-auth-admin-design.md` ("the spec"). Stage 1 = spec §14 delivery item 1. HTTPS/allowlist/public address (stage 2), outside providers (stage 3) and the audit plugin plus existing-plugin updates (stage 4) get their own plans later. Where this plan says "§n" it means the spec.

## Global Constraints

- Layers and import-linter contracts in `pyproject.toml` must keep passing: the domain imports nothing from NetView or third parties; the application layer imports no `fastapi`/`starlette`/`sqlalchemy`; presentation imports no infrastructure; plugins import only `netview.sdk`.
- Keep the `X-Netview: 1` rule on non-GET requests, the Host check and the CSP (no inline scripts or inline event handlers in new pages).
- `SDK_VERSION = "1.5"`. Plugins declaring `sdk_version` ranges like `>=1.3,<2` must still load.
- Built-in role IDs: `administrator` (name "Administrator") and `default` (name "Default"). Default starts with exactly `core.view`.
- Core permission IDs and labels, verbatim from §6.1: `core.view` "View devices and dashboard", `core.rename` "Rename devices", `core.forget` "Forget devices", `core.watches` "Manage watches", `core.scan` "Run scans and probes", `core.plugins` "Turn plugins on or off", `core.users` "Manage users and roles", `core.system` "Manage sign-in, HTTPS and general settings". Locked row `core.install` "Install plugins", locked reason "Administrator only: installing runs downloaded code".
- Automatic plugin permissions: `<id>.view` "View <Plugin name>", `<id>.use` "Use <Plugin name>", `<id>.configure` "Change <Plugin name> settings" (§6.2).
- Policy defaults (§7.2, §7.5, §12; all admin-configurable): password minimum length 12 (floor 8); session idle 8 h, absolute 7 days; lockout after 5 failures within 15 min, locked for 15 min.
- Setup code: 8 characters from the alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`.
- Session cookie: name `netview_session`, `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when the request scheme is `https`. Store only the SHA-256 hex of the token. Token = `secrets.token_urlsafe(32)`.
- Generic sign-in error copy: "Username or password is wrong". Lockout copy: "Too many attempts. Try again later." Setup-required API body: `{"error": "setup required"}` with status 409.
- Usernames are stored stripped and lower-cased; uniqueness is case-insensitive *(plan call)*.
- `mode` setting values `"enterprise"` (default) and `"home"`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit with the repo's existing no-reply `user.email`; never change it.
- Run the full gate before each commit: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports`, and `npm test` when JS changed.

## Review Focus

1. **Guard bypass on plugin routes.** `HEAD`/`OPTIONS`, a trailing slash, `%2F` in a path, and `/plugins/<id>/static/../` must all still get the `<id>.view`/`<id>.use` check or a 401/403/404. Never a 200 with data. Owner: Task 9.
2. **A user changed mid-session.** Disabled, deleted, or roles edited while signed in: the next request reflects it immediately, and an open `/api/v1/stream` closes at the next keep-alive. Owner: Tasks 4 and 8.
3. **Two setup requests at once.** Exactly one admin is created; the other request gets 409. Owner: Task 5 (store-level atomicity) and Task 8 (API).
4. **Username case and spaces.** `" Admin "` and `admin` are the same user, for sign-in, uniqueness and lockout. Owner: Tasks 1 and 4.
5. **Open redirect through `next`.** `//evil.example`, `https://evil.example`, `/\evil.example` and `javascript:` all fall back to `/`. Owner: Task 11 (`safeNext`, used by both pages).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/netview/domain/auth.py` | `User`, `Role`, `PermissionSet`, `AuthPolicy`, `normalize_username`, `check_password`, built-in role constants |
| `src/netview/domain/errors.py` (modify) | add `AuthenticationError`, `PermissionDeniedError`, `SetupRequiredError`, `TooManyAttemptsError` |
| `src/netview/application/plugins/user_permissions.py` | `UserPermission` (SDK type) |
| `src/netview/application/auth/catalog.py` | core permission list, automatic plugin permissions, `build_catalog`, `validate_declared`, `default_permission_for` |
| `src/netview/application/auth/principal.py` | `Principal`, `SYSTEM_PRINCIPAL`, the `current_principal` context variable |
| `src/netview/application/ports/auth_store.py` | `AuthStore`/`AuthUnitOfWork` and repository protocols, `SessionRecord` |
| `src/netview/application/ports/password_hasher.py` | `PasswordHasher` protocol |
| `src/netview/application/usecases/auth/sessions.py` | `SessionService`, `Authorizer` |
| `src/netview/application/usecases/auth/sign_in.py` | `LoginThrottle`, `SignIn`, `ChangeOwnPassword` |
| `src/netview/application/usecases/auth/setup.py` | `SetupService`, `make_setup_code` |
| `src/netview/application/usecases/auth/admin.py` | `UserAdmin`, `RoleAdmin`, `PolicyAdmin` |
| `src/netview/application/services.py` (modify) | add `AuthServices` and an `auth` field |
| `src/netview/infrastructure/auth/memory_store.py` | `InMemoryAuthStore` (used by tests and as the contract reference) |
| `src/netview/infrastructure/auth/sql_store.py` | `SqlAuthStore` |
| `src/netview/infrastructure/auth/argon2_hasher.py` | `Argon2Hasher` |
| `src/netview/infrastructure/db/models.py` (modify) | auth rows |
| `src/netview/infrastructure/db/core_versions/0004_auth.py` | tables and built-in role seed |
| `src/netview/presentation/api/auth_middleware.py` | `AuthMiddleware` |
| `src/netview/presentation/api/permissions.py` | `require_permission`, `plugin_default_guard`, `explicit_permission` marker |
| `src/netview/presentation/api/routers/auth.py`, `setup.py`, `admin.py` | new endpoints |
| `src/netview/presentation/api/schemas.py`, `errors.py`, `app.py`, routers (modify) | guards, filtering, error mapping, mounting |
| `src/netview/infrastructure/plugins/host.py`, `context.py` (modify) | read declared permissions, fill `PluginInfo`, `ctx.require`, `ctx.principal` |
| `src/netview/application/plugins/base.py`, `context.py`, `manifest.py`, `src/netview/sdk/__init__.py` (modify) | SDK 1.5 surface |
| `src/netview/bootstrap.py`, `infrastructure/settings.py`, `presentation/cli.py` (modify) | wiring, `mode`, setup-code print, `users` commands |
| `src/netview/presentation/web/static/login.html`, `setup.html`, `js/auth/*.js` | sign-in and setup pages |
| `src/netview/presentation/web/static/js/auth.js` | `createAuth(me)`, `safeNext`, account menu |
| `src/netview/presentation/web/static/js/pages/admin/*.js` | Admin page and its sections |
| `docs/plugin-permissions.md` | plugin developer guide for user permissions |

---

### Task 1: Domain rules for users, roles and passwords

**Files:**
- Create: `src/netview/domain/auth.py`
- Modify: `src/netview/domain/errors.py`
- Test: `tests/unit/domain/test_auth.py`

**Interfaces:**
- Produces:
  - `ADMIN_ROLE = "administrator"`, `DEFAULT_ROLE = "default"`, `BUILTIN_ROLES = frozenset({ADMIN_ROLE, DEFAULT_ROLE})`
  - `@dataclass(frozen=True) class Role: id: str; name: str; builtin: bool; permissions: frozenset[str]`
  - `@dataclass(frozen=True) class User: id: int; username: str; display_name: str; email: str | None; enabled: bool; builtin: bool; must_change_password: bool; role_ids: frozenset[str]; provider: str; created_ms: int; last_sign_in_ms: int | None`. `provider` is `"local"` in this stage.
  - `@dataclass(frozen=True) class PermissionSet: everything: bool; ids: frozenset[str]` with `has(permission_id: str) -> bool`, `as_list(catalog_ids: Iterable[str]) -> list[str]` (all catalog IDs when `everything`).
  - `resolve_permissions(roles: Iterable[Role]) -> PermissionSet`: Administrator gives `everything=True`.
  - `normalize_username(raw: str) -> str` (strip, lower-case; raises `ValidationError` when empty or longer than 128 characters or containing whitespace inside).
  - `@dataclass(frozen=True) class AuthPolicy` with the defaults from Global Constraints as fields `password_min_length: int = 12`, `session_idle_s: int = 28800`, `session_max_s: int = 604800`, `lockout_failures: int = 5`, `lockout_window_s: int = 900`, `lockout_s: int = 900`, and `validate() -> None` (raises `ValidationError` with `fields` naming each bad field; floor 8 for the length; every other value ≥ 1).
  - `check_password(password: str, username: str, min_length: int) -> None` raises `ValidationError(fields={"password": ...})`.
  - Errors: `AuthenticationError(NetviewError)`, `PermissionDeniedError(NetviewError)`, `SetupRequiredError(NetviewError)` (default message "setup required"), `TooManyAttemptsError(NetviewError)` (default message "Too many attempts. Try again later.").

- [ ] **Step 1: Write the failing tests**

```python
def test_administrator_gets_everything():
    ps = resolve_permissions([Role(ADMIN_ROLE, "Administrator", True, frozenset())])
    assert ps.everything and ps.has("anything.at_all")

def test_permissions_add_up_across_roles():
    ps = resolve_permissions([Role("a", "A", False, frozenset({"core.view"})),
                              Role("b", "B", False, frozenset({"gsm7248.console"}))])
    assert ps.has("core.view") and ps.has("gsm7248.console") and not ps.has("core.users")

def test_no_roles_means_no_permissions():
    assert not resolve_permissions([]).has("core.view")

@pytest.mark.parametrize("raw", [" Admin ", "ADMIN", "admin"])
def test_usernames_normalize(raw):
    assert normalize_username(raw) == "admin"

@pytest.mark.parametrize("raw", ["", "   ", "a b", "x" * 129])
def test_bad_usernames_rejected(raw):
    with pytest.raises(ValidationError):
        normalize_username(raw)

def test_password_rules():
    check_password("correct horse battery", "admin", 12)
    for bad in ("short", "admin"):
        with pytest.raises(ValidationError):
            check_password(bad, "admin", 12)
    with pytest.raises(ValidationError):
        check_password("adminadminadmin", "adminadminadmin", 12)

def test_policy_defaults_and_floor():
    p = AuthPolicy()
    assert (p.password_min_length, p.session_idle_s, p.session_max_s) == (12, 28800, 604800)
    assert (p.lockout_failures, p.lockout_window_s, p.lockout_s) == (5, 900, 900)
    with pytest.raises(ValidationError) as e:
        AuthPolicy(password_min_length=7).validate()
    assert "password_min_length" in e.value.fields
```

- [ ] **Step 2: Run them and see them fail.** Run: `uv run pytest tests/unit/domain/test_auth.py -q`. Expected: ImportError.
- [ ] **Step 3: Implement `src/netview/domain/auth.py` and the four errors** as specified in Interfaces. Use the stdlib only.
- [ ] **Step 4: Run the tests.** Expected: PASS. Then run the full gate (Global Constraints).
- [ ] **Step 5: Commit** `feat(auth): domain rules for users, roles, permissions and passwords`.

---

### Task 2: Permission catalog and the SDK `UserPermission` type

**Files:**
- Create: `src/netview/application/plugins/user_permissions.py`, `src/netview/application/auth/__init__.py`, `src/netview/application/auth/catalog.py`
- Modify: `src/netview/application/ports/plugin_admin.py` (add a `PluginInfo` field)
- Test: `tests/unit/application/test_permission_catalog.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class UserPermission: id: str; label: str; description: str = ""; dangerous: bool = False`
  - `PluginInfo.user_permissions: list[UserPermission] = field(default_factory=list)` (the plugin's declared list, unprefixed)
  - `@dataclass(frozen=True) class PermissionInfo: id: str; label: str; description: str; dangerous: bool = False; locked: str | None = None`
  - `@dataclass(frozen=True) class PermissionGroup: owner: str; title: str; off: bool; permissions: tuple[PermissionInfo, ...]`. `owner` is `"core"` or the plugin ID. `off` is true when the plugin is not enabled.
  - `CORE_GROUP: PermissionGroup` with the 8 core permissions plus the locked `core.install` row (Global Constraints, verbatim).
  - `ADMIN_ONLY: frozenset[str] = frozenset({"core.install"})`
  - `AUTOMATIC = ("view", "use", "configure")`
  - `automatic_permissions(info: PluginInfo) -> list[PermissionInfo]`: `view` when `"api"` or `"web_ui"` is in `info.capabilities`; `use` when `"api"` is; `configure` when `info.settings_schema is not None`.
  - `validate_declared(plugin_id: str, declared: Sequence[UserPermission], automatic_ids: set[str]) -> list[str]`: error messages for a bad ID (regex `^[a-z0-9_.-]+$`), duplicates, and an automatic ID (`view`/`use`/`configure`) that the plugin does not have, which is the "may not declare" case.
  - `plugin_group(info: PluginInfo) -> PermissionGroup`: the automatic permissions first, with any declared entry whose ID matches an automatic one replacing its label and description (a relabel), then the other declared entries prefixed `<plugin_id>.`.
  - `build_catalog(plugins: Sequence[PluginInfo]) -> list[PermissionGroup]`: `CORE_GROUP` first, then one group per plugin whose `state` is `"active"`, `"disabled"` or `"failed"` (not `"pending"`), sorted by name. Plugins with no permissions are left out.
  - `catalog_ids(groups) -> set[str]`, which leaves out locked rows.
  - `default_permission_for(plugin_id: str, method: str) -> str`: `<id>.view` for `GET`/`HEAD`/`OPTIONS`, otherwise `<id>.use`.

- [ ] **Step 1: Write the failing tests**

```python
def info(pid="gsm7248", caps=("api", "web_ui"), schema={"type": "object"}, declared=(), state="active"):
    return PluginInfo(pid, "NETGEAR GSM7248", "0.1", "", state, capabilities=list(caps),
                      settings_schema=schema, user_permissions=list(declared))

def test_core_group_first_and_verbatim_labels():
    g = build_catalog([])[0]
    assert g.owner == "core"
    assert [p.id for p in g.permissions][:8] == ["core.view", "core.rename", "core.forget", "core.watches",
                                                  "core.scan", "core.plugins", "core.users", "core.system"]
    install = next(p for p in g.permissions if p.id == "core.install")
    assert install.locked == "Administrator only: installing runs downloaded code"

def test_automatic_permissions_follow_manifest_and_settings():
    ids = [p.id for p in plugin_group(info()).permissions]
    assert ids == ["gsm7248.view", "gsm7248.use", "gsm7248.configure"]
    assert [p.id for p in plugin_group(info(caps=("web_ui",), schema=None)).permissions] == ["gsm7248.view"]
    assert plugin_group(info()).permissions[0].label == "View NETGEAR GSM7248"

def test_declared_are_prefixed_and_relabel_allowed():
    g = plugin_group(info(declared=[UserPermission("console", "Open serial console", "Full CLI", True),
                                    UserPermission("view", "View the switch")]))
    assert g.permissions[0].label == "View the switch"
    assert g.permissions[-1].id == "gsm7248.console" and g.permissions[-1].dangerous

def test_validate_declared():
    assert validate_declared("p", [UserPermission("Bad Id", "x")], {"view"})
    assert validate_declared("p", [UserPermission("a", "x"), UserPermission("a", "y")], {"view"})
    assert validate_declared("p", [UserPermission("use", "x")], {"view"})   # no api → no automatic use
    assert validate_declared("p", [UserPermission("view", "x")], {"view"}) == []

def test_disabled_shown_off_pending_hidden():
    groups = build_catalog([info("a", state="disabled"), info("b", state="pending")])
    assert [(g.owner, g.off) for g in groups[1:]] == [("a", True)]

@pytest.mark.parametrize("m,suffix", [("GET", "view"), ("HEAD", "view"), ("OPTIONS", "view"),
                                      ("POST", "use"), ("DELETE", "use"), ("PATCH", "use")])
def test_default_permission_for(m, suffix):
    assert default_permission_for("roku", m) == f"roku.{suffix}"
```

- [ ] **Step 2: Run and see it fail.** `uv run pytest tests/unit/application/test_permission_catalog.py -q`.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run tests and the full gate.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(auth): permission catalog with automatic plugin permissions`.

---

### Task 3: Auth store port, principal, and the in-memory store

**Files:**
- Create: `src/netview/application/ports/auth_store.py`, `src/netview/application/ports/password_hasher.py`, `src/netview/application/auth/principal.py`, `src/netview/infrastructure/auth/__init__.py`, `src/netview/infrastructure/auth/memory_store.py`
- Test: `tests/contract/auth_store_contract.py` (shared assertions), `tests/unit/infrastructure/test_memory_auth_store.py`

**Interfaces:**
- Produces (application/ports/auth_store.py):
  - `@dataclass(frozen=True) class SessionRecord: token_hash: str; user_id: int; created_ms: int; last_seen_ms: int; ip: str; user_agent: str`
  - `class UserRepository(Protocol)`:
    - `get(user_id: int) -> User | None`
    - `by_username(username: str) -> User | None`
    - `list() -> list[User]`
    - `count() -> int`
    - `add(user: User, password_hash: str | None) -> User` (assigns the `id`; raises `ConflictError` on a duplicate username)
    - `save(user: User) -> None`
    - `remove(user_id: int) -> None`
    - `password_hash(user_id: int) -> str | None`
    - `set_password_hash(user_id: int, hash: str) -> None`
  - `class RoleRepository(Protocol)`:
    - `get(role_id: str) -> Role | None`
    - `list() -> list[Role]`
    - `add(role: Role) -> None`
    - `save(role: Role) -> None`
    - `remove(role_id: str) -> None` (also removes it from every user)
  - `class SessionRepository(Protocol)`:
    - `add(s: SessionRecord) -> None`
    - `get(token_hash: str) -> SessionRecord | None`
    - `touch(token_hash: str, now_ms: int) -> None`
    - `remove(token_hash: str) -> None`
    - `remove_for_user(user_id: int) -> int`
  - `class SettingsRepository(Protocol)`:
    - `get(key: str) -> str | None`
    - `set(key: str, value: str) -> None`
  - `class AuthUnitOfWork(Protocol)`: `users`, `roles`, `sessions`, `settings`, `commit()`, a context manager that rolls back unless committed.
  - `AuthStore = Callable[[], AuthUnitOfWork]`
  - `class PasswordHasher(Protocol)`:
    - `hash(password: str) -> str`
    - `verify(hash: str, password: str) -> bool`
    - `needs_rehash(hash: str) -> bool`
  - `principal.py`:
    - `@dataclass(frozen=True) class Principal: user_id: int | None; username: str; display_name: str; provider: str; permissions: PermissionSet; must_change_password: bool = False`, with `can(permission_id: str) -> bool`
    - `SYSTEM_PRINCIPAL` (`user_id=None`, username `"system"`, everything)
    - `current_principal: ContextVar[Principal | None]` (default `None`)
    - `get_principal() -> Principal | None`
- Produces (infrastructure): `class InMemoryAuthStore` callable returning a unit of work that copies on enter and writes back on commit, like `InMemoryUnitOfWorkFactory` in `sdk/testing/fakes.py`. It seeds the two built-in roles on construction: Administrator with no stored permissions, Default with `{"core.view"}`. The `add` of a user inside a unit of work whose `users.count()` changed since enter must raise `ConflictError` when the caller asked for `only_if_empty=True`. So `UserRepository.add` gains the keyword `only_if_empty: bool = False`, which is the setup-race guard (Review Focus 3).

- [ ] **Step 1: Write the contract** `tests/contract/auth_store_contract.py` as plain functions taking a store factory, with an `__init__.py` and a `conftest.py` that parametrizes over factories (Task 7 adds the SQL one). Assertions:
  - built-in roles exist after creation, and Default holds `{"core.view"}`;
  - `add`, then `by_username("ADMIN".lower())` round-trips;
  - a duplicate username raises `ConflictError`;
  - `roles.remove("helpdesk")` strips it from users;
  - `sessions.remove_for_user` returns its count;
  - nothing persists without `commit()`;
  - `add(..., only_if_empty=True)` raises `ConflictError` when a user already exists.
- [ ] **Step 2: Run** `uv run pytest tests/contract -q`. Expected: fail on import.
- [ ] **Step 3: Implement** the ports, the principal module and `InMemoryAuthStore`.
- [ ] **Step 4: Run the contract and the full gate.** Expected: PASS. (`lint-imports` proves the application layer stays framework-free.)
- [ ] **Step 5: Commit** `feat(auth): auth store port, principal context and in-memory store`.

---

### Task 4: Sessions, permission resolution and password sign-in

**Files:**
- Create: `src/netview/application/usecases/auth/__init__.py`, `sessions.py`, `sign_in.py`
- Test: `tests/unit/application/test_auth_sessions.py`, `tests/unit/application/test_sign_in.py`

**Interfaces:**
- Consumes: Tasks 1–3. `Clock` from `application/ports/clock.py` (`now_ms()`).
- Produces:
  - `class Authorizer(store: AuthStore)`:
    - `permissions(user: User) -> PermissionSet`, cached per user ID
    - `invalidate() -> None`
  - `class SessionService(store: AuthStore, clock: Clock, authorizer: Authorizer, policy: Callable[[], AuthPolicy])`:
    - `create(user_id: int, ip: str, user_agent: str) -> str`: returns the raw token and stores its SHA-256.
    - `resolve(token: str) -> Principal | None`: `None` when the token is unknown, past the idle or absolute limit (the record is then deleted), or the user is missing or disabled. Otherwise it touches `last_seen_ms` and returns the principal.
    - `end(token: str) -> None`
    - `end_all(user_id: int) -> None`
  - `class LoginThrottle(clock: Clock, policy: Callable[[], AuthPolicy])`, in memory and keyed by `(normalized username, ip)`:
    - `check(username: str, ip: str) -> None`: raises `TooManyAttemptsError` while locked.
    - `failed(username: str, ip: str) -> None`
    - `succeeded(username: str, ip: str) -> None`
  - `@dataclass(frozen=True) class SignInResult: token: str; principal: Principal`
  - `class SignIn(store, hasher: PasswordHasher, sessions: SessionService, throttle: LoginThrottle, clock: Clock)`: `__call__(username: str, password: str, ip: str, user_agent: str) -> SignInResult`.
    - Unknown user, wrong password, a disabled user and a non-local user all raise `AuthenticationError("Username or password is wrong")`.
    - It verifies against a dummy hash when the user is unknown, so timing stays similar.
    - It rehashes when `needs_rehash`, and sets `last_sign_in_ms`.
  - `class ChangeOwnPassword(store, hasher, sessions, policy, clock)`: `__call__(principal: Principal, current: str, new: str, keep_token: str) -> None`. Checks the current password and the policy, clears `must_change_password`, and ends the user's other sessions.

- [ ] **Step 1: Write the failing tests.** Use `InMemoryAuthStore`, `FakeClock` from `netview.sdk.testing.fakes`, and a `PlainHasher` test double (`hash = "h:"+p`). Tests:
  - `test_resolve_returns_principal_with_role_permissions`
  - `test_idle_timeout_expires_session`: advance 28,801 s → `None`, and the record is gone.
  - `test_absolute_lifetime_expires_even_when_active`: touch every hour for 7 days and one second.
  - `test_disabled_user_session_resolves_none` (Review Focus 2)
  - `test_role_edit_visible_after_invalidate`
  - `test_token_stored_hashed`: the raw token is not among the stored keys.
  - `test_sign_in_wrong_password_generic_message`, and the same message for an unknown user and a disabled user.
  - `test_sign_in_case_insensitive_username` (Review Focus 4)
  - `test_lockout_after_five_failures_then_unlock_after_fifteen_minutes`: the 6th attempt raises `TooManyAttemptsError` even with the right password; after 900 s the right password works.
  - `test_lockout_is_per_ip`: another IP is unaffected.
  - `test_failures_outside_window_do_not_count`
  - `test_change_password_clears_must_change_and_other_sessions`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run the tests and the full gate.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(auth): sessions, permission resolution and password sign-in`.

---

### Task 5: First-run setup

**Files:**
- Create: `src/netview/application/usecases/auth/setup.py`
- Test: `tests/unit/application/test_setup.py`

**Interfaces:**
- Produces:
  - `make_setup_code() -> str`: 8 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, using `secrets`.
  - `@dataclass(frozen=True) class SetupStatus: open: bool; code_required: bool`
  - `class SetupService(store, hasher, sessions: SessionService, throttle: LoginThrottle, clock, mode: Literal["enterprise", "home"], code: str | None)`:
    - `status() -> SetupStatus`
    - `complete(code: str | None, username: str, password: str, ip: str, user_agent: str) -> SignInResult`
  - `complete` behaviour:
    - raises `ConflictError("setup already done")` when any user exists;
    - in Enterprise mode, compares the code with `hmac.compare_digest`, case-insensitively, and treats a mismatch as a throttled failure under the key `("#setup", ip)`;
    - checks the policy;
    - creates the built-in admin (`builtin=True`, roles `{ADMIN_ROLE}`, provider `"local"`) with `only_if_empty=True`;
    - returns a signed-in result.

- [ ] **Step 1: Write the failing tests**
  - `test_status_open_until_first_user`
  - `test_home_mode_needs_no_code`
  - `test_enterprise_wrong_code_rejected_and_throttled`
  - `test_code_is_case_insensitive`
  - `test_complete_creates_builtin_admin_and_signs_in`
  - `test_second_complete_conflicts`
  - `test_racing_completes_create_one_admin`: two threads, `threading.Barrier`, the in-memory store; exactly one succeeds (Review Focus 3).
  - `test_make_setup_code_alphabet`: 1,000 codes, all 8 characters long, all within the alphabet.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and the full gate.**
- [ ] **Step 5: Commit** `feat(auth): first-run setup with enterprise setup code`.

---

### Task 6: User, role and policy administration use cases

**Files:**
- Create: `src/netview/application/usecases/auth/admin.py`
- Modify: `src/netview/application/services.py`
- Test: `tests/unit/application/test_auth_admin.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class RoleView: role: Role; user_count: int`
  - `class UserAdmin(store, hasher, sessions, authorizer, policy, clock)`:
    - `list() -> list[User]`
    - `create_local(username: str, display_name: str, password: str, role_ids: set[str]) -> User`: sets `must_change_password=True`.
    - `update(user_id: int, *, display_name: str | None = None, role_ids: set[str] | None = None, enabled: bool | None = None) -> User`
    - `reset_password(user_id: int, password: str) -> None`: sets `must_change_password=True` and ends the user's sessions.
    - `delete(user_id: int) -> None`
  - Built-in admin protections: `update` refuses `enabled=False` and a role set without `administrator`; `delete` refuses. All three raise `ValidationError`.
  - Unknown role IDs raise `ValidationError`.
  - Disable, delete and role changes end sessions or invalidate the authorizer as appropriate.
  - `class RoleAdmin(store, authorizer, catalog: Callable[[], list[PermissionGroup]])`:
    - `list() -> list[RoleView]`
    - `create(name: str) -> Role`: the ID is a slug of the name; a clash raises `ConflictError`.
    - `update(role_id: str, *, name: str | None = None, permissions: set[str] | None = None) -> Role`
    - `delete(role_id: str) -> None`
  - Role protections:
    - built-ins can't be renamed or deleted;
    - Administrator's permissions can't be edited;
    - granting anything in `ADMIN_ONLY` raises `ValidationError`;
    - permission IDs not in the current catalog are **kept** if already stored on the role (§6.3: an uninstalled plugin's permissions survive) but rejected if newly added.
  - `class PolicyAdmin(store)`:
    - `get() -> AuthPolicy`
    - `update(**fields: int) -> AuthPolicy`: validates, then stores each field under the `settings` key `policy.<field>`.
  - `@dataclass class AuthServices` with fields: `sessions: SessionService`, `sign_in: SignIn`, `change_password: ChangeOwnPassword`, `setup: SetupService`, `users: UserAdmin`, `roles: RoleAdmin`, `policy: PolicyAdmin`, `authorizer: Authorizer`, `catalog: Callable[[], list[PermissionGroup]]`.
  - `AppServices.auth: AuthServices`

- [ ] **Step 1: Write the failing tests**
  - `test_builtin_admin_cannot_be_disabled_deleted_or_demoted`
  - `test_default_role_editable_not_deletable`
  - `test_administrator_permissions_not_editable`
  - `test_cannot_grant_install`
  - `test_stale_permission_kept_new_unknown_rejected`
  - `test_disable_ends_sessions` (Review Focus 2)
  - `test_role_change_invalidates_authorizer`
  - `test_create_local_requires_policy_and_marks_must_change`
  - `test_policy_update_persists_and_validates_floor`
  - `test_role_delete_removes_from_users`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Add the `auth` field to `AppServices`. The API test helper gets it in Task 8.
- [ ] **Step 4: Run the tests and the full gate.** The existing API tests that build `AppServices` will fail until Task 8, so give `build_world` an `auth=None` placeholder now (keep them green by making `AppServices.auth` default `None` until Task 8 removes the default).
- [ ] **Step 5: Commit** `feat(auth): user, role and policy administration`.

---

### Task 7: SQL store, Argon2 hasher and migration 0004

**Files:**
- Create: `src/netview/infrastructure/auth/sql_store.py`, `src/netview/infrastructure/auth/argon2_hasher.py`, `src/netview/infrastructure/db/core_versions/0004_auth.py`
- Modify: `src/netview/infrastructure/db/models.py`, `pyproject.toml` (add `argon2-cffi>=23.1`), `tests/contract/conftest.py`
- Test: `tests/integration/db/test_auth_migration.py`, `tests/unit/infrastructure/test_argon2_hasher.py`

**Interfaces:**
- Produces:
  - `class SqlAuthStore(session_factory: sessionmaker[Session])`, which satisfies `AuthStore`.
  - `class Argon2Hasher`, which satisfies `PasswordHasher` (argon2id, library defaults).
  - Migration `revision = "0004"`, `down_revision = "0003"`. Tables:
    - `users` (id PK autoincrement, username unique, display_name, email nullable, enabled, builtin, must_change_password, provider, created_ms BigInteger, last_sign_in_ms nullable)
    - `user_logins` (user_id FK→users ON DELETE CASCADE, provider, subject, password_hash nullable; PK (provider, subject)). The name avoids the existing `identity` repository, which means name claims. Local logins use `provider="local"` and `subject=<username>`.
    - `roles` (id PK, name, builtin)
    - `role_permissions` (role_id FK cascade, permission_id; PK both)
    - `user_roles` (user_id FK cascade, role_id FK cascade; PK both)
    - `sessions` (token_hash PK, user_id FK cascade index, created_ms, last_seen_ms, ip, user_agent)
    - `app_settings` (key PK, value Text)
  - The migration inserts the roles `administrator`/"Administrator" and `default`/"Default" (both builtin) and `role_permissions(default, core.view)`.
  - `only_if_empty=True` is implemented by inserting inside a transaction that first takes a write lock: `BEGIN IMMEDIATE` on SQLite, or `SELECT … FOR UPDATE` on the `users` table count where supported. It re-checks the count and raises `ConflictError`.

- [ ] **Step 1: Write the failing tests.**
  - Add the `SqlAuthStore` factory (SQLite file in `tmp_path`, migrated with the existing `migrate.upgrade_core`, or whatever `infrastructure/db/migrate.py` exposes) to the contract parametrization.
  - `test_upgrade_from_0003_keeps_data_and_seeds_roles`: start from 0003 with a device row; upgrade; the device is still there and both roles exist.
  - `test_racing_setup_inserts_on_sqlite`: two threads, `only_if_empty`, exactly one row.
  - `test_argon2_roundtrip_and_wrong_password`
- [ ] **Step 2: Run** `uv run pytest tests/contract tests/integration/db/test_auth_migration.py tests/unit/infrastructure/test_argon2_hasher.py -q`. Expected: fail.
- [ ] **Step 3: Implement**, then run `uv sync`.
- [ ] **Step 4: Run the tests and the full gate.** Expected: PASS for both store factories.
- [ ] **Step 5: Commit** `feat(auth): SQL auth store, Argon2 hasher and migration 0004`.

---

### Task 8: Authentication middleware, auth/setup/admin API, core route guards

**Files:**
- Create:
  - `src/netview/presentation/api/auth_middleware.py`
  - `src/netview/presentation/api/permissions.py`
  - `src/netview/presentation/api/routers/auth.py`
  - `src/netview/presentation/api/routers/setup.py`
  - `src/netview/presentation/api/routers/admin.py`
- Modify:
  - `src/netview/presentation/api/app.py`
  - `src/netview/presentation/api/errors.py`
  - `src/netview/presentation/api/schemas.py`
  - every router in `src/netview/presentation/api/routers/`
  - `tests/integration/api/api_helpers.py`
- Test:
  - `tests/integration/api/test_auth_api.py`
  - `tests/integration/api/test_setup_api.py`
  - `tests/integration/api/test_admin_api.py`
  - `tests/integration/api/test_core_guards.py`

**Interfaces:**
- Consumes: `AppServices.auth` (Task 6).
- Produces:
  - `class AuthMiddleware(app, services: AppServices, plugin_ids: Callable[[], set[str]])`. Pure ASGI, added inside `SecurityMiddleware`, so the Host and header checks run first. Per HTTP request:
    1. Reads the cookie `netview_session` and resolves it with `sessions.resolve`.
    2. Sets `current_principal` (and `scope["state"]["principal"]`) for the rest of the request. It resets the variable afterwards.
    3. Public paths, allowed without a principal:
       - exact: `/login`, `/setup`, `/api/v1/auth/login`, `/api/v1/setup` (only while setup is open), `/favicon.ico`
       - prefixes: `/static/`, `/themes/user/`
    4. While `setup.status().open`:
       - non-public HTML GETs redirect `303` to `/setup`;
       - `/login` redirects to `/setup`;
       - other API calls get `409 {"error": "setup required"}`.
    5. With no principal:
       - `/api/…` and `/openapi.json` → `401 {"error": "sign in required"}`;
       - other GETs → `303` to `/login?next=<path+query, URL-encoded>`.
    6. `/docs`, `/docs/init.js` and `/openapi.json` need `core.view`, else 403. These routes are FastAPI's or `app.py`'s own, so the middleware checks them rather than a route dependency.
    7. `/plugins/<id>/static/…` needs `<id>.view`, else 403. Normalize the path first (`posixpath.normpath` on the decoded path); a path that leaves `/plugins/<id>/static/` gets 404.
    8. A signed-in user with `must_change_password` gets `403 {"error": "password change required"}` on every API call except `/api/v1/auth/me`, `/api/v1/auth/password` and `/api/v1/auth/logout`.
  - `require_permission(permission_id: str) -> Any`: a `Depends` that raises `PermissionDeniedError` unless `get_principal().can(permission_id)`.
  - `require_admin() -> Any`: needs `ADMIN_ROLE` membership, i.e. `principal.permissions.everything`.
  - Error mapping:
    - `AuthenticationError` → 401
    - `PermissionDeniedError` → 403
    - `SetupRequiredError` → 409
    - `TooManyAttemptsError` → 429
  - Endpoints (§13.1, this stage only):
    - `GET /api/v1/auth/me` → `{username, display_name, provider, must_change_password, permissions: [ids], is_admin}`
    - `POST /api/v1/auth/login {username, password}`: sets the cookie, returns the `me` body.
    - `POST /api/v1/auth/logout` → 204, clears the cookie.
    - `POST /api/v1/auth/password {current, new}`
    - `GET /api/v1/auth/providers` → `[]` (stage 3 fills it).
    - `GET /api/v1/setup` → `{open, code_required}`
    - `POST /api/v1/setup {code?, username, password}`: sets the cookie.
    - `GET|POST /api/v1/admin/users`, `PATCH|DELETE /api/v1/admin/users/{id}`, `POST /api/v1/admin/users/{id}/password`: all `core.users`.
    - `GET|POST /api/v1/admin/roles`, `PATCH|DELETE /api/v1/admin/roles/{id}`, `GET /api/v1/admin/permissions`: all `core.users`.
    - `GET|PATCH /api/v1/admin/general`: `core.system`; the body is the six `AuthPolicy` fields plus a read-only `mode`.
  - Cookie helper: `Secure` when `request.url.scheme == "https"`. The client IP is `request.client.host` (stage 2 adds trusted proxies).
  - Core guards, exactly as §6.1:
    - `core.view`: every `GET` in `state`, `devices`, `events`, `metrics`, `inspections`, `watches`, `plugins`, `stream`, `themes` (`/docs` and `/openapi.json` are covered by the middleware, rule 6).
    - `core.rename`: `PUT /devices/{key}/nickname`
    - `core.forget`: `DELETE /devices/{key}`
    - `core.watches`: `POST`/`DELETE /watches`
    - `core.scan`: `POST /scan`, `POST /devices/{ip}/probe`, `POST /inspections`
    - `require_admin`: `POST /plugins/install`, `POST /plugins/catalog/refresh`
    - `PATCH /plugins/{id}`: `core.plugins` for the `enabled` field, `<id>.configure` for `settings`. A body with both needs both.
  - `GET /plugins` and `GET /plugins/{id}` drop `settings` and `settings_schema` (they become `null`) for plugins where the caller lacks `<id>.configure` (§6.2).
  - Stream: guarded by `core.view`. At each keep-alive tick, re-resolve the session; if it is gone, end the response (Review Focus 2).
  - `api_helpers`:
    - `build_world` wires real `AuthServices` with `InMemoryAuthStore`, a `PlainHasher` and the world's `FakeClock`, mode `"home"`, and seeds a built-in admin `admin`.
    - `make_client(app, with_header=True, user="admin")` signs in by creating a session straight through `services.auth.sessions.create` and setting the cookie; `user=None` means anonymous.
    - `world.add_user(username, role_ids) -> str` returns the username.
    - Existing API tests keep passing unchanged because they sign in as admin.

- [ ] **Step 1: Write the failing tests** (FastAPI `TestClient`).
  - `test_anonymous_api_401_and_page_redirects_to_login_with_next`
  - `test_setup_open_redirects_pages_and_409s_api`: a world with no users.
  - `test_setup_post_signs_in_and_closes_setup`
  - `test_setup_race_one_wins`: two threads posting through the client (Review Focus 3).
  - `test_login_sets_httponly_samesite_cookie_and_logout_clears`
  - `test_login_lockout_returns_429`
  - `test_login_requires_x_netview_header`
  - `test_must_change_password_blocks_other_api`
  - `@pytest.mark.parametrize` over the full §6.1 route table: `test_core_route_needs_its_permission`. A Default user gets 403 on each doing-route, and 2xx or 4xx-but-not-403 when granted.
  - `test_default_user_sees_dashboard_but_not_plugin_settings`: `GET /plugins` shows `settings` as `null` for the demo plugin.
  - `test_install_admin_only_even_with_all_grantable_permissions`
  - `test_patch_plugin_enabled_needs_core_plugins_settings_needs_configure`
  - `test_admin_users_crud_and_builtin_protections_map_to_422`
  - `test_admin_roles_and_permissions_catalog_shape`
  - `test_general_get_patch_and_floor_422`
  - `test_disabled_user_next_request_401`
  - `test_stream_closes_after_session_ended`: a short keep-alive, monkeypatched to 0.05 s.
- [ ] **Step 2: Run** `uv run pytest tests/integration/api -q`. Expected: the new tests fail.
- [ ] **Step 3: Implement.** In `create_app`, add `AuthMiddleware` so that `SecurityMiddleware` stays outermost. Include the new routers. Attach the guards with `dependencies=[require_permission(...)]` on each route decorator.
- [ ] **Step 4: Run the whole suite and the gate.** Expected: everything passes, old API tests included.
- [ ] **Step 5: Commit** `feat(auth): authentication middleware, auth/setup/admin API and core route guards`.

---

### Task 9: Plugin SDK 1.5: declared permissions, default guards, `ctx.require`, `ctx.principal`

**Files:**
- Modify:
  - `src/netview/application/plugins/base.py`
  - `src/netview/application/plugins/context.py`
  - `src/netview/application/plugins/manifest.py` (`SDK_VERSION = "1.5"`)
  - `src/netview/sdk/__init__.py`
  - `src/netview/infrastructure/plugins/host.py`
  - `src/netview/infrastructure/plugins/context.py`
  - `src/netview/presentation/api/app.py`
  - `src/netview/presentation/api/permissions.py`
  - `src/netview/sdk/testing/fakes.py`
  - `tests/unit/test_sdk_exports.py`
- Create: `docs/plugin-permissions.md`
- Test: `tests/integration/plugins/test_plugin_permissions.py`, `tests/integration/api/test_plugin_guards.py`

**Interfaces:**
- Produces:
  - `Plugin.user_permissions: ClassVar[tuple[UserPermission, ...]] = ()`
  - The host reads it from the class, for enabled and disabled plugins alike:
    - it fills `PluginInfo.user_permissions`;
    - it runs `validate_declared`; errors fail the plugin load like other manifest errors, with state `"failed"` and the message.
  - `PluginContext.require(permission_id: str) -> Any`: returns a FastAPI `Depends`. Implemented in `infrastructure/plugins/context.py`, which may import FastAPI. The dependency callable carries the attribute `__netview_permission__ = <full id>`. A relative ID gets `<plugin_id>.` prepended; `core.*` passes through. It raises `PermissionDeniedError` when `get_principal()` lacks the permission.
  - `PluginContext.principal() -> Principal`: `get_principal() or SYSTEM_PRINCIPAL`.
  - Audit port, so later stages can call it (spec §14):
    - `src/netview/application/ports/audit.py` defines `@dataclass(frozen=True) class AuditEntry: t_ms: int; username: str; ip: str | None; action: str; target: str | None; outcome: Literal["ok", "denied", "failed"]; detail: str | None`.
    - It also defines `class AuditSink(Protocol): def record(self, entry: AuditEntry) -> None` and `class NullAuditSink` (does nothing).
    - `AuthServices.audit: AuditSink` defaults to `NullAuditSink()`.
    - `PluginContext.audit(action: str, target: str | None = None, ok: bool = True, detail: str | None = None) -> None` builds an entry from `ctx.principal()` and the clock, and hands it to the sink.
    - The core makes no `record` calls in this stage; stage 4 adds them.
  - `netview.sdk` exports `UserPermission` and `Principal`.
  - `plugin_default_guard(plugin_id: str) -> Any` in `presentation/api/permissions.py`: a router-level dependency. It reads `request.scope["route"]`. If any of the route's dependencies' calls has `__netview_permission__`, it returns and lets that one decide. Otherwise it requires `default_permission_for(plugin_id, request.method)`.
  - `create_app` includes each plugin router with `dependencies=[Depends(plugin_default_guard(plugin_id))]`.
  - Fakes: `FakePluginContext.require` returns a no-op `Depends`; `principal()` returns `SYSTEM_PRINCIPAL`. Plugin unit tests keep passing.

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_get_needs_view_post_needs_use`: a demo router with `GET /x` and `POST /x`.
  - `test_explicit_guard_overrides_default`: `POST /console` with `ctx.require("console")`. A user holding only `demo.console` gets 2xx; a user with only `demo.use` gets 403.
  - `test_guard_holds_for_head_options_trailing_slash_and_encoded_slash` (Review Focus 1): each request is 401, 403, 404 or 405, never 200 with a body.
  - `test_static_needs_view_and_dotdot_404` (Review Focus 1)
  - `test_sdk14_plugin_loads_with_automatic_permissions`: a fixture plugin with `sdk_version=">=1.3,<2"` and no declarations.
  - `test_bad_declaration_fails_plugin_load`
  - `test_disabled_plugin_permissions_listed_off`: `GET /api/v1/admin/permissions`.
  - `test_ctx_principal_is_caller_in_request_and_system_in_job`
  - `test_ctx_audit_reaches_sink_with_caller`: give a recording sink to the context and call it from a route; the entry's `username` is the caller.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Write `docs/plugin-permissions.md`:
  - **The two meanings of "permissions"** (§5): the manifest `permissions` are what the plugin may do to the core; `user_permissions` are what users may do in the plugin.
  - Declaring permissions, and relabelling the automatic ones.
  - `ctx.require` and the default guards.
  - `can()` and slot `permission` (Task 12).
- [ ] **Step 4: Run the tests and the full gate**, including `uv run pytest plugins -q` for the folder plugins.
- [ ] **Step 5: Commit** `feat(sdk): 1.5 user permissions, default plugin route guards, ctx.require and ctx.principal`.

---

### Task 10: Bootstrap wiring, `mode`, setup-code print, `users` CLI

**Files:**
- Modify: `src/netview/infrastructure/settings.py` (`mode: Literal["enterprise","home"] = "enterprise"`), `src/netview/bootstrap.py`, `src/netview/presentation/cli.py`
- Test: `tests/integration/test_cli_users.py`, `tests/integration/test_bootstrap_auth.py`

**Interfaces:**
- Produces:
  - `build_container` builds `SqlAuthStore(sessions)`, `Argon2Hasher()`, and the services from Tasks 4–6. Policy is read through `PolicyAdmin.get`. The catalog is `lambda: build_catalog(host.list())`.
  - It sets `AppServices.auth`.
  - On `serve`, when no users exist and mode is Enterprise, it generates the code once per process and prints it to stdout and the log, framed so it stands out:

    ```
    ==============================================
    NetView setup code: ABCD2345
    Open http://<host>:<port>/setup to create the admin account.
    ==============================================
    ```

  - CLI (`users_app = typer.Typer()` added as `users`):
    - `netview users list`: columns `username`, `provider`, `roles`, `enabled`, `last sign-in`.
    - `netview users reset-password USERNAME`: `typer.prompt(..., hide_input=True, confirmation_prompt=True)`, the policy check, ends that user's sessions, sets `must_change_password=False` (the admin chose it at the console).
    - `netview users enable USERNAME`: refuses the built-in admin with "the built-in admin can't be disabled, so there is nothing to enable".
  - `serve --mode [enterprise|home]` overrides the setting.

- [ ] **Step 1: Write the failing tests** with Typer's `CliRunner` and a `tmp_path` data dir:
  - `test_users_list_after_setup`
  - `test_reset_password_prompts_twice_and_ends_sessions`
  - `test_reset_password_unknown_user_exit_code_1`
  - `test_enable_reenables_disabled_user`
  - `test_serve_prints_setup_code_in_enterprise_only`: call the print helper directly, `print_setup_banner(settings, code)`, and assert on captured output.
  - `test_mode_env_and_flag`: `NETVIEW_MODE=home`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and the full gate.** Then start the dev server with the HomeLab `netview` launch config, data dir `netview-dev`. Confirm it prints the banner because no users exist, and that the existing devices are still listed after setup. Do this through the preview tools, not Bash.
- [ ] **Step 5: Commit** `feat(auth): wiring, mode setting, setup banner and users CLI`.

---

### Task 11: Sign-in and setup pages; API client reactions; account menu

**Files:**
- Create:
  - `src/netview/presentation/web/static/login.html`
  - `src/netview/presentation/web/static/setup.html`
  - `src/netview/presentation/web/static/js/auth/login.js`
  - `src/netview/presentation/web/static/js/auth/setup.js`
  - `src/netview/presentation/web/static/js/auth.js`
- Modify:
  - `src/netview/presentation/web/static/js/api.js`
  - `src/netview/presentation/web/static/index.html`
  - `src/netview/presentation/web/static/js/main.js`
  - `src/netview/presentation/web/static/css/app.css`
  - `src/netview/presentation/api/app.py` (serve `/login` and `/setup`)
- Test: `tests/js/auth.test.mjs`, `tests/integration/api/test_web_shell.py` (extend)

**Interfaces:**
- Produces (`js/auth.js`):
  - `safeNext(raw: string) -> string`: returns `raw` only when it starts with a single `/` that is not followed by `/` or `\`, and has no scheme; otherwise `/` (Review Focus 5).
  - `createAuth(me) -> { user: {username, displayName}, provider, can(id), isAdmin, mustChange }`
  - `accountMenuHtml(auth) -> string`. Its lines:
    - the display name;
    - "Signed in with NetView account" for local accounts;
    - "Change password", only for local accounts;
    - "Sign out".
- `api.js`:
  - A `401` from `apiGet` or `apiSend` assigns `location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search + location.hash)`.
  - A `403` with `error === "password change required"` opens the change-password dialog.
  - Other `403`s throw as today; the shell's toast says "You don't have permission to do that".
- Pages:
  - Both are static HTML with a module script, no inline script, and the theme stylesheets as in `index.html`.
  - Copy as in spec §9.2 and the approved mockup:
    - Login: "NetView", "Sign in to continue", the provider buttons area (empty in this stage), "or with a NetView account", "Username", "Password", "Sign in".
    - Setup: "Welcome to NetView"; "Create the administrator account. You can add sign-in with Microsoft, Google and others afterwards in Admin."; "Setup code from the server console" (only when `code_required`); "Admin username", "Password", "Confirm password", "Create account and sign in".
  - Setup checks that the two passwords match before posting. A server 422 shows field messages next to the fields.
  - On success, both pages go to `safeNext(new URLSearchParams(location.search).get("next"))`.
- Shell: the account button sits at the right of the topbar after the Settings button. When `me.must_change_password` is true, the change-password dialog opens and can't be dismissed until the change succeeds.

- [ ] **Step 1: Write the failing tests.**
  - `tests/js/auth.test.mjs`:
    - `safeNext` cases: `/devices` ok; `//evil.example`, `https://evil.example`, `/\\evil.example`, `javascript:alert(1)`, `""` and `null` all → `/`.
    - `createAuth().can` with and without `is_admin`.
    - `accountMenuHtml` hides "Change password" for non-local providers.
  - `test_web_shell.py`: `/login` and `/setup` are served with the CSP header and no inline `<script>` body.
- [ ] **Step 2: Run** `npm test` and `uv run pytest tests/integration/api/test_web_shell.py -q`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and the gate.** Then check in the browser pane against the dev server:
  - the setup page, then sign-in, the account menu and sign-out;
  - a wrong password shows the generic message;
  - six wrong attempts show the lockout message.

  Take a screenshot of each page.
- [ ] **Step 5: Commit** `feat(web): sign-in and setup pages, account menu, 401/403 handling`.

---

### Task 12: Hide what the user can't use

**Files:**
- Modify:
  - `src/netview/presentation/web/static/js/main.js`
  - `src/netview/presentation/web/static/js/slots.js`
  - `src/netview/presentation/web/static/js/nav.js`
  - `src/netview/presentation/web/static/js/pages/devices.js`
  - `src/netview/presentation/web/static/js/cards/watches.js`
  - `src/netview/presentation/web/static/js/report/dialog.js`
  - `src/netview/presentation/web/static/js/settings/plugins-tab.js`
  - `src/netview/presentation/web/static/js/settings/dialog.js`
- Create: `src/netview/presentation/web/static/js/pages/no-access.js`
- Test: `tests/js/plugin-ui.test.mjs`, `tests/js/nav.test.mjs`, `tests/js/pages.test.mjs` (extend)

**Interfaces:**
- Consumes: `createAuth` (Task 11).
- Produces:
  - `createUiHost(auth)`:
    - `loadPlugins` skips a plugin unless `auth.can(id + ".view")`;
    - `uiApi` gains `user` and `can(rel)` (a relative ID resolves to `<pluginId>.<rel>`; `core.*` passes through);
    - `slot()` records `spec.permission`, and `get(name)` filters out specs whose permission the user lacks.
  - Core actions are hidden without their permission:
    - the Scan button: `core.scan`;
    - inline rename: `core.rename`;
    - Forget: `core.forget`;
    - Watch / Remove: `core.watches`;
    - the report dialog's "Run again" and "All ports": `core.scan`.
  - Settings dialog: the Plugins tab lists only plugins with `<id>.configure`. The enable switch shows only with `core.plugins`. The gallery's install controls show only when `auth.isAdmin`.
  - A user with no permissions at all (an empty `permissions` list and not admin) sees the `no-access` page: "You don't have access to anything yet. Ask a NetView admin to give you a role." The account menu stays available.
  - The Admin nav tab (Task 13) is added only when `auth.can("core.users") || auth.can("core.system")`.

- [ ] **Step 1: Write the failing tests** (pure functions plus the existing jsdom-free patterns in `tests/js`):
  - `test slot with permission hidden without it`
  - `test plugin module not loaded without view`
  - `test uiApi.can resolves relative ids`
  - `test devices actions html omits forget without core.forget`: export the existing row-actions helper if it isn't already.
  - `test nav includes Admin only for users or system holders`
- [ ] **Step 2: Run** `npm test`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` and the gate. Then check in the browser: sign in as a Default user created in Task 13's Admin page (or through the API) and confirm there are no Scan, Forget, Watch or rename controls, no plugin pages, and no Admin tab. Screenshot it.
- [ ] **Step 5: Commit** `feat(web): hide actions, plugin UI and settings the user lacks permission for`.

---

### Task 13: Admin page: Users, Roles, General

**Files:**
- Create:
  - `src/netview/presentation/web/static/js/pages/admin/admin.js`: the page shell and sidebar
  - `src/netview/presentation/web/static/js/pages/admin/users.js`
  - `src/netview/presentation/web/static/js/pages/admin/roles.js`
  - `src/netview/presentation/web/static/js/pages/admin/general.js`
- Modify: `src/netview/presentation/web/static/js/main.js` (route `admin`), `src/netview/presentation/web/static/css/app.css`
- Test: `tests/js/admin.test.mjs`

**Interfaces:**
- Consumes: the `/api/v1/admin/*` endpoints from Task 8, and `createAuth`.
- Produces:
  - `adminSections(auth) -> [{id, label}]`, in the sidebar order from §9.1:
    - Users and Roles (each needs `core.users`);
    - Sign-in providers and HTTPS certificate (stage 2/3 placeholders, left out in this stage);
    - General (needs `core.system`);
    - Audit log (stage 4, left out).
  - Users section (mockup "Admin → Users"):
    - table columns: User, Signs in with, Roles (pills), Last sign-in, and the row action (`built-in`, `Edit`, or `Disabled`);
    - an "Add local user" dialog: username, display name, initial password, roles;
    - an Edit dialog: roles, enable/disable, reset password, delete with a confirm step that names the user;
    - the built-in admin row offers only "Change password".
  - Roles section (mockup "Admin → Roles"):
    - the roles list with "built-in" and "N users" tags, and "+ New role";
    - permission groups from `/admin/permissions`, "NetView core" first, each permission a checkbox with its label;
    - descriptions shown muted, dangerous ones with a warning marker;
    - groups of disabled plugins titled "<name> (off)";
    - locked rows disabled, with the lock reason as a tooltip;
    - Administrator's boxes all checked and disabled;
    - Save, Rename and Delete (Delete absent for built-ins).
  - General section:
    - six number inputs labelled "Password minimum length", "Session idle timeout (hours)", "Session lifetime (days)", "Sign-in failures allowed", "Within (minutes)", "Locked for (minutes)";
    - each shows its default and has a "Reset to default" control;
    - hours, days and minutes are converted to seconds on save;
    - the read-only mode line reads: "Mode: Enterprise. Set `mode` in netview.toml or `--mode` on `netview serve`."
  - Pure helpers to test: `roleEditorModel(role, groups) -> {groups:[{title, off, rows:[{id,label,checked,disabled,title}]}]}`, `generalFormModel(policy) -> rows`, `secondsFromForm(rows) -> policy`.

- [ ] **Step 1: Write the failing tests:**
  - `roleEditorModel` locks every row for Administrator;
  - it disables locked rows with the lock reason as their title;
  - it marks off groups;
  - `generalFormModel` converts 28800 s to 8 h and 604800 s to 7 days;
  - `secondsFromForm` round-trips;
  - `adminSections` for a `core.users`-only user leaves out General.
- [ ] **Step 2: Run** `npm test`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` and the gate. Then, in the browser pane against the dev server:
  - create a Helpdesk role with `core.view`, `core.rename` and `gsm7248.view`;
  - add a local user in Helpdesk;
  - sign in as them in a second tab and confirm what they see;
  - disable them from the first tab, and confirm the second tab's next action lands on the login page.

  Screenshot Users, Roles and General.
- [ ] **Step 5: Commit** `feat(web): Admin page with Users, Roles and General`.

---

### Task 14: Whole-stage check

**Files:** none new, except fixes found here.

- [ ] **Step 1:** Run the full gate. All of it must be green: `uv run pytest -q`, `uv run pytest plugins -q`, `npm test`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports`.
- [ ] **Step 2:** Walk spec sections 3, 6, 7.1, 7.2, 7.5, 7.6, 9 (Users, Roles, General), 10.1–10.4, 12 and 13 against the code. List anything missing as a fix task here.
- [ ] **Step 3:** Hand off to the whole-branch review (subagent-driven-development's final step).
- [ ] **Step 4:** Update `docs/superpowers/deferred.md` with what the later stages carry:
  - stage 2: TLS, the allowlist, the public address and trusted proxies;
  - stage 3: providers;
  - stage 4: the audit plugin, the GSM7248 console declaration with its server-local rule, and the existing-plugin route review.
- [ ] **Step 5: Commit** `docs: record auth stages 2-4 as deferred`.
