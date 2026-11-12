"""Runtime keys are ``str(source_id)``; saved state is keyed by guid (spec section 4)."""

import shutil
from pathlib import Path

from conftest import HostEnv
from sample_plugins.good import GoodPlugin

REPO = Path(__file__).resolve().parents[3]
ROKU = REPO / "plugins" / "roku"
ROKU_GUID = "241d4d28-4a70-406c-833c-a7b4d5b389a9"


def copy_roku(dest: Path) -> Path:
    shutil.copytree(ROKU, dest, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    return dest


def host_for(env: HostEnv, *bases: tuple[Path, int]):  # type: ignore[no-untyped-def]
    return env.host([], folder_bases=list(bases))


def test_info_keys(env: HostEnv, tmp_path: Path) -> None:
    data = tmp_path / "plugins"
    copy_roku(data / "roku")
    host = host_for(env, (data, 2))
    host.load_all()

    [info] = host.list()
    sid = env.id_of(ROKU_GUID)
    assert info.id == sid == str(info.source_id)
    assert info.guid == ROKU_GUID
    assert info.ui_module is not None and info.ui_module.startswith(f"/plugins/{sid}/static/")
    assert [key for key, _ in host.routers()] == [sid]
    assert [key for key, _ in host.ui_contributions()] == [sid]
    assert [owner for owner, _cap, _prov in env.registry._entries] == [sid] * len(env.registry._entries)
    host.start_jobs()
    assert {owner for kind, owner, _ in env.scheduler.calls if kind == "add"} == {sid}
    assert host.guids() == {sid: ROKU_GUID}
    assert host.guid_of(sid) == ROKU_GUID
    assert (info.display_name, info.plugin_type) == ("Roku", "tv")


def test_state_keyed_by_guid(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    sid = env.id(GoodPlugin)

    host.set_enabled(sid, False)

    with env.uow() as uow:
        state = uow.plugin_state.get(GoodPlugin.manifest.guid)
        assert state is not None and state.enabled is False
        assert uow.plugin_state.get(sid) is None
        assert uow.plugin_state.get("good") is None


def test_seed_by_guid(env: HostEnv) -> None:
    guid = GoodPlugin.manifest.guid
    host = env.host([GoodPlugin], {guid: {"level": 4}, "good": {"level": 8}})
    host.load_all()
    assert host.get(env.id(GoodPlugin)).settings == {"level": 4}  # the legacy-id seed is ignored


def test_uninstallable_only_in_data_dir(env: HostEnv, tmp_path: Path) -> None:
    data = tmp_path / "data" / "plugins"
    dirs = tmp_path / "dirs"
    copy_roku(data / "roku")
    in_data = host_for(env, (data, 2))
    in_data.load_all()
    [info] = in_data.list()
    assert info.uninstallable is True and info.folder == "roku"

    other = tmp_path / "other"
    copy_roku(dirs / "roku")
    in_dirs = host_for(env, (other, 2), (dirs, 1))
    in_dirs.load_all()
    [info] = in_dirs.list()
    assert info.uninstallable is False and info.folder is None

    builtin = env.host([GoodPlugin])
    builtin.load_all()
    [info] = builtin.list()
    assert info.uninstallable is False and info.folder is None


def test_owns_data_winner_only(env: HostEnv, tmp_path: Path) -> None:
    data = tmp_path / "data" / "plugins"
    dirs = tmp_path / "dirs"
    copy_roku(dirs / "roku")
    copy_roku(data / "aaa_roku")
    host = host_for(env, (data, 2), (dirs, 1))
    host.load_all()

    winner = host.get(env.id_of(ROKU_GUID))
    [loser] = [i for i in host.list() if i is not winner]
    assert (winner.owns_data, winner.uninstallable) == (True, False)  # it lives in plugin_dirs
    assert (loser.owns_data, loser.uninstallable) == (False, True)  # a failed card in the data dir
    assert loser.folder == "aaa_roku"
    assert loser.source_id == winner.source_id  # same guid, same number; but its id is its card key
    assert loser.id == loser.card_key != winner.id


def test_a_loser_cannot_change_the_winners_state(env: HostEnv, tmp_path: Path) -> None:
    import pytest

    from netview.domain.errors import ConflictError

    data = tmp_path / "data" / "plugins"
    dirs = tmp_path / "dirs"
    copy_roku(dirs / "roku")
    copy_roku(data / "aaa_roku")
    host = host_for(env, (data, 2), (dirs, 1))
    host.load_all()
    winner = host.get(env.id_of(ROKU_GUID))
    [loser] = [i for i in host.list() if i is not winner]

    with pytest.raises(ConflictError):
        host.set_enabled(loser.id, False)

    with env.uow() as uow:
        state = uow.plugin_state.get(ROKU_GUID)
        assert state is not None and state.enabled is True
