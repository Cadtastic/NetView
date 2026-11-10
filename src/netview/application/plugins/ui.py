"""Plugin UI and storage contributions."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UiContribution:
    static_dir: Path
    module: str = "ui.js"


@dataclass(frozen=True)
class StorageSpec:
    metadata: Any
    versions_dir: Path
