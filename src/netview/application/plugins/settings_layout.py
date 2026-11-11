"""How a plugin's settings form is laid out, stated in its settings JSON schema.

Two keys on a property, both read by the web form (``schema-form.js``) and ignored by validation:

* ``group``: the titled section the field belongs to. Sections appear in the order of their first
  field; fields without a group come first, untitled.
* ``show_when``: the field is shown only while other fields hold the given values, for example
  ``{"snmp_version": "3"}``. A list means any one of those values. A hidden field keeps its value.

A plugin sets them through pydantic, ``Field(..., json_schema_extra=setting_group("SNMP v3",
show_when={"snmp_version": "3"}))``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def setting_group(name: str, show_when: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The ``json_schema_extra`` that puts a settings field in section ``name``, optionally conditional."""
    extra: dict[str, Any] = {"group": name}
    if show_when:
        extra["show_when"] = {k: list(v) if isinstance(v, list | tuple) else v for k, v in show_when.items()}
    return extra
