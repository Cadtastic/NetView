from __future__ import annotations

from collections.abc import Callable
from itertools import count

from netview_local_plugins.roku.merge import merge
from netview_local_plugins.roku.model import SavedTv, ScanHit

NOW = "2026-11-11T15:00:00Z"
OLD = "2026-11-01T10:00:00Z"


def tv(**kw: object) -> SavedTv:
    base: dict[str, object] = {
        "id": "a", "serial": "", "ip": "192.168.1.60", "name": "TV", "label": "", "model": "M",
        "location": "", "tv": True, "found_by": "sweep", "first_seen": OLD, "last_seen": OLD,
    }  # fmt: skip
    base.update(kw)
    return SavedTv(**base)


def hit(**kw: object) -> ScanHit:
    base: dict[str, object] = {
        "ip": "192.168.1.60", "serial": "", "name": "TV", "model": "M", "location": "",
        "tv": True, "found_by": "ssdp",
    }  # fmt: skip
    base.update(kw)
    return ScanHit(**base)


def ids() -> Callable[[], str]:
    c = count(1)
    return lambda: f"n{next(c)}"


def test_merge_matches_by_serial_and_keeps_label_and_order() -> None:
    saved = [
        tv(id="a", serial="S1", ip="192.168.1.60", label="Lounge"),
        tv(id="b", serial="S2", ip="192.168.1.61"),
    ]
    r = merge(saved, [hit(serial="S1", ip="192.168.1.70", name="New name")], NOW, ids())
    assert [t.id for t in r.tvs] == ["a", "b"] and r.tvs[0].ip == "192.168.1.70"
    assert r.tvs[0].label == "Lounge" and r.tvs[0].name == "New name" and (r.added, r.updated) == (0, 1)
    assert r.tvs[0].first_seen == OLD and r.tvs[0].last_seen == NOW and r.tvs[0].found_by == "ssdp"


def test_merge_matches_by_ip_when_serial_missing() -> None:
    saved = [tv(id="a", serial="", ip="192.168.1.60", label="Den")]
    r = merge(saved, [hit(serial="S9", ip="192.168.1.60", name="Renamed")], NOW, ids())
    assert len(r.tvs) == 1 and r.tvs[0].id == "a" and r.tvs[0].name == "Renamed"
    assert r.tvs[0].label == "Den" and (r.added, r.updated) == (0, 1)


def test_merge_appends_new_and_never_removes() -> None:
    saved = [tv(id="a", serial="S1"), tv(id="b", serial="S2", ip="192.168.1.61")]
    r = merge(saved, [hit(serial="S3", ip="192.168.1.62", name="Bedroom")], NOW, ids())
    assert [t.id for t in r.tvs] == ["a", "b", "n1"]
    new = r.tvs[2]
    assert new.first_seen == NOW and new.last_seen == NOW and new.label == "" and new.serial == "S3"
    assert (r.added, r.updated) == (1, 0)


def test_merge_does_not_match_ip_across_different_serials() -> None:
    saved = [tv(id="a", serial="S1", ip="192.168.1.60")]
    r = merge(saved, [hit(serial="S2", ip="192.168.1.60")], NOW, ids())
    assert [t.id for t in r.tvs] == ["a", "n1"] and (r.added, r.updated) == (1, 0)


def test_merge_address_reshuffle_moves_ip_to_serial_match_other_keeps_old() -> None:
    saved = [tv(id="a", serial="S1", ip="192.168.1.60"), tv(id="b", serial="S2", ip="192.168.1.61")]
    r = merge(saved, [hit(serial="S1", ip="192.168.1.61")], NOW, ids())
    assert r.tvs[0].ip == "192.168.1.61" and r.tvs[1].ip == "192.168.1.61" and r.tvs[1].id == "b"
    assert r.tvs[1].last_seen == OLD
