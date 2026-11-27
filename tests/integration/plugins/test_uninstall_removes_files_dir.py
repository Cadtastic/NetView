"""Uninstalling with "delete data" also removes the plugin's files folder."""

import shutil
from pathlib import Path

import pytest
from conftest import HostEnv

from netview.infrastructure.db.engine import plugin_data_file, plugin_files_dir
from netview.infrastructure.plugins.host import PluginHost

REPO = Path(__file__).resolve().parents[3]
ROKU = REPO / "plugins" / "roku"
ROKU_GUID = "241d4d28-4a70-406c-833c-a7b4d5b389a9"


def _host(env: HostEnv, tmp_path: Path) -> PluginHost:
    data = tmp_path / "plugins"
    shutil.copytree(ROKU, data / "roku", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    host = env.host([], folder_bases=[(data, 2)])
    host.load_all()
    return host


def _fill_files_dir(env: HostEnv) -> Path:
    files = plugin_files_dir(env.data_dir, ROKU_GUID)
    (files / "a").mkdir(parents=True)
    (files / "a" / "b.bin").write_bytes(b"x")
    return files


def test_uninstall_removes_files_dir(env: HostEnv, tmp_path: Path) -> None:
    host = _host(env, tmp_path)
    files = _fill_files_dir(env)
    db = plugin_data_file(env.data_dir, ROKU_GUID)
    assert db.exists()

    result = host.uninstall("roku", True)

    assert (result.finished, result.error) == (True, None)
    assert not files.exists()
    assert not db.exists()


def test_uninstall_keeps_files_dir_without_delete_data(env: HostEnv, tmp_path: Path) -> None:
    host = _host(env, tmp_path)
    files = _fill_files_dir(env)
    assert host.uninstall("roku", False).finished
    assert files.exists()


def test_uninstall_reports_undeletable_files(
    env: HostEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _host(env, tmp_path)
    _fill_files_dir(env)

    real_rmtree = shutil.rmtree
    files = plugin_files_dir(env.data_dir, ROKU_GUID)

    def rmtree(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path) == files:
            raise PermissionError("locked")
        real_rmtree(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("netview.infrastructure.plugins.host.shutil.rmtree", rmtree)

    result = host.uninstall("roku", True)

    assert result.finished is True
    assert result.error is not None
    assert result.error.startswith("its saved data was not fully deleted")
