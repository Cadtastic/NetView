"""A permission a plugin offers to NetView's role editor (SDK 1.5)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UserPermission:
    id: str
    label: str
    description: str = ""
    dangerous: bool = False
