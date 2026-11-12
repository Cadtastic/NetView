import json
import shutil
import sys
from pathlib import Path

import pytest
from conftest import HostEnv

from netview.infrastructure.plugins.discovery import find_folders

REPO = Path(__file__).resolve().parents[3]
ROKU = REPO / "plugins" / "roku"
ROKU_GUID = "241d4d28-4a70-406c-833c-a7b4d5b389a9"


def copy_roku(dest: Path) -> Path:
    shutil.copytree(ROKU, dest, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    return dest


def host_for(env: HostEnv, *bases: tuple[Path, int]):  # type: ignore[no-untyped-def]
    return env.host([], folder_bases=list(bases))


def test_renamed_copy_never_displaces_original(env: HostEnv, tmp_path: Path) -> None:
    dirs = tmp_path / "dirs"
    data = tmp_path / "data" / "plugins"
    original = copy_roku(dirs / "roku")
    copy = copy_roku(data / "aaa_roku")
    host = host_for(env, (data, 2), (dirs, 1))
    host.load_all()
    infos = host.list()
    roku = next(i for i in infos if i.id == "roku")
    assert roku.state == "active"
    [dup] = [i for i in infos if i.id != "roku"]
    assert dup.state == "failed"
    assert dup.error is not None and dup.error.startswith("Same guid as Roku")
    assert str(original.resolve()) in dup.error
    assert copy.exists()


def test_folder_name_irrelevant(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    copy_roku(base / "whatever")
    host = host_for(env, (base, 1))
    host.load_all()
    assert host.get("roku").state == "active"
    with env.uow() as uow:
        n = uow.plugin_registry.source_id(ROKU_GUID)
    assert n is not None
    assert f"netview_local_plugins.p{n}" in sys.modules


def test_missing_plugin_json_fails_card(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    folder = copy_roku(base / "roku")
    (folder / "plugin.json").unlink()
    host = host_for(env, (base, 1))
    host.load_all()
    [info] = host.list()
    assert info.state == "failed"
    assert info.error == "plugin.json is missing or invalid"


def test_manifest_plugin_json_mismatch_fails(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    folder = copy_roku(base / "roku")
    path = folder / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = "9.9.9"
    path.write_text(json.dumps(data), encoding="utf-8")
    host = host_for(env, (base, 1))
    host.load_all()
    info = host.get("roku")
    assert info.state == "failed"
    assert info.error == "plugin.json and the manifest disagree on: version"
    assert host.plugin("roku") is None


def test_last_folder_recorded(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    folder = copy_roku(base / "roku")
    host_for(env, (base, 1)).load_all()
    with env.uow() as uow:
        assert uow.plugin_registry.last_folders() == {ROKU_GUID: str(folder.resolve())}


def test_find_folders_imports_nothing(tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    copy_roku(base / "roku")
    before = set(sys.modules)
    [cand] = find_folders([(base, 2)])
    assert cand.tier == 2 and cand.plugin_json is not None and cand.plugin_json.guid == ROKU_GUID
    assert not [m for m in set(sys.modules) - before if m.startswith("netview_local_plugins")]


@pytest.mark.parametrize("name", [".hidden"])
def test_dot_folders_skipped(tmp_path: Path, name: str) -> None:
    copy_roku(tmp_path / name)
    assert find_folders([(tmp_path, 1)]) == []


def test_builtin_winner_gets_a_source_id(env: HostEnv) -> None:
    from sample_plugins.good import GoodPlugin

    env.host([GoodPlugin]).load_all()
    with env.uow() as uow:
        assert uow.plugin_registry.source_id(GoodPlugin.manifest.guid) is not None
