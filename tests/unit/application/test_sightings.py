from usecase_helpers import SELF_IP, World, seen

from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.nicknames import SetNickname
from netview.domain.device import DeviceStatus
from netview.domain.events import EventKind
from netview.domain.naming import NameClaim

MAC = "90:39:5f:00:00:01"
MAC2 = "aa:bb:cc:00:00:02"


def test_first_sweep_emits_no_new_events() -> None:
    w = World()
    summary = w.record([seen("192.168.1.10", MAC)])
    assert summary.seen == 1 and summary.new == 0
    assert w.kinds() == []


def test_second_sweep_new_device_emits_new() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    summary = w.record([seen("192.168.1.10", MAC), seen("192.168.1.11", MAC2)])
    assert summary.new == 1
    assert w.kinds() == ["new"]
    with w.uow() as uow:
        assert uow.devices.get(MAC2) is not None
        assert [e.kind for e in uow.events.recent()] == [EventKind.NEW]


def test_quiet_when_arp_only() -> None:
    w = World()
    summary = w.record([seen("192.168.1.10", MAC, rtt=None)])
    with w.uow() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.status is DeviceStatus.QUIET and d.rtt_ms is None
    assert summary.quiet == 1 and summary.replied == 0


def test_unseen_goes_offline_once() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([])
    w.record([])
    assert w.kinds() == ["offline"]
    with w.uow() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.status is DeviceStatus.OFFLINE
        assert d.rtt_ms is None and d.missed == 2


def test_incomplete_sweep_does_not_mark_offline() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([], complete_sweep=False)
    assert w.kinds() == []
    with w.uow() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.status is DeviceStatus.ONLINE


def test_device_back_online_emits_online() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([])
    w.record([seen("192.168.1.10", MAC)])
    assert w.kinds() == ["offline", "online"]


def test_moved_device_emits_moved() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([seen("192.168.1.20", MAC)])
    assert w.kinds() == ["moved"]
    with w.uow() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.ip == "192.168.1.20"


def test_ip_answering_from_different_mac_emits_conflict() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([seen("192.168.1.10", MAC2)])
    assert "conflict" in w.kinds()


def test_mac_learned_later_merges_ip_key() -> None:
    """Review focus 1."""
    w = World()
    set_nickname = SetNickname(w.uow, w.clock, w.bus)
    w.record([seen("192.168.1.74", None, t=1000)])
    set_nickname("ip:192.168.1.74", "Jessi's Kindle")
    w.record([seen("192.168.1.74", MAC, t=5000)])
    with w.uow() as uow:
        assert uow.devices.get("ip:192.168.1.74") is None
        assert uow.nicknames.get("ip:192.168.1.74") is None
        assert uow.nicknames.get(MAC) == "Jessi's Kindle"
        merged = uow.devices.get(MAC)
        assert merged is not None and merged.first_seen_ms == 1000
        assert [d.ip for d in uow.devices.list()].count("192.168.1.74") == 1
        assert all(c.key == MAC for c in uow.nicknames.history())


def test_mac_learned_later_moves_name_claims() -> None:
    w = World()
    w.record([seen("192.168.1.74", None)])
    ClaimIdentity(w.uow, w.bus)([NameClaim("ip:192.168.1.74", "kindle", "DNS", 1, 10)])
    w.record([seen("192.168.1.74", MAC)])
    with w.uow() as uow:
        assert uow.identity.claims("ip:192.168.1.74") == []
        assert [c.name for c in uow.identity.claims(MAC)] == ["kindle"]


def test_mac_merge_keeps_existing_mac_nickname() -> None:
    w = World()
    set_nickname = SetNickname(w.uow, w.clock, w.bus)
    w.record([seen("192.168.1.50", MAC), seen("192.168.1.74", None)])
    set_nickname(MAC, "Original")
    set_nickname("ip:192.168.1.74", "Other")
    # the known MAC now shows up at the ip-keyed address
    w.record([seen("192.168.1.74", MAC)])
    with w.uow() as uow:
        assert uow.nicknames.get(MAC) == "Original"
        assert uow.devices.get("ip:192.168.1.74") is None
        assert len([d for d in uow.devices.list() if d.key == MAC]) == 1


def test_self_ip_gets_self_key() -> None:
    w = World()
    w.record([seen(SELF_IP, "de:ad:be:ef:00:01"), seen("192.168.1.10", MAC)])
    w.record([seen(SELF_IP, None), seen("192.168.1.10", MAC)])
    with w.uow() as uow:
        d = uow.devices.get("self")
        assert d is not None and d.mac is None and d.is_self
    assert "new" not in w.kinds()


def test_no_sightings_at_all_is_harmless() -> None:
    w = World()
    summary = w.record([])
    assert (summary.seen, summary.replied, summary.quiet, summary.went_offline) == (0, 0, 0, 0)


def test_sighting_without_reply_or_mac_is_ignored() -> None:
    w = World()
    w.record([seen("192.168.1.10", None, rtt=None)])
    with w.uow() as uow:
        assert uow.devices.list() == []
