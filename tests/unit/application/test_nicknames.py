import pytest
from usecase_helpers import World, seen

from netview.application.usecases.nicknames import SetNickname
from netview.domain.errors import NotFoundError, ValidationError

MAC = "90:39:5f:00:00:01"


def _world() -> tuple[World, SetNickname]:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    return w, SetNickname(w.uow, w.clock, w.bus)


def test_set_nickname_records_history_and_event() -> None:
    w, set_nickname = _world()
    assert set_nickname(MAC, "  Kindle ", by="me") == "Kindle"
    with w.uow() as uow:
        assert uow.nicknames.get(MAC) == "Kindle"
        (change,) = uow.nicknames.history(MAC)
        assert (change.old, change.new, change.by) == ("", "Kindle", "me")
    assert w.kinds() == ["nickname"]


def test_set_nickname_unchanged_is_noop() -> None:
    w, set_nickname = _world()
    set_nickname(MAC, "Kindle")
    set_nickname(MAC, " Kindle ")
    with w.uow() as uow:
        assert len(uow.nicknames.history()) == 1
    assert w.kinds() == ["nickname"]


def test_clearing_nickname_records_history() -> None:
    w, set_nickname = _world()
    set_nickname(MAC, "Kindle")
    w.clock.advance(1000)
    assert set_nickname(MAC, "  ") is None
    with w.uow() as uow:
        assert uow.nicknames.get(MAC) is None
        assert uow.nicknames.history(MAC)[0].new == ""
    set_nickname(MAC, None)  # already empty: no-op
    assert w.kinds() == ["nickname", "nickname"]


def test_set_nickname_unknown_key_raises_not_found() -> None:
    _, set_nickname = _world()
    with pytest.raises(NotFoundError):
        set_nickname("aa:aa:aa:aa:aa:aa", "x")


def test_set_nickname_too_long_is_rejected_and_nothing_stored() -> None:
    w, set_nickname = _world()
    with pytest.raises(ValidationError):
        set_nickname(MAC, "x" * 61)
    with w.uow() as uow:
        assert uow.nicknames.get(MAC) is None
    assert w.kinds() == []


@pytest.mark.parametrize("text", ["Café <b>", "Jessi's Kindle", '<script>alert("x")</script>', "日本語"])
def test_set_nickname_stores_exact_text(text: str) -> None:
    """Review focus 2."""
    w, set_nickname = _world()
    assert set_nickname(MAC, text) == text
    with w.uow() as uow:
        assert uow.nicknames.get(MAC) == text
        assert uow.nicknames.history(MAC)[0].new == text
