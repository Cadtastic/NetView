from pathlib import Path

from conftest import import_folders

from netview.application.plugins.manifest import PluginManifest
from netview.application.plugins.plugin_type import PluginType
from netview.plugins.builtin.health.plugin import HealthPlugin
from netview.plugins.builtin.identity.plugin import IdentityPlugin
from netview.plugins.builtin.inspection.plugin import InspectionPlugin
from netview.plugins.builtin.lan_discovery.plugin import LanDiscoveryPlugin
from netview.plugins.builtin.local_host.plugin import LocalHostPlugin

PLUGINS = Path(__file__).resolve().parents[3] / "plugins"

FIXED = {
    "lan_discovery": ("4eddf684-deb5-41cf-9588-020746307ade", "LAN discovery", PluginType.SOFTWARE),
    "health": ("9f4cd689-1a67-4c89-abff-ac9252568d97", "Health", PluginType.SOFTWARE),
    "identity": ("4b77e778-dc26-4ac0-8b2e-fe3995363df1", "Identity", PluginType.SOFTWARE),
    "inspection": ("ac1dc07d-123c-4414-a4c8-72013d00f267", "Inspection", PluginType.SOFTWARE),
    "local_host": ("0a505ba4-bbbd-40b8-a77d-8f5dbe1470a8", "This device", PluginType.SOFTWARE),
    "gsm7248": ("3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4", "GSM7248", PluginType.SWITCH),
    "gs105e": ("c66a564b-0254-44cf-bb74-1c7f6ebae6be", "GS105E", PluginType.SWITCH),
    "starlink": ("67216b55-f454-4876-b26f-336e505c83ce", "Starlink", PluginType.ROUTER),
    "roku": ("241d4d28-4a70-406c-833c-a7b4d5b389a9", "Roku", PluginType.TV),
}
BUILTINS = (LanDiscoveryPlugin, HealthPlugin, IdentityPlugin, InspectionPlugin, LocalHostPlugin)


def _manifests() -> list[PluginManifest]:
    folders = [d.cls for d in import_folders(PLUGINS) if d.cls is not None]
    return [p.manifest for p in (*BUILTINS, *folders)]


def test_every_plugin_has_fixed_guid() -> None:
    manifests = _manifests()
    by_guid = {guid: (guid, name, kind) for guid, name, kind in FIXED.values()}
    assert {m.guid for m in manifests} == set(by_guid)
    for m in manifests:
        assert (m.guid, m.display_name, m.plugin_type) == by_guid[m.guid], m.display_name
