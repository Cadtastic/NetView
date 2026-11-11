import pytest
from usecase_helpers import SELF_IP, World, seen

from netview.application.usecases.forget import ForgetDevice
from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.nicknames import SetNickname
from netview.domain.errors import NotFoundError, ValidationError
from netview.domain.events import EventKind
from netview.domain.keys import SELF_KEY
from netview.domain.naming import Hint, NameClaim, TypeClaim

MAC = "90:39:5f:00:00:01"


def test_forget_deletes_device_and_identity_but_keeps_nickname() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    SetNickname(w.uow, w.clock, w.bus)(MAC, "Desk lamp")
    ClaimIdentity(w.uow, w.bus)(
        [NameClaim(MAC, "lamp", "DNS", 1, 5), TypeClaim(MAC, "iot", "oui", "a"), Hint(MAC, "hint", "a")]
    )
    ForgetDevice(w.uow, w.bus, w.clock)(MAC)
    with w.uow() as uow:
        assert uow.devices.get(MAC) is None
        assert uow.identity.claims(MAC) == []
        assert uow.identity.types(MAC) == []
        assert uow.identity.hints(MAC) == []
        assert uow.nicknames.get(MAC) == "Desk lamp"
        assert [c.new for c in uow.nicknames.history(MAC)] == ["Desk lamp"]
        assert uow.events.recent()[0].kind is EventKind.FORGOTTEN
        assert uow.events.recent()[0].key == MAC
    assert w.bus.published[-1].kind is EventKind.FORGOTTEN


def test_returning_device_gets_its_nickname_back() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    SetNickname(w.uow, w.clock, w.bus)(MAC, "Desk lamp")
    ForgetDevice(w.uow, w.bus, w.clock)(MAC)
    w.record([seen("192.168.1.10", MAC)])
    with w.uow() as uow:
        assert uow.devices.get(MAC) is not None
        assert uow.nicknames.get(MAC) == "Desk lamp"


def test_forget_unknown_device_raises_not_found() -> None:
    w = World()
    with pytest.raises(NotFoundError):
        ForgetDevice(w.uow, w.bus, w.clock)("aa:bb:cc:00:00:99")
    assert w.kinds() == []


def test_forget_self_is_refused() -> None:
    w = World()
    w.record([seen(SELF_IP)])
    with pytest.raises(ValidationError, match="this device cannot be forgotten"):
        ForgetDevice(w.uow, w.bus, w.clock)(SELF_KEY)
    with w.uow() as uow:
        assert uow.devices.get(SELF_KEY) is not None
        assert uow.events.recent() == []
    assert w.kinds() == []
