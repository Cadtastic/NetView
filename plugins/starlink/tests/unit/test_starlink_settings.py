"""Settings labels that the UI would otherwise derive badly from field names."""

from netview_local_plugins.starlink.settings import StarlinkSettings


def test_the_router_setting_has_a_title_and_help() -> None:
    schema = StarlinkSettings.model_json_schema()["properties"]["router"]
    assert schema["title"] == "Router address"
    assert "Blank means the gateway" in schema["description"]
