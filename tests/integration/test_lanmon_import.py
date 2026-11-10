import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from netview.application.ports.uow import UnitOfWork, UnitOfWorkFactory
from netview.application.usecases.nicknames import SetNickname
from netview.domain.errors import ValidationError
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.infrastructure.event_bus import InMemoryEventBus
from netview.infrastructure.lanmon_import import LanmonImporter
from netview.sdk.testing.fakes import FakeClock

FIXTURES = Path(__file__).parent.parent / "fixtures" / "lanmon"
KINDLE = "aa:bb:cc:00:00:01"


@pytest.fixture
def uow(tmp_path: Path) -> UnitOfWorkFactory:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    upgrade_core(engine)
    sessions = sessionmaker(engine)

    def make() -> UnitOfWork:
        return SqlUnitOfWork(sessions)  # type: ignore[return-value]

    return make


@pytest.fixture
def importer(uow: UnitOfWorkFactory) -> LanmonImporter:
    return LanmonImporter(uow, FakeClock())


@pytest.fixture
def copy_store(tmp_path: Path) -> Callable[[str], Path]:
    def copy(name: str) -> Path:
        target = tmp_path / name
        shutil.copyfile(FIXTURES / name, target)
        return target

    return copy


def test_import_basic_counts(
    importer: LanmonImporter, uow: UnitOfWorkFactory, copy_store: Callable[[str], Path]
) -> None:
    report = importer.run(copy_store("store_basic.json"))
    assert report.devices_added == 2
    assert report.devices_updated == 0
    assert report.nicknames_added == 2
    assert report.history_added == 4  # two from the file, two written by the import itself
    assert report.watches_added == 1
    assert report.conflicts == []
    with uow() as u:
        kindle = u.devices.get(KINDLE)
        assert kindle is not None
        assert kindle.status.value == "offline"
        assert kindle.ip == "192.168.1.20"
        assert kindle.first_seen_ms == 1797000000000
        assert u.nicknames.get(KINDLE) == "Jessi's Kindle"
        claims = u.identity.claims(KINDLE)
        assert [(c.name, c.source, c.rank) for c in claims] == [("kindle-jessi", "DHCP", 3.5)]
        assert [(t.type, t.source, t.reason) for t in u.identity.types(KINDLE)] == [
            ("e-reader", "lan_monitor", "imported")
        ]
        assert [w.spec() for w in u.watches.list()] == ["192.168.1.128:443,22=R720 iDRAC"]
        assert {h.by for h in u.nicknames.history(KINDLE)} == {"user", "import: lan_monitor"}


def test_import_is_idempotent(importer: LanmonImporter, copy_store: Callable[[str], Path]) -> None:
    path = copy_store("store_basic.json")
    importer.run(path)
    again = importer.run(path)
    assert (
        again.devices_added,
        again.devices_updated,
        again.nicknames_added,
        again.history_added,
        again.watches_added,
    ) == (0, 0, 0, 0, 0)
    assert again.conflicts == []


def test_import_widens_existing_device_times_only(
    importer: LanmonImporter, uow: UnitOfWorkFactory, copy_store: Callable[[str], Path]
) -> None:
    path = copy_store("store_basic.json")
    importer.run(path)
    with uow() as u:
        d = u.devices.get(KINDLE)
        assert d is not None
        d.first_seen_ms = 1798000000000  # later than the file says
        d.last_seen_ms = 1799500000000  # later than the file says
        d.ip = "192.168.1.99"
        u.devices.save(d)
        u.commit()
    report = importer.run(path)
    assert report.devices_updated == 1
    with uow() as u:
        d = u.devices.get(KINDLE)
        assert d is not None
        assert d.first_seen_ms == 1797000000000  # widened down
        assert d.last_seen_ms == 1799500000000  # kept
        assert d.ip == "192.168.1.99"  # untouched


def _existing_nickname(uow: UnitOfWorkFactory, path: Path, nickname: str) -> LanmonImporter:
    """Import once, then change the Kindle's nickname through the real use case."""
    clock = FakeClock()
    importer = LanmonImporter(uow, clock)
    importer.run(path)
    clock.advance(1000)
    SetNickname(uow, clock, InMemoryEventBus())(KINDLE, nickname)
    return importer


def test_import_never_overwrites_existing_nickname(
    uow: UnitOfWorkFactory, copy_store: Callable[[str], Path]
) -> None:
    path = copy_store("store_basic.json")
    importer = _existing_nickname(uow, path, "Mine")
    report = importer.run(path)
    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert (conflict.key, conflict.netview, conflict.source) == (KINDLE, "Mine", "Jessi's Kindle")
    assert report.nicknames_added == 0
    with uow() as u:
        assert u.nicknames.get(KINDLE) == "Mine"


def test_prefer_source_overwrites_with_history(
    uow: UnitOfWorkFactory, copy_store: Callable[[str], Path]
) -> None:
    path = copy_store("store_basic.json")
    importer = _existing_nickname(uow, path, "Mine")
    report = importer.run(path, prefer_source=True)
    assert report.conflicts == []
    with uow() as u:
        assert u.nicknames.get(KINDLE) == "Jessi's Kindle"
        entries = [h for h in u.nicknames.history(KINDLE) if h.by.endswith("(prefer source)")]
        assert len(entries) == 1
        assert (entries[0].old, entries[0].new) == ("Mine", "Jessi's Kindle")
        assert entries[0].by == "import: lan_monitor (prefer source)"


def test_import_odd_store(
    importer: LanmonImporter, uow: UnitOfWorkFactory, copy_store: Callable[[str], Path]
) -> None:
    path = copy_store("store_odd.json")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    report = importer.run(path)
    assert report.devices_added == 2
    assert report.nicknames_added == 1  # the empty label sets nothing
    with uow() as u:
        assert u.nicknames.get("aa:bb:cc:00:00:02") is None
        assert u.nicknames.get("aa:bb:cc:00:00:03") == "Café <b>"  # stored exactly as typed
        assert u.identity.claims("aa:bb:cc:00:00:02") == []  # known entry without a name
        from_file = {h.key: h for h in u.nicknames.history() if not h.by.startswith("import:")}
        assert from_file["aa:bb:cc:00:00:03"].by == "lan_monitor"  # defaulted
        assert from_file["aa:bb:cc:00:00:02"].by == "claude: cleared auto-written nickname"  # kept
        assert from_file["aa:bb:cc:00:00:02"].new == ""


def test_import_does_not_modify_source(importer: LanmonImporter, copy_store: Callable[[str], Path]) -> None:
    path = copy_store("store_basic.json")
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    importer.run(path)
    importer.run(path, prefer_source=True)
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_import_rejects_unknown_schema(importer: LanmonImporter, tmp_path: Path) -> None:
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"schema": "something.else@1", "known": {}}), encoding="utf-8")
    with pytest.raises(ValidationError):
        importer.run(path)
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValidationError):
        importer.run(path)


def test_dry_run_writes_nothing(
    importer: LanmonImporter, uow: UnitOfWorkFactory, copy_store: Callable[[str], Path]
) -> None:
    path = copy_store("store_basic.json")
    report = importer.run(path, dry_run=True)
    assert report.devices_added == 2
    assert report.nicknames_added == 2
    with uow() as u:
        assert u.devices.list() == []
        assert u.nicknames.all() == {}
        assert u.watches.list() == []
        assert u.nicknames.history() == []
    real = importer.run(path)
    assert real.devices_added == 2  # the dry run left nothing behind
