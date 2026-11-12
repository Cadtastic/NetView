"""Uninstalling a plugin that lives directly in <data dir>/plugins (spec: uninstall)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import HostEnv

from netview.domain.errors import ConflictError, NotFoundError
from netview.infrastructure.db.engine import plugin_data_file
from netview.infrastructure.plugins.folders import TRASH, clear_trash, finish_pending_uninstalls
from netview.infrastructure.plugins.host import PluginHost

REPO = Path(__file__).resolve().parents[3]
ROKU = REPO / "plugins" / "roku"
ROKU_GUID = "241d4d28-4a70-406c-833c-a7b4d5b389a9"


def copy_roku(dest: Path) -> Path:
    shutil.copytree(ROKU, dest, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    return dest


def host_for(env: HostEnv, *bases: tuple[Path, int]) -> PluginHost:
    return env.host([], folder_bases=list(bases))


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """<data dir>/plugins; ``env.data_dir`` is ``tmp_path``."""
    return tmp_path / "plugins"


def data_files(env: HostEnv) -> list[Path]:
    db = plugin_data_file(env.data_dir, ROKU_GUID)
    return [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]


def state_exists(env: HostEnv) -> bool:
    with env.uow() as uow:
        return uow.plugin_state.get(ROKU_GUID) is not None


def test_uninstall_removes_folder_and_card(env: HostEnv, data: Path) -> None:
    folder = copy_roku(data / "roku")
    host = host_for(env, (data, 2))
    host.load_all()
    sid = env.id_of(ROKU_GUID)
    host.start_jobs()
    assert host.is_present(sid)

    result = host.uninstall("roku", False)

    assert (result.finished, result.error) == (True, None)
    assert not folder.exists()
    assert not any((data / TRASH).glob("*"))
    assert host.list() == []
    assert not host.is_present(sid)
    assert host.routers() == [] and host.ui_contributions() == []
    assert ("remove_owner", sid, "") in env.scheduler.calls
    assert not any(owner == sid for owner, _c, _p in env.registry._entries)
    with pytest.raises(NotFoundError):
        host.get(sid)


@pytest.mark.parametrize("name", ["..", ".", ".staging", ".trash", "", "a/b", "nope"])
def test_uninstall_refused_for_bad_names(env: HostEnv, data: Path, name: str) -> None:
    copy_roku(data / "roku")
    (data / ".staging").mkdir()
    host = host_for(env, (data, 2))
    host.load_all()
    with pytest.raises((ConflictError, NotFoundError)):
        host.uninstall(name, False)
    assert (data / "roku").exists()
    assert (data / ".staging").exists()
    assert host.get(env.id_of(ROKU_GUID)).state == "active"


def test_uninstall_refused_outside_data_dir(env: HostEnv, tmp_path: Path, data: Path) -> None:
    dirs = tmp_path / "dirs"
    copy_roku(dirs / "roku")
    data.mkdir()
    host = host_for(env, (data, 2), (dirs, 1))
    host.load_all()
    sid = env.id_of(ROKU_GUID)

    for ref in (
        str(dirs / "roku"),
        "../dirs/roku",
        "roku",
        sid,
        ROKU_GUID,
    ):  # a plugin_dirs plugin, however named
        with pytest.raises((ConflictError, NotFoundError)):
            host.uninstall(ref, False)
    with pytest.raises(ConflictError):
        host.uninstall(str(dirs / "roku"), False)
    assert (dirs / "roku" / "plugin.json").exists()
    assert host.get(sid).state == "active"


def test_uninstall_refused_for_builtin(env: HostEnv, data: Path) -> None:
    from sample_plugins.good import GoodPlugin

    data.mkdir()
    host = env.host([GoodPlugin], folder_bases=[(data, 2)])
    host.load_all()
    sid = env.id(GoodPlugin)
    for ref in (sid, "good", "test:GoodPlugin"):
        with pytest.raises((ConflictError, NotFoundError)):
            host.uninstall(ref, False)
    assert host.get(sid).state == "active"


def make_junction(link: Path, target: Path) -> bool:
    """A directory link ``link`` -> ``target``; False when the OS refuses."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
            )
            return out.returncode == 0
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def test_uninstall_refused_for_link_pointing_outside(env: HostEnv, tmp_path: Path, data: Path) -> None:
    outside = copy_roku(tmp_path / "elsewhere" / "roku")
    data.mkdir()
    link = data / "linked"
    if not make_junction(link, outside):
        pytest.skip("the OS refused to create a directory link")
    host = host_for(env, (data, 2))
    host.load_all()
    with pytest.raises(ConflictError):
        host.uninstall("linked", False)
    assert (outside / "plugin.json").exists() and (outside / "__init__.py").exists()


def test_keep_data_by_default(env: HostEnv, data: Path) -> None:
    copy_roku(data / "roku")
    host = host_for(env, (data, 2))
    host.load_all()
    sid = env.id_of(ROKU_GUID)
    host.set_enabled(sid, False)
    assert data_files(env)[0].exists()

    host.uninstall("roku", False)

    assert data_files(env)[0].exists()
    assert state_exists(env)

    copy_roku(data / "roku")  # reinstall
    again = host_for(env, (data, 2))
    again.load_all()
    info = again.get(env.id_of(ROKU_GUID))
    assert env.id_of(ROKU_GUID) == sid  # the registry row stayed
    assert info.id == sid
    assert info.enabled is False  # and so did its settings


def test_delete_data_removes_file_and_state(env: HostEnv, data: Path) -> None:
    copy_roku(data / "roku")
    host = host_for(env, (data, 2))
    host.load_all()
    sid = env.id_of(ROKU_GUID)
    db, wal, shm = data_files(env)
    assert db.exists() and state_exists(env)
    wal.write_bytes(b"x")  # leftovers a crashed plugin could leave
    shm.write_bytes(b"x")

    result = host.uninstall("roku", True)

    assert (result.finished, result.error) == (True, None)
    assert not any(p.exists() for p in data_files(env))
    assert not state_exists(env)
    with env.uow() as uow:
        assert uow.plugin_registry.source_id(ROKU_GUID) == int(sid)  # the number is kept


def test_delete_data_removes_partial_file_of_failed_plugin(env: HostEnv, data: Path) -> None:
    folder = copy_roku(data / "roku")
    (folder / "plugin.py").write_text("raise RuntimeError('broken')\n", encoding="utf-8")
    host = host_for(env, (data, 2))
    host.load_all()
    info = host.get(env.id_of(ROKU_GUID))
    assert info.state == "failed" and info.owns_data
    db = data_files(env)[0]
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"")  # what a failed migration can leave
    assert host.uninstall("roku", True).finished
    assert not db.exists()


def test_delete_data_refused_for_duplicate(env: HostEnv, tmp_path: Path, data: Path) -> None:
    dirs = tmp_path / "dirs"
    copy_roku(dirs / "roku")
    copy_roku(data / "aaa_roku")
    host = host_for(env, (data, 2), (dirs, 1))
    host.load_all()
    owner = host.get(env.id_of(ROKU_GUID))
    db = data_files(env)[0]
    assert owner.owns_data and db.exists() and state_exists(env)
    before = db.read_bytes()

    with pytest.raises(ConflictError):
        host.uninstall("aaa_roku", True)

    assert (data / "aaa_roku").exists()  # nothing was touched
    assert db.read_bytes() == before and state_exists(env)
    assert host.get(owner.id).state == "active"

    assert host.uninstall("aaa_roku", False).finished  # without delete_data the duplicate may go
    assert not (data / "aaa_roku").exists()
    assert db.exists() and state_exists(env)
    assert host.get(owner.id).state == "active" and host.is_present(owner.id)
    assert ("remove_owner", owner.id, "") not in env.scheduler.calls  # the owner's jobs were not stopped


def test_uninstall_pending_card(env: HostEnv, data: Path) -> None:
    data.mkdir()
    host = host_for(env, (data, 2))
    host.load_all()
    folder = copy_roku(data / "roku")
    [pending] = host.list()
    assert pending.state == "pending" and pending.folder == "roku"

    assert host.uninstall("roku", False).finished
    assert not folder.exists()
    assert host.list() == []

    copy_roku(data / "roku")
    with pytest.raises(ConflictError):  # not loaded here, so it is not known to own any saved data
        host.uninstall("roku", True)
    assert (data / "roku").exists()


def refuse_rename(self: Path, target: object) -> Path:
    raise PermissionError("in use")


def clear_in(env: HostEnv):  # type: ignore[no-untyped-def]
    def clear(entry: str) -> None:
        with env.uow() as uow:
            uow.plugin_registry.clear_pending_uninstall(entry)
            uow.commit()

    return clear


def test_rename_failure_marks_pending(env: HostEnv, data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = copy_roku(data / "roku")
    host = host_for(env, (data, 2))
    host.load_all()
    sid = env.id_of(ROKU_GUID)

    with monkeypatch.context() as m:
        m.setattr(Path, "rename", refuse_rename)
        result = host.uninstall("roku", True)

    assert result.finished is False
    assert result.error is not None and "in use" in result.error
    assert folder.exists()
    with env.uow() as uow:
        assert str(folder.resolve()) in uow.plugin_registry.pending_uninstalls()
    assert not host.is_present(sid)  # stopped all the same
    assert host.routers() == [] and host.ui_contributions() == []
    [card] = host.list()  # the card stays, stopped, and says why
    assert card.state == "failed" and card.uninstallable and not card.owns_data
    assert card.error == "Uninstall didn't finish: in use. It will be removed when netview restarts"
    assert not any(p.exists() for p in data_files(env)) and not state_exists(env)  # delete_data still applied

    with env.uow() as uow:  # the next start
        pending = uow.plugin_registry.pending_uninstalls()
    assert finish_pending_uninstalls(data, pending, clear_in(env)) == {}
    clear_trash(data)
    assert not folder.exists()
    with env.uow() as uow:
        assert uow.plugin_registry.pending_uninstalls() == []
    fresh = host_for(env, (data, 2))
    fresh.load_all()
    assert fresh.list() == []


def test_unmovable_pending_uninstall_is_never_loaded(
    env: HostEnv, data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = copy_roku(data / "roku")
    host = host_for(env, (data, 2))
    host.load_all()
    with monkeypatch.context() as m:
        m.setattr(Path, "rename", refuse_rename)
        assert host.uninstall("roku", False).finished is False
        with env.uow() as uow:  # the next start fails to move it as well
            pending = uow.plugin_registry.pending_uninstalls()
        unfinished = finish_pending_uninstalls(data, pending, clear_in(env))
    assert list(unfinished) == [folder.resolve()]
    with env.uow() as uow:
        assert uow.plugin_registry.pending_uninstalls() == pending  # still to do

    second = env.host([], folder_bases=[(data, 2)], unfinished_uninstalls=unfinished)
    second.load_all()
    second.start_jobs()
    [card] = second.list()
    assert card.state == "failed" and card.uninstallable and not card.owns_data
    assert card.error is not None and card.error.startswith("Uninstall didn't finish: in use")
    assert card.error.endswith("It will be removed when netview restarts")
    assert second.routers() == [] and second.ui_contributions() == []
    assert env.scheduler.calls.count(("add", "1", "")) == 0 and not env.registry._entries
    assert "netview_local_plugins.p1" not in sys.modules

    assert second.uninstall("roku", False).finished  # a retry works once the folder can be moved
    assert not folder.exists()
    assert second.list() == []
    with env.uow() as uow:
        assert uow.plugin_registry.pending_uninstalls() == []  # the record went with the folder

    copy_roku(data / "roku")  # reinstalled; the next start must not remove it
    with env.uow() as uow:
        again = uow.plugin_registry.pending_uninstalls()
    assert finish_pending_uninstalls(data, again, clear_in(env)) == {}
    assert (data / "roku" / "plugin.json").exists()
    third = host_for(env, (data, 2))
    third.load_all()
    assert third.get(env.id_of(ROKU_GUID)).state == "active"


def test_delete_data_refused_while_legacy_move_blocked(env: HostEnv, data: Path) -> None:
    folder = copy_roku(data / "roku")
    host = env.host([], folder_bases=[(data, 2)], blocked={ROKU_GUID: "disk full"})
    host.load_all()
    sid = env.id_of(ROKU_GUID)
    assert host.get(sid).state == "failed"

    with pytest.raises(ConflictError, match="still being moved"):
        host.uninstall("roku", True)
    assert folder.exists() and host.is_present(sid)  # nothing was stopped

    assert host.uninstall("roku", False).finished  # without delete_data it is allowed
    assert not folder.exists()


def test_finish_pending_ignores_entries_outside_base(tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    base.mkdir()
    outside = tmp_path / "keep"
    outside.mkdir()
    (outside / "f.txt").write_text("x")
    entries = [str(outside), "..", ".staging", "gone"]
    cleared: list[str] = []
    finish_pending_uninstalls(base, entries, cleared.append)
    assert (outside / "f.txt").exists()
    assert sorted(cleared) == sorted(entries)  # nothing there to retry


def test_clear_trash(tmp_path: Path) -> None:
    (tmp_path / TRASH / "roku-1").mkdir(parents=True)
    clear_trash(tmp_path)
    assert not (tmp_path / TRASH).exists()
