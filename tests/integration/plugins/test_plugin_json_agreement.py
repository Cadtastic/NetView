import json
from pathlib import Path

import pytest
from conftest import import_folders

from netview.application.plugins.plugin_json import parse_plugin_json

PLUGINS = Path(__file__).resolve().parents[3] / "plugins"
JSON_FILES = sorted(PLUGINS.glob("*/plugin.json"))


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.parent.name)
def test_plugin_json_matches_manifest(path: Path) -> None:
    pj = parse_plugin_json(json.loads(path.read_text(encoding="utf-8")))
    found = [d.cls for d in import_folders(PLUGINS) if d.cls is not None]
    cls = next(c for c in found if c.manifest.guid == pj.guid)
    m = cls.manifest
    assert (
        pj.name,
        pj.version,
        pj.description,
        pj.guid,
        pj.display_name,
        pj.plugin_type,
        pj.sdk_version,
    ) == (
        m.name,
        m.version,
        m.description,
        m.guid,
        m.display_name,
        m.plugin_type.value,
        m.sdk_version,
    )
    assert pj.capabilities == tuple(sorted(c.value for c in m.capabilities))
    assert pj.permissions == tuple(sorted(p.value for p in m.permissions))


def test_plugin_json_files_exist() -> None:
    assert {p.parent.name for p in JSON_FILES} >= {"gs105e", "gsm7248", "roku", "starlink"}


def test_every_loadable_folder_plugin_has_plugin_json() -> None:
    for folder in sorted(p for p in PLUGINS.iterdir() if p.is_dir() and (p / "__init__.py").is_file()):
        assert (folder / "plugin.json").is_file(), f"{folder.name} has no plugin.json"
