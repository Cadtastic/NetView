"""Review fixes I4, M13-M15 for RecordSightings."""

from usecase_helpers import World, seen

from netview.application.usecases.nicknames import SetNickname
from netview.domain.device import Device, DeviceStatus

MAC = "90:39:5f:00:00:01"
MAC2 = "aa:bb:cc:00:00:02"


def test_conflict_is_emitted_once_per_ownership_change() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([seen("192.168.1.10", MAC2)], complete_sweep=False)
    w.record([seen("192.168.1.10", MAC2)], complete_sweep=False)
    w.record([seen("192.168.1.10", MAC2)])
    assert w.kinds().count("conflict") == 1


def test_stale_offline_owner_is_not_a_conflict() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([])  # MAC goes offline
    w.record([seen("192.168.1.10", MAC2)])
    assert "conflict" not in w.kinds()


def test_two_sweeps_with_the_same_conflicting_state_give_one_event() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([seen("192.168.1.10", MAC2)])
    w.record([seen("192.168.1.10", MAC2)])
    assert w.kinds().count("conflict") == 1


def test_partial_sighting_batch_does_not_end_the_first_sweep() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)], complete_sweep=False)
    w.record([seen("192.168.1.11", MAC2)])  # still the first complete sweep: nothing is new
    assert "new" not in w.kinds()
    w.record([seen("192.168.1.12", "aa:bb:cc:00:00:03")])
    assert w.kinds().count("new") == 1


def test_first_sweep_emits_no_back_online_events() -> None:
    w = World()
    with w.uow() as uow:  # as left by an import: known but offline
        uow.devices.add(Device(MAC, "192.168.1.10", MAC, "", 10, 20, DeviceStatus.OFFLINE))
        uow.commit()
    w.record([seen("192.168.1.10", MAC)])
    assert w.kinds() == []
    with w.uow() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.status is DeviceStatus.ONLINE


def test_merge_keeps_earliest_first_seen() -> None:
    w = World()
    w.record([seen("192.168.1.50", MAC, t=5000), seen("192.168.1.74", None, t=1000)])
    w.record([seen("192.168.1.74", MAC, t=9000)])
    with w.uow() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.first_seen_ms == 1000


def test_merge_records_dropped_ip_nickname_in_history() -> None:
    w = World()
    set_nickname = SetNickname(w.uow, w.clock, w.bus)
    w.record([seen("192.168.1.50", MAC), seen("192.168.1.74", None)])
    set_nickname(MAC, "Original")
    set_nickname("ip:192.168.1.74", "Other")
    w.record([seen("192.168.1.74", MAC)])
    with w.uow() as uow:
        assert uow.nicknames.get(MAC) == "Original"
        [merge] = [c for c in uow.nicknames.history(MAC) if c.by.startswith("merge:")]
        assert (merge.old, merge.new) == ("Original", "Original")
        assert merge.by == "merge: dropped ip-key nickname 'Other'"


def test_merge_with_same_nickname_adds_no_history_row() -> None:
    w = World()
    set_nickname = SetNickname(w.uow, w.clock, w.bus)
    w.record([seen("192.168.1.50", MAC), seen("192.168.1.74", None)])
    set_nickname(MAC, "Same")
    set_nickname("ip:192.168.1.74", "Same")
    w.record([seen("192.168.1.74", MAC)])
    with w.uow() as uow:
        assert not any(c.by.startswith("merge:") for c in uow.nicknames.history())


def test_clear_new_flag() -> None:
    w = World()
    w.record([seen("192.168.1.10", MAC)])
    w.record([seen("192.168.1.10", MAC), seen("192.168.1.11", MAC2)])
    with w.uow() as uow:
        d = uow.devices.get(MAC2)
        assert d is not None and d.is_new
        uow.devices.clear_new()
        uow.commit()
    with w.uow() as uow:
        assert not any(d.is_new for d in uow.devices.list())
