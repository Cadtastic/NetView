"""Saved plugin references move from the author-written id to the plugin's guid.

Re-keys ``plugin_state.plugin_id``, the ``plugin_id`` of each section in
``inspection_reports.sections_json`` and the ``<id>.`` prefix of ``role_permissions.permission_id``. Rows with
an id that is not in the map belong to no current plugin; they are left alone and logged.

The map is a literal copy on purpose: a migration must not import application code, and it must keep meaning
what it meant when it was written.

Revision ID: 0006
Revises: 0005
"""

import json
import logging

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

LEGACY_GUIDS: dict[str, str] = {
    "lan_discovery": "4eddf684-deb5-41cf-9588-020746307ade",
    "health": "9f4cd689-1a67-4c89-abff-ac9252568d97",
    "identity": "4b77e778-dc26-4ac0-8b2e-fe3995363df1",
    "inspection": "ac1dc07d-123c-4414-a4c8-72013d00f267",
    "local_host": "0a505ba4-bbbd-40b8-a77d-8f5dbe1470a8",
    "gsm7248": "3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4",
    "gs105e": "c66a564b-0254-44cf-bb74-1c7f6ebae6be",
    "starlink": "67216b55-f454-4876-b26f-336e505c83ce",
    "roku": "241d4d28-4a70-406c-833c-a7b4d5b389a9",
}


def _rekey_state(bind: sa.Connection) -> None:
    for (plugin_id,) in bind.execute(sa.text("SELECT plugin_id FROM plugin_state")).all():
        guid = LEGACY_GUIDS.get(plugin_id)
        if guid is None:
            if plugin_id not in LEGACY_GUIDS.values():
                log.warning("plugin_state: no guid known for %r; left as it is", plugin_id)
            continue
        taken = bind.execute(sa.text("SELECT 1 FROM plugin_state WHERE plugin_id = :g"), {"g": guid}).first()
        if taken is not None:
            log.warning("plugin_state: %r already has a row for guid %s; left as it is", plugin_id, guid)
            continue
        bind.execute(
            sa.text("UPDATE plugin_state SET plugin_id = :g WHERE plugin_id = :old"),
            {"g": guid, "old": plugin_id},
        )


def _rekey_reports(bind: sa.Connection) -> None:
    for row_id, sections_json in bind.execute(
        sa.text("SELECT id, sections_json FROM inspection_reports")
    ).all():
        try:
            sections = json.loads(sections_json)
        except ValueError:
            log.warning("inspection_reports %s: sections_json is not JSON; left as it is", row_id)
            continue
        changed = False
        for section in sections:
            guid = LEGACY_GUIDS.get(section.get("plugin_id", ""))
            if guid is not None:
                section["plugin_id"] = guid
                changed = True
        if changed:
            bind.execute(
                sa.text("UPDATE inspection_reports SET sections_json = :j WHERE id = :id"),
                {"j": json.dumps(sections), "id": row_id},
            )


def _rekey_permissions(bind: sa.Connection) -> None:
    rows = bind.execute(sa.text("SELECT role_id, permission_id FROM role_permissions")).all()
    for role_id, permission_id in rows:
        owner, dot, rest = permission_id.partition(".")
        guid = LEGACY_GUIDS.get(owner)
        if not dot or guid is None:
            if dot and owner != "core" and owner not in LEGACY_GUIDS.values():
                log.warning("role_permissions: no guid known for %r; left as it is", permission_id)
            continue
        new_id = f"{guid}.{rest}"
        bind.execute(
            sa.text("INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (:r, :new)"),
            {"r": role_id, "new": new_id},
        )
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE role_id = :r AND permission_id = :old"),
            {"r": role_id, "old": permission_id},
        )


def upgrade() -> None:
    bind = op.get_bind()
    _rekey_state(bind)
    _rekey_reports(bind)
    _rekey_permissions(bind)


def downgrade() -> None:
    bind = op.get_bind()
    reverse = {guid: legacy for legacy, guid in LEGACY_GUIDS.items()}
    for guid, legacy in reverse.items():
        bind.execute(
            sa.text("UPDATE plugin_state SET plugin_id = :l WHERE plugin_id = :g"), {"l": legacy, "g": guid}
        )
        bind.execute(
            sa.text(
                "UPDATE role_permissions SET permission_id = :l || substr(permission_id, :n) "
                "WHERE permission_id LIKE :g || '.%'"
            ),
            {"l": legacy, "g": guid, "n": len(guid) + 1},
        )
    for row_id, sections_json in bind.execute(
        sa.text("SELECT id, sections_json FROM inspection_reports")
    ).all():
        sections = json.loads(sections_json)
        for section in sections:
            section["plugin_id"] = reverse.get(section.get("plugin_id", ""), section.get("plugin_id"))
        bind.execute(
            sa.text("UPDATE inspection_reports SET sections_json = :j WHERE id = :id"),
            {"j": json.dumps(sections), "id": row_id},
        )
