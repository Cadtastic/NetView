from netview.application.plugins.plugin_type import PluginType


def test_plugin_type_values() -> None:
    assert [t.value for t in PluginType] == [
        "router",
        "switch",
        "access_point",
        "firewall",
        "modem",
        "server",
        "nas",
        "computer",
        "tv",
        "printer",
        "camera",
        "ups",
        "iot",
        "software",
        "other",
    ]


def test_sdk_exports_plugin_type() -> None:
    from netview.sdk import PluginType as Exported

    assert Exported is PluginType
