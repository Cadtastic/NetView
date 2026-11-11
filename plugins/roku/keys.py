"""Allow-lists for what NetView may send to a TV: remote keys, app ids and typed text."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import quote

KEYS: frozenset[str] = frozenset(
    {
        "Home",
        "Back",
        "Up",
        "Down",
        "Left",
        "Right",
        "Select",
        "Info",
        "InstantReplay",
        "Search",
        "Play",
        "Rev",
        "Fwd",
        "VolumeUp",
        "VolumeDown",
        "VolumeMute",
        "PowerOff",
        "PowerOn",
        "Power",
        "InputTuner",
        "InputHDMI1",
        "InputHDMI2",
        "InputHDMI3",
        "InputHDMI4",
        "InputAV1",
        "ChannelUp",
        "ChannelDown",
        "Backspace",
        "Enter",
        "FindRemote",
    }
)

MAX_TEXT_CHARS = 100

_ACTIONS = {"press": "keypress", "down": "keydown", "up": "keyup"}
_LIT_PREFIX = "Lit_"
# \Z, not $, so a trailing newline is not accepted.
_APP_ID = re.compile(r"(?:[0-9]{1,10}|tvinput\.(?:hdmi[1-4]|dtv|cvbs))\Z")


def key_path(key: str, action: Literal["press", "down", "up"] = "press") -> str:
    verb = _ACTIONS.get(action)
    if verb is None:
        raise ValueError(f"unknown key action: {action!r}")
    if key in KEYS:
        return f"/{verb}/{key}"
    if key.startswith(_LIT_PREFIX) and len(key) == len(_LIT_PREFIX) + 1:
        # One character, always percent-encoded: it could otherwise be / ? # or %.
        return f"/{verb}/{_LIT_PREFIX}{quote(key[-1], safe='')}"
    raise ValueError(f"key not allowed: {key!r}")


def app_path(app: str) -> str:
    if not _APP_ID.match(app):
        raise ValueError(f"app id not allowed: {app!r}")
    return f"/launch/{app}"


def text_paths(text: str) -> list[str]:
    if not 1 <= len(text) <= MAX_TEXT_CHARS:
        raise ValueError(f"text must be 1 to {MAX_TEXT_CHARS} characters")
    return [f"/keypress/{_LIT_PREFIX}{quote(ch, safe='')}" for ch in text]
