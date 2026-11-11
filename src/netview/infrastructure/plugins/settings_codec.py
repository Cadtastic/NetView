"""Secret-aware conversion of plugin settings.

Storage keeps real values, everything shown outside storage (API, logs, errors) shows MASK.
"""

import types
import typing
from typing import Any, Final

import pydantic
from pydantic import BaseModel, SecretStr

MASK: Final = "********"


def _unwrap(annotation: Any) -> Any:
    while typing.get_origin(annotation) is typing.Annotated:
        annotation = typing.get_args(annotation)[0]
    return annotation


def _is_secret(annotation: Any) -> bool:
    """A supported secret field: SecretStr, or a union holding it, either possibly Annotated."""
    annotation = _unwrap(annotation)
    if annotation is SecretStr:
        return True
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return any(_is_secret(arg) for arg in typing.get_args(annotation))
    return False


_UNION_KEYS: Final = ("anyOf", "oneOf", "allOf")


def _write_only_paths(node: Any, path: str) -> list[str]:
    """Every location under ``node`` that pydantic marks as a secret (``writeOnly``)."""
    found: list[str] = []
    if isinstance(node, dict):
        if node.get("writeOnly") is True:
            found.append(path)
        for key, child in node.items():
            found += _write_only_paths(child, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for i, child in enumerate(node):
            found += _write_only_paths(child, f"{path}[{i}]")
    return found


def unsupported_secrets(model: type[BaseModel]) -> list[str]:
    """Secret locations this codec cannot mask, so a plugin using them must not load (fail closed).

    Only a top-level ``SecretStr`` field (optionally in a union or Annotated) is masked. Any
    other secret the JSON schema reveals, such as SecretBytes, a secret inside a nested model,
    a list or a dict, is reported by its schema path.
    """
    schema = model.model_json_schema()
    supported = _secret_keys(model)
    bad: list[str] = []
    for name, prop in (schema.get("properties") or {}).items():
        base = f"properties.{name}"
        allowed = {base} | {
            f"{base}.{key}[{i}]" for key in _UNION_KEYS for i in range(len(prop.get(key) or ()))
        }
        for path in _write_only_paths(prop, base):
            if name not in supported or path not in allowed:
                bad.append(path)
    rest = {k: v for k, v in schema.items() if k != "properties"}
    bad += _write_only_paths(rest, "")
    return bad


def _secret_keys(model: type[BaseModel]) -> frozenset[str]:
    return frozenset(name for name, field in model.model_fields.items() if _is_secret(field.annotation))


def dump_for_storage(model: BaseModel) -> dict[str, Any]:
    """JSON-safe dict with SecretStr values revealed (for the plugin_state row only)."""
    out: dict[str, Any] = model.model_dump(mode="json")
    for key in _secret_keys(type(model)):
        value = getattr(model, key, None)
        out[key] = value.get_secret_value() if isinstance(value, SecretStr) else None
    return out


def dump_for_display(model: BaseModel) -> dict[str, Any]:
    """JSON-safe dict where a set secret is MASK and an unset one is None."""
    out: dict[str, Any] = model.model_dump(mode="json")
    for key in _secret_keys(type(model)):
        out[key] = None if getattr(model, key, None) is None else MASK
    return out


def merge_patch(stored: dict[str, Any], patch: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
    """Apply a PATCH to the stored settings. MASK, "" or a missing key keeps a stored secret."""
    merged = {**stored, **patch}
    for key in _secret_keys(model):
        if key not in patch or patch[key] == MASK or patch[key] == "":
            if key in stored:
                merged[key] = stored[key]
            else:
                merged.pop(key, None)
    return merged


def mask_raw(raw: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
    """Mask the secret keys of an unvalidated dict (disabled and failed plugins)."""
    out = dict(raw)
    for key in _secret_keys(model):
        if out.get(key) is not None:
            out[key] = MASK
    return out


def safe_validation_message(exc: pydantic.ValidationError) -> str:
    """Location and message of each error, never the offending input."""
    parts = [
        f"{'.'.join(str(p) for p in err['loc']) or 'settings'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    ]
    return "; ".join(parts)
