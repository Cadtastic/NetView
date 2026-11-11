import importlib.metadata
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sample_plugins.bad_sdk import BadSdkPlugin
from sample_plugins.good import GoodPlugin
from sample_plugins.undeclared import UndeclaredPlugin

from netview.application.plugins.validation import (
    validate_manifest,
    validate_providers,
    validate_storage,
)
from netview.infrastructure.plugins.discovery import discover_plugin_classes
from netview.sdk import SDK_VERSION, Capability, Permission, PluginManifest


def manifest(**overrides: Any) -> PluginManifest:
    values: dict[str, Any] = {
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "description": "",
        "sdk_version": ">=1.0,<2",
        "capabilities": frozenset({Capability.JOBS}),
        "permissions": frozenset({Permission.API}),
    }
    values.update(overrides)
    return PluginManifest(**values)


def test_valid_manifest_has_no_errors() -> None:
    assert validate_manifest(manifest(), SDK_VERSION, set()) == []


@pytest.mark.parametrize("bad_id", ["Demo", "1demo", "de-mo", "", "de mo"])
def test_invalid_ids_rejected(bad_id: str) -> None:
    errors = validate_manifest(manifest(id=bad_id), SDK_VERSION, set())
    assert any("id" in e for e in errors)


def test_sdk_version_mismatch_and_garbage_specifier() -> None:
    assert any("sdk" in e for e in validate_manifest(manifest(sdk_version=">=2"), SDK_VERSION, set()))
    assert any("sdk" in e for e in validate_manifest(manifest(sdk_version="not a spec"), SDK_VERSION, set()))


def test_duplicate_id_rejected() -> None:
    errors = validate_manifest(manifest(), SDK_VERSION, {"demo"})
    assert any("duplicate" in e for e in errors)


def test_unknown_capability_rejected() -> None:
    errors = validate_manifest(manifest(capabilities=frozenset({"teleport"})), SDK_VERSION, set())
    assert any("teleport" in e for e in errors)


def test_validate_storage_requires_plugin_prefix() -> None:
    metadata = sa.MetaData()
    sa.Table("demo_ok", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("other", metadata, sa.Column("id", sa.Integer, primary_key=True))
    errors = validate_storage("demo", metadata)
    assert len(errors) == 1
    assert "other" in errors[0]
    assert "prefix" in errors[0]


def test_validate_providers() -> None:
    assert validate_providers(GoodPlugin()) == []
    errors = validate_providers(UndeclaredPlugin())
    assert any("undeclared" in e and "traffic" in e for e in errors)
    assert validate_providers(BadSdkPlugin()) == []


def test_broken_entry_point_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEntryPoint:
        name = "broken"

        def load(self) -> Any:
            raise ImportError("no such module")

    def fake_entry_points(**kwargs: Any) -> list[BrokenEntryPoint]:
        assert kwargs == {"group": "netview.plugins"}
        return [BrokenEntryPoint()]

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)
    found = discover_plugin_classes()
    assert len(found) == 1
    assert found[0].cls is None
    assert found[0].error is not None
    assert "no such module" in found[0].error
    assert found[0].source == "entry_point:broken"


def test_a_folder_plugin_can_import_its_own_modules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real plugin is several files. Found in the browser: with no parent package the relative import failed."""
    import sys

    from netview.infrastructure.plugins.discovery import LOCAL_PACKAGE

    monkeypatch.setattr(importlib.metadata, "entry_points", lambda **_: [])
    for name in [m for m in sys.modules if m == LOCAL_PACKAGE or m.startswith(LOCAL_PACKAGE + ".")]:
        monkeypatch.delitem(sys.modules, name)
    folder = tmp_path / "splitplug"
    (folder / "parts").mkdir(parents=True)
    (folder / "__init__.py").write_text("from .plugin import P\nplugin_class = P\n", encoding="utf-8")
    (folder / "plugin.py").write_text(
        "from netview.sdk import Plugin, PluginManifest\n"
        "from .parts.name import NAME\n"
        "class P(Plugin):\n"
        "    manifest = PluginManifest('splitplug', NAME, '1', '', '>=1.0,<2', frozenset(), frozenset())\n"
        "    def setup(self, ctx): pass\n",
        encoding="utf-8",
    )
    (folder / "parts" / "__init__.py").write_text("", encoding="utf-8")
    (folder / "parts" / "name.py").write_text("NAME = 'Split'\n", encoding="utf-8")

    [found] = discover_plugin_classes(extra_dirs=[tmp_path])

    assert found.error is None
    assert found.cls is not None
    assert found.cls.manifest.name == "Split"
    for name in [m for m in sys.modules if m.startswith(LOCAL_PACKAGE + ".splitplug")]:
        monkeypatch.delitem(sys.modules, name)


def test_folder_plugins_discovered_and_failures_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda **_: [])
    ok = tmp_path / "okplug"
    ok.mkdir()
    (ok / "__init__.py").write_text(
        "from netview.sdk import Plugin, PluginManifest\n"
        "class P(Plugin):\n"
        "    manifest = PluginManifest('okplug', 'x', '1', '', '>=1.0,<2', frozenset(), frozenset())\n"
        "    def setup(self, ctx): pass\n"
        "plugin_class = P\n",
        encoding="utf-8",
    )
    crash = tmp_path / "crashplug"
    crash.mkdir()
    (crash / "__init__.py").write_text("raise RuntimeError('import boom')\n", encoding="utf-8")
    nocls = tmp_path / "nocls"
    nocls.mkdir()
    (nocls / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "not_a_plugin").mkdir()

    found = {
        Path(d.source.removeprefix("folder:")).name: d for d in discover_plugin_classes(extra_dirs=[tmp_path])
    }

    assert set(found) == {"okplug", "crashplug", "nocls"}
    assert found["okplug"].cls is not None
    assert found["okplug"].cls.__module__ == "netview_local_plugins.okplug"
    assert "import boom" in (found["crashplug"].error or "")
    assert "plugin_class" in (found["nocls"].error or "")
