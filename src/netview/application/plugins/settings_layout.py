"""How a plugin's settings form is laid out, stated in its settings JSON schema.

Two keys on a property, both read by the web form (``schema-form.js``) and ignored by validation:

* ``group``: the titled section the field belongs to. Sections appear in the order of their first
  field; fields without a group come first, untitled.
* ``show_when``: the field is shown only while other fields hold the given values, for example
  ``{"snmp_version": "3"}``. A list means any one of those values. A hidden field keeps its value.

* ``tab``: the tab of the form the field's section sits on. A form shows tabs only when at least one
  field names one; fields without a tab then go on a "General" tab.

* ``enum_labels``: on an enum (``Literal``) field, ``{value: "display text"}``. The form's drop-down shows
  the text; the stored value stays the raw one. A value without a label shows itself.

One key on the schema itself: ``tabs``, the order of the tabs. Tabs it does not list follow in the
order of their first field.

A plugin sets them through pydantic, ``Field(..., json_schema_extra=setting_group("SNMP v3",
show_when={"snmp_version": "3"}, tab="SNMP"))`` and ``ConfigDict(json_schema_extra=settings_tabs(
["General", "SNMP"]))``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


def setting_group(
    name: str, show_when: Mapping[str, Any] | None = None, tab: str | None = None
) -> dict[str, Any]:
    """The ``json_schema_extra`` that puts a settings field in section ``name``, optionally conditional
    and optionally on tab ``tab``."""
    extra: dict[str, Any] = {"group": name}
    if show_when:
        extra["show_when"] = {k: list(v) if isinstance(v, list | tuple) else v for k, v in show_when.items()}
    if tab:
        extra["tab"] = tab
    return extra


def settings_tabs(
    names: Sequence[str], then: Callable[[dict[str, Any]], None] | None = None
) -> Callable[[dict[str, Any]], None]:
    """A model-level ``json_schema_extra`` that fixes the order of the settings form's tabs.

    A model has one ``json_schema_extra``: pass the other one (``settings_requirements(...)``) as ``then``.
    """
    order = list(names)

    def extend(schema: dict[str, Any]) -> None:
        schema["tabs"] = list(order)
        if then is not None:
            then(schema)

    return extend
