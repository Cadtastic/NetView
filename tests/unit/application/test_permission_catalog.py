import pytest

from netview.application.auth.catalog import (
    build_catalog,
    default_permission_for,
    plugin_group,
    validate_declared,
)
from netview.application.plugins.user_permissions import UserPermission
from netview.application.ports.plugin_admin import PluginInfo

G = "3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4"  # gsm7248's guid


def info(guid=G, caps=("api", "web_ui"), schema={"type": "object"}, declared=(), state="active"):  # noqa: B006
    return PluginInfo(
        "7",  # the runtime key (a source_id) never appears in a permission id
        "NETGEAR GSM7248",
        "0.1",
        "",
        state,
        capabilities=list(caps),
        settings_schema=schema,
        user_permissions=list(declared),
        guid=guid,
        source_id=7,
    )


def test_core_group_first_and_verbatim_labels():
    g = build_catalog([])[0]
    assert g.owner == "core"
    assert [p.id for p in g.permissions][:8] == [
        "core.view",
        "core.rename",
        "core.forget",
        "core.watches",
        "core.scan",
        "core.plugins",
        "core.users",
        "core.system",
    ]
    install = next(p for p in g.permissions if p.id == "core.install")
    assert install.locked == "Administrator only: installing runs downloaded code"


def test_automatic_permissions_follow_manifest_and_settings():
    ids = [p.id for p in plugin_group(info()).permissions]
    assert ids == [f"{G}.view", f"{G}.use", f"{G}.configure"]
    assert [p.id for p in plugin_group(info(caps=("web_ui",), schema=None)).permissions] == [f"{G}.view"]
    assert plugin_group(info()).permissions[0].label == "View NETGEAR GSM7248"


def test_declared_are_prefixed_and_relabel_allowed():
    g = plugin_group(
        info(
            declared=[
                UserPermission("console", "Open serial console", "Full CLI", True),
                UserPermission("view", "View the switch"),
            ]
        )
    )
    assert g.permissions[0].label == "View the switch"
    assert g.permissions[-1].id == f"{G}.console" and g.permissions[-1].dangerous
    assert g.owner == G


def test_validate_declared():
    assert validate_declared("p", [UserPermission("Bad Id", "x")], {"view"})
    assert validate_declared("p", [UserPermission("a", "x"), UserPermission("a", "y")], {"view"})
    assert validate_declared("p", [UserPermission("use", "x")], {"view"})  # no api -> no automatic use
    assert validate_declared("p", [UserPermission("view", "x")], {"view"}) == []


def test_disabled_shown_off_pending_hidden():
    groups = build_catalog([info("a", state="disabled"), info("b", state="pending")])
    assert [(g.owner, g.off) for g in groups[1:]] == [("a", True)]


def test_a_card_that_lost_its_guid_or_has_none_holds_no_permissions():
    lost = info("a")
    lost.owns_data = False
    none = info(None)
    assert build_catalog([lost, none])[1:] == []


@pytest.mark.parametrize(
    ("m", "suffix"),
    [
        ("GET", "view"),
        ("HEAD", "view"),
        ("OPTIONS", "view"),
        ("POST", "use"),
        ("DELETE", "use"),
        ("PATCH", "use"),
    ],
)
def test_default_permission_for(m, suffix):
    assert default_permission_for(G, m) == f"{G}.{suffix}"
