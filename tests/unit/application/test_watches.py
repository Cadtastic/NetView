import pytest
from usecase_helpers import World

from netview.application.usecases.watches import AddWatch, RemoveWatch
from netview.domain.errors import ValidationError
from netview.domain.watch import Watch


def test_add_watch_stores_and_announces() -> None:
    w = World()
    watch = AddWatch(w.uow, w.bus, w.clock)("192.168.1.1:80,443=Router")
    assert watch == Watch("192.168.1.1", (80, 443), "Router")
    with w.uow() as uow:
        assert uow.watches.list() == [watch]
    assert w.kinds() == ["watch"]


def test_add_watch_without_clock_still_works() -> None:
    w = World()
    AddWatch(w.uow, w.bus)("192.168.1.1")
    assert w.bus.published[0].t_ms > 0


def test_add_watch_invalid_spec_changes_nothing() -> None:
    w = World()
    with pytest.raises(ValidationError):
        AddWatch(w.uow, w.bus, w.clock)("not-an-ip")
    assert w.kinds() == []


def test_remove_watch() -> None:
    w = World()
    AddWatch(w.uow, w.bus, w.clock)("192.168.1.1")
    remove = RemoveWatch(w.uow, w.bus, w.clock)
    assert remove("192.168.1.1") is True
    assert remove("192.168.1.1") is False
    with w.uow() as uow:
        assert uow.watches.list() == []
    assert w.kinds() == ["watch", "watch"]
