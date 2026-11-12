"""User, role and general-settings administration."""

from dataclasses import asdict

from fastapi import APIRouter, Response

from netview.domain.auth import Role, User
from netview.presentation.api.deps import Auth
from netview.presentation.api.permissions import CurrentUser, require_permission
from netview.presentation.api.schemas import (
    GeneralOut,
    GeneralPatch,
    PasswordResetIn,
    PermissionGroupOut,
    RoleCreateIn,
    RoleOut,
    RolePatch,
    UserCreateIn,
    UserOut,
    UserPatch,
)

router = APIRouter(prefix="/admin")

_USERS = [require_permission("core.users")]
_SYSTEM = [require_permission("core.system")]


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        enabled=user.enabled,
        builtin=user.builtin,
        must_change_password=user.must_change_password,
        role_ids=sorted(user.role_ids),
        provider=user.provider,
        created_ms=user.created_ms,
        last_sign_in_ms=user.last_sign_in_ms,
    )


def _role_out(role: Role, user_count: int) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        builtin=role.builtin,
        permissions=sorted(role.permissions),
        user_count=user_count,
    )


@router.get("/users", response_model=list[UserOut], dependencies=_USERS)
def list_users(auth: Auth) -> list[UserOut]:
    return [_user_out(u) for u in auth.users.list()]


@router.post("/users", response_model=UserOut, status_code=201, dependencies=_USERS)
def create_user(body: UserCreateIn, auth: Auth, actor: CurrentUser) -> UserOut:
    user = auth.users.create_local(actor, body.username, body.display_name, body.password, set(body.role_ids))
    return _user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=_USERS)
def update_user(user_id: int, body: UserPatch, auth: Auth, actor: CurrentUser) -> UserOut:
    user = auth.users.update(
        actor,
        user_id,
        display_name=body.display_name,
        role_ids=None if body.role_ids is None else set(body.role_ids),
        enabled=body.enabled,
    )
    return _user_out(user)


@router.delete("/users/{user_id}", status_code=204, dependencies=_USERS)
def delete_user(user_id: int, auth: Auth, actor: CurrentUser) -> Response:
    auth.users.delete(actor, user_id)
    return Response(status_code=204)


@router.post("/users/{user_id}/password", status_code=204, dependencies=_USERS)
def reset_password(user_id: int, body: PasswordResetIn, auth: Auth, actor: CurrentUser) -> Response:
    auth.users.reset_password(actor, user_id, body.password)
    return Response(status_code=204)


@router.get("/roles", response_model=list[RoleOut], dependencies=_USERS)
def list_roles(auth: Auth) -> list[RoleOut]:
    return [_role_out(v.role, v.user_count) for v in auth.roles.list()]


@router.post("/roles", response_model=RoleOut, status_code=201, dependencies=_USERS)
def create_role(body: RoleCreateIn, auth: Auth, actor: CurrentUser) -> RoleOut:
    role = auth.roles.create(body.name)
    if body.permissions:
        try:
            role = auth.roles.update(actor, role.id, permissions=set(body.permissions))
        except Exception:
            auth.roles.delete(actor, role.id)  # do not leave a half-made role behind
            raise
    return _role_out(role, 0)


@router.patch("/roles/{role_id}", response_model=RoleOut, dependencies=_USERS)
def update_role(role_id: str, body: RolePatch, auth: Auth, actor: CurrentUser) -> RoleOut:
    role = auth.roles.update(
        actor,
        role_id,
        name=body.name,
        permissions=None if body.permissions is None else set(body.permissions),
    )
    count = next((v.user_count for v in auth.roles.list() if v.role.id == role.id), 0)
    return _role_out(role, count)


@router.delete("/roles/{role_id}", status_code=204, dependencies=_USERS)
def delete_role(role_id: str, auth: Auth, actor: CurrentUser) -> Response:
    auth.roles.delete(actor, role_id)
    return Response(status_code=204)


@router.get("/permissions", response_model=list[PermissionGroupOut], dependencies=_USERS)
def list_permissions(auth: Auth) -> list[PermissionGroupOut]:
    return [PermissionGroupOut.model_validate(g) for g in auth.catalog()]


def _general(auth: Auth) -> GeneralOut:
    return GeneralOut(**asdict(auth.policy.get()), mode=auth.mode)


@router.get("/general", response_model=GeneralOut, dependencies=_SYSTEM)
def get_general(auth: Auth) -> GeneralOut:
    return _general(auth)


@router.patch("/general", response_model=GeneralOut, dependencies=_SYSTEM)
def patch_general(body: GeneralPatch, auth: Auth) -> GeneralOut:
    auth.policy.update(**body.model_dump(exclude_none=True))
    return _general(auth)
