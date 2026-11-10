"""Nicknames."""

from dataclasses import dataclass

from netview.domain.errors import ValidationError

MAX_NICKNAME_LEN = 60


def normalize_nickname(raw: str | None) -> str | None:
    """Trim; empty becomes None; over-long values are rejected, not truncated."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > MAX_NICKNAME_LEN:
        raise ValidationError(f"nickname must be at most {MAX_NICKNAME_LEN} characters")
    return value


@dataclass(frozen=True)
class NicknameChange:
    """A nickname history entry. old/new use '' for none; by is free text."""

    key: str
    old: str
    new: str
    by: str
    t_ms: int
