"""A saved dashboard layout: which cards and tiles show, in what order, how wide, and how grouped."""

import json
import re
from dataclasses import dataclass

from netview.domain.errors import ValidationError

LAYOUT_VERSION = 1
GROUPS = ("none", "plugin", "plugin_type")
SPANS = ("third", "half", "full")
KEY_RE = re.compile(r"^(core|[0-9a-f-]{36})\.(tile|card)\.[A-Za-z0-9_.-]{1,100}$")
MAX_KEYS = 500
MAX_BYTES = 65536


ECHO_CHARS = 40


def _short(value: object) -> str:
    """A rejected key as it may appear in an error message: never more than ECHO_CHARS characters of it."""
    text = str(value)
    return repr(text if len(text) <= ECHO_CHARS else text[:ECHO_CHARS] + "…")


@dataclass(frozen=True)
class DashboardLayout:
    order: tuple[str, ...]
    hidden: tuple[str, ...]
    spans: tuple[tuple[str, str], ...]
    group: str


def _key_list(raw: object, field: str, problems: dict[str, str]) -> tuple[str, ...]:
    if not isinstance(raw, list):
        problems[field] = f"{field} must be a list"
        return ()
    if len(raw) > MAX_KEYS:  # refuse before looking at a single entry
        problems[field] = f"{field} holds {len(raw)} keys; the most allowed is {MAX_KEYS}"
        return ()
    seen: dict[str, None] = {}
    for item in raw:
        if not isinstance(item, str) or not KEY_RE.fullmatch(item):
            problems[field] = f"{field} holds a key that is not valid: {_short(item)}"
            return ()
        seen.setdefault(item)
    return tuple(seen)


def parse_layout(raw: object) -> DashboardLayout:
    """Validate ``raw`` (decoded JSON); raise ValidationError naming each bad field."""
    if not isinstance(raw, dict):
        raise ValidationError("the layout must be an object", {"layout": "the layout must be an object"})
    problems: dict[str, str] = {}
    if raw.get("version") != LAYOUT_VERSION or isinstance(raw.get("version"), bool):
        problems["version"] = f"version must be {LAYOUT_VERSION}"
    order = _key_list(raw.get("order"), "order", problems)
    hidden = _key_list(raw.get("hidden"), "hidden", problems)

    spans: list[tuple[str, str]] = []
    raw_spans = raw.get("spans")
    if not isinstance(raw_spans, dict):
        problems["spans"] = "spans must be an object"
    elif len(raw_spans) > MAX_KEYS:
        problems["spans"] = f"spans holds {len(raw_spans)} keys; the most allowed is {MAX_KEYS}"
    else:
        for key, span in raw_spans.items():
            if not isinstance(key, str) or not KEY_RE.fullmatch(key) or span not in SPANS:
                problems["spans"] = f"spans holds an entry that is not valid: {_short(key)}"
                spans = []
                break
            spans.append((key, span))

    group = raw.get("group")
    if group not in GROUPS:
        problems["group"] = f"group must be one of {', '.join(GROUPS)}"
    if not problems:
        count = len(order) + len(hidden) + len(spans)
        if count > MAX_KEYS:
            problems["layout"] = f"the layout holds {count} keys; the most allowed is {MAX_KEYS}"
    if problems:
        raise ValidationError("the layout is not valid", problems)

    layout = DashboardLayout(order, hidden, tuple(spans), str(group))
    if len(layout_to_json(layout).encode("utf-8")) > MAX_BYTES:
        raise ValidationError(
            "the layout is too large", {"layout": f"the layout is larger than {MAX_BYTES} bytes"}
        )
    return layout


def layout_to_dict(layout: DashboardLayout) -> dict[str, object]:
    return {
        "version": LAYOUT_VERSION,
        "order": list(layout.order),
        "hidden": list(layout.hidden),
        "spans": dict(layout.spans),
        "group": layout.group,
    }


def layout_to_json(layout: DashboardLayout) -> str:
    return json.dumps(layout_to_dict(layout), sort_keys=True, separators=(",", ":"))
