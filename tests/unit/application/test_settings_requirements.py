from typing import Literal

from pydantic import BaseModel, ConfigDict

from netview.application.plugins.settings_requirements import (
    is_blank,
    unmet_requirements,
)
from netview.sdk import fixed_when, required_when, settings_requirements


class _Settings(BaseModel):
    model_config = ConfigDict(
        json_schema_extra=settings_requirements(
            required=["host"],
            rules=[
                required_when({"mode": "key"}, ["key"]),
                required_when({"mode": ["key", "user"]}, ["user"]),
                fixed_when({"mode": "none"}, "level", 0, "Level must be 0 without a mode"),
            ],
        )
    )

    name: str
    host: str = ""
    mode: Literal["none", "key", "user"] = "none"
    key: str | None = None
    user: str = ""
    level: int = 0


SCHEMA = _Settings.model_json_schema()


def test_pydantic_required_and_extra_required_are_merged() -> None:
    assert SCHEMA["required"] == ["name", "host"]
    assert len(SCHEMA["allOf"]) == 3


def test_blank_values() -> None:
    assert all(is_blank(v) for v in (None, "", "   ", [], {}))
    assert not any(is_blank(v) for v in ("x", 0, False, ["a"]))


def test_top_level_required() -> None:
    assert unmet_requirements(SCHEMA, {"name": "n"}) == {"host": "Required"}
    assert unmet_requirements(SCHEMA, {"name": "n", "host": " "}) == {"host": "Required"}
    assert unmet_requirements(SCHEMA, {"name": "n", "host": "h"}) == {}


def test_const_condition_requires_a_field() -> None:
    values = {"name": "n", "host": "h", "mode": "key", "user": "u"}
    assert unmet_requirements(SCHEMA, values) == {"key": "Required"}
    assert unmet_requirements(SCHEMA, {**values, "key": "k"}) == {}


def test_enum_condition_requires_a_field() -> None:
    assert unmet_requirements(SCHEMA, {"name": "n", "host": "h", "mode": "user"}) == {"user": "Required"}


def test_fixed_value_with_its_message() -> None:
    problems = unmet_requirements(SCHEMA, {"name": "n", "host": "h", "level": 3})
    assert problems == {"level": "Level must be 0 without a mode"}


def test_fixed_value_without_message_names_the_value() -> None:
    schema = {
        "properties": {"a": {"default": "x"}, "b": {"default": 1}},
        "allOf": [{"if": {"properties": {"a": {"const": "x"}}}, "then": {"properties": {"b": {"const": 2}}}}],
    }
    assert unmet_requirements(schema, {}) == {"b": "Must be 2"}


def test_missing_values_take_the_schema_default() -> None:
    schema = {
        "properties": {"mode": {"default": "key"}, "key": {}},
        "allOf": [required_when({"mode": "key"}, ["key"])],
    }
    assert unmet_requirements(schema, {}) == {"key": "Required"}
    assert unmet_requirements(schema, {"mode": "off"}) == {}


def test_problems_follow_schema_order_and_first_wins() -> None:
    problems = unmet_requirements(SCHEMA, {"mode": "key"})
    assert list(problems) == ["name", "host", "key", "user"]


def test_no_schema_means_nothing_unmet() -> None:
    assert unmet_requirements(None, {}) == {}
    assert unmet_requirements({}, {"a": 1}) == {}
