from usecase_helpers import World, seen

from netview.application.usecases.identity import ClaimIdentity
from netview.domain.naming import Hint, NameClaim, TypeClaim

MAC = "90:39:5f:00:00:01"


def _world() -> tuple[World, ClaimIdentity]:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    return w, ClaimIdentity(w.uow, w.bus)


def test_claim_identity_name_event_only_on_change() -> None:
    w, claim = _world()
    claim([NameClaim(MAC, "printer", "DNS", 1, 10)])
    assert w.kinds() == ["name"]
    claim([NameClaim(MAC, "printer", "DNS", 1, 20)])  # same name again
    assert w.kinds() == ["name"]
    claim([NameClaim(MAC, "other", "mDNS", 3, 30)])  # higher rank wins
    assert w.kinds() == ["name", "name"]
    claim([NameClaim(MAC, "weak", "DNS", 1, 40)])  # outranked, best unchanged
    assert w.kinds() == ["name", "name"]


def test_type_event_only_when_type_changes() -> None:
    w, claim = _world()
    claim([TypeClaim(MAC, "printer", "port 9100", "inspection")])
    claim([TypeClaim(MAC, "printer", "port 9100", "inspection")])
    claim([TypeClaim(MAC, "camera", "rtsp", "inspection")])
    assert w.kinds() == ["type", "type"]


def test_hints_are_replaced_per_source() -> None:
    w, claim = _world()
    claim([Hint(MAC, "a", "s1"), Hint(MAC, "b", "s1")])
    claim([Hint(MAC, "c", "s1"), Hint(MAC, "z", "s2")])
    with w.uow() as uow:
        assert sorted(h.text for h in uow.identity.hints(MAC)) == ["c", "z"]
    assert w.kinds() == []


def test_claims_and_events_are_persisted() -> None:
    w, claim = _world()
    claim([NameClaim(MAC, "printer", "DNS", 1, 10)])
    with w.uow() as uow:
        assert [c.name for c in uow.identity.claims(MAC)] == ["printer"]
        assert [e.kind.value for e in uow.events.recent()] == ["name"]
