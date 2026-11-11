"""Which settings a plugin needs before it can work, read from its settings JSON schema.

A plugin states its requirements in the schema itself, so the host (to decide whether the plugin
is configured and to reject an incomplete save) and the web form (to mark fields with an asterisk
and check them before saving) read one source of truth:

* the top-level ``required`` list: fields that must have a value;
* ``allOf`` entries of the form ``{"if": {"properties": {f: {"const": v} | {"enum": [...]}}},
  "then": {"required": [...], "properties": {f: {"const": v, "errorMessage": "..."}}}}``:
  fields that must have a value, or one fixed value, while other fields hold given values.

Pydantic puts fields without a default in ``required``. A plugin adds its own rules through the
model's ``json_schema_extra`` with :func:`settings_requirements`, :func:`required_when` and
:func:`fixed_when`. The web form evaluates the same subset (``schema-form.js``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

REQUIRED_MESSAGE = "Required"

Condition = Mapping[str, Any]
"""Field name to the value it must hold; a list or tuple means any one of those values."""


def _match(value: Any) -> dict[str, Any]:
    return {"enum": list(value)} if isinstance(value, list | tuple) else {"const": value}


def _if(condition: Condition) -> dict[str, Any]:
    return {
        "properties": {name: _match(value) for name, value in condition.items()},
        "required": list(condition),
    }


def required_when(condition: Condition, fields: Iterable[str]) -> dict[str, Any]:
    """A rule: ``fields`` must have a value while every field in ``condition`` holds its value."""
    return {"if": _if(condition), "then": {"required": list(fields)}}


def fixed_when(condition: Condition, field: str, value: Any, message: str | None = None) -> dict[str, Any]:
    """A rule: ``field`` must equal ``value`` while every field in ``condition`` holds its value."""
    rule: dict[str, Any] = {"const": value}
    if message:
        rule["errorMessage"] = message
    return {"if": _if(condition), "then": {"properties": {field: rule}}}


def settings_requirements(
    required: Iterable[str] = (), rules: Iterable[Mapping[str, Any]] = ()
) -> Callable[[dict[str, Any]], None]:
    """A pydantic ``json_schema_extra`` that adds ``required`` fields and ``allOf`` rules to the schema."""
    extra_required = list(required)
    extra_rules = [dict(r) for r in rules]

    def extend(schema: dict[str, Any]) -> None:
        names = list(schema.get("required") or [])
        names += [n for n in extra_required if n not in names]
        if names:
            schema["required"] = names
        if extra_rules:
            schema["allOf"] = [*(schema.get("allOf") or []), *extra_rules]

    return extend


def is_blank(value: Any) -> bool:
    """No value: None, an empty or whitespace-only string, or an empty list."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | tuple | dict):
        return len(value) == 0
    return False


def _default(schema: Mapping[str, Any], name: str) -> Any:
    prop = (schema.get("properties") or {}).get(name) or {}
    return prop.get("default")


def _holds(rule: Mapping[str, Any], value: Any) -> bool:
    if "const" in rule and value != rule["const"]:
        return False
    return not ("enum" in rule and value not in rule["enum"])


def _condition_holds(cond: Mapping[str, Any], values: Mapping[str, Any]) -> bool:
    for name in cond.get("required") or []:
        if name not in values:
            return False
    for name, rule in (cond.get("properties") or {}).items():
        if name in values and not _holds(rule, values[name]):
            return False
    return True


def _expected(rule: Mapping[str, Any]) -> str:
    if "const" in rule:
        return f"Must be {rule['const']!s}"
    return "Must be one of " + ", ".join(str(v) for v in rule.get("enum") or [])


def unmet_requirements(schema: Mapping[str, Any] | None, values: Mapping[str, Any]) -> dict[str, str]:
    """Field name to a short message for every requirement ``values`` does not meet.

    A field missing from ``values`` takes its schema default. Fields are reported in schema order
    and each one once (the first problem wins).
    """
    if not schema:
        return {}
    props = schema.get("properties") or {}
    full = {name: values[name] if name in values else _default(schema, name) for name in props}
    full.update({k: v for k, v in values.items() if k not in full})
    problems: dict[str, str] = {}

    def report(name: str, message: str) -> None:
        problems.setdefault(name, message)

    for name in schema.get("required") or []:
        if is_blank(full.get(name)):
            report(name, REQUIRED_MESSAGE)
    for rule in schema.get("allOf") or []:
        cond = rule.get("if")
        then = rule.get("then") or {}
        if not isinstance(cond, Mapping) or not _condition_holds(cond, full):
            continue
        for name in then.get("required") or []:
            if is_blank(full.get(name)):
                report(name, REQUIRED_MESSAGE)
        for name, fixed in (then.get("properties") or {}).items():
            if not _holds(fixed, full.get(name)):
                report(name, str(fixed.get("errorMessage") or _expected(fixed)))
    order = list(props)
    return dict(sorted(problems.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)))
