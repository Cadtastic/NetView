"""Theme catalog port."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ThemeInfo:
    id: str
    name: str
    scheme: str
    preview: list[str]
    source: Literal["built-in", "user"]
    url: str
    error: str | None = None


class ThemeCatalog(Protocol):
    def list(self) -> list[ThemeInfo]:
        """Built-in themes first (daylight, graphite, harbor, contrast, then the rest), then user themes."""
        ...

    def user_dir(self) -> str:
        """The folder users drop their own theme files into."""
        ...
