"""Settings labels that the UI would otherwise derive badly from field names (acronyms, vague names)."""

from netview.plugins.builtin.health.settings import HealthSettings
from netview.plugins.builtin.identity.settings import IdentitySettings
from netview.plugins.builtin.inspection.settings import InspectionSettings
from netview.plugins.builtin.starlink.settings import StarlinkSettings


def titles(model: type) -> dict[str, str]:
    return {k: v.get("title", "") for k, v in model.model_json_schema()["properties"].items()}


def test_acronyms_keep_their_spelling_in_settings_titles() -> None:
    assert titles(HealthSettings)["dns_servers"] == "DNS servers"
    assert titles(HealthSettings)["dns_names"] == "DNS test names"
    assert titles(IdentitySettings)["ssdp_timeout_s"] == "SSDP timeout (s)"
    assert titles(IdentitySettings)["mdns_timeout_s"] == "mDNS timeout (s)"
    assert titles(IdentitySettings)["netbios_timeout_s"] == "NetBIOS timeout (s)"
    assert titles(IdentitySettings)["rdns_timeout_s"] == "Reverse DNS timeout (s)"


def test_vague_settings_get_a_title_and_help() -> None:
    schema = StarlinkSettings.model_json_schema()["properties"]["router"]
    assert schema["title"] == "Router address"
    assert "Blank means the gateway" in schema["description"]
    assert titles(InspectionSettings)["max_analyzed"] == "Open ports analyzed at most"
