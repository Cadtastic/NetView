from __future__ import annotations

from netview_local_plugins.gs105e.settings import Gs105eSettings

from netview.application.plugins.settings_requirements import unmet_requirements


def test_defaults_are_valid_and_not_configured() -> None:
    s = Gs105eSettings.model_validate({})
    assert s.host == "192.168.1.3"
    assert s.port == 80
    assert s.password is None
    assert s.configured() is False


def test_configured_needs_host_and_password() -> None:
    assert Gs105eSettings.model_validate({"password": "pw"}).configured() is True
    assert Gs105eSettings.model_validate({"password": "pw", "host": ""}).configured() is False
    assert Gs105eSettings.model_validate({"password": ""}).configured() is False


def test_password_text_unwraps() -> None:
    assert Gs105eSettings.model_validate({"password": "pw"}).password_text() == "pw"
    assert Gs105eSettings.model_validate({"password": ""}).password_text() is None
    assert Gs105eSettings.model_validate({}).password_text() is None


def test_tabs_are_general_and_connection() -> None:
    schema = Gs105eSettings.model_json_schema()
    assert schema["tabs"] == ["General", "Connection"]
    assert {p["tab"] for p in schema["properties"].values()} == {"General", "Connection"}
    assert [n for n, p in schema["properties"].items() if not p.get("group")] == []


def test_password_is_a_secret_in_the_schema() -> None:
    prop = Gs105eSettings.model_json_schema()["properties"]["password"]
    branch = next(b for b in prop["anyOf"] if b.get("type") == "string")
    assert branch["writeOnly"] is True
    assert branch["format"] == "password"
    assert "restart" in prop["description"]


def test_every_field_has_a_description() -> None:
    assert [n for n, f in Gs105eSettings.model_fields.items() if not f.description] == []


def test_host_and_password_are_required_by_the_schema() -> None:
    schema = Gs105eSettings.model_json_schema()
    assert set(unmet_requirements(schema, {"host": "h", "password": None})) == {"password"}
    assert unmet_requirements(schema, {"host": "h", "password": "********"}) == {}
