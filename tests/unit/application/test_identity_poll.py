from collections.abc import Iterable, Sequence

from usecase_helpers import World

from netview.application.queries.read_models import DeviceView
from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.identity_poll import PollIdentity
from netview.domain.naming import Hint, NameClaim, TypeClaim


def view(i: int, status: str = "online", is_self: bool = False) -> DeviceView:
    return DeviceView(
        key=f"k{i:03d}",
        ip=f"10.0.{i // 250}.{i % 250 + 1}",
        mac=None,
        vendor="",
        nickname=None,
        device_name="",
        name_source="",
        type="",
        hints=[],
        status=status,
        rtt_ms=None,
        ttl=None,
        first_seen_ms=0,
        last_seen_ms=0,
        is_new=False,
        is_self=is_self,
        watched=False,
        display_name="",
    )


class _Provider:
    def __init__(
        self, recheck_after_s: float = 1800.0, claims: Sequence[NameClaim | TypeClaim | Hint] = ()
    ) -> None:
        self.recheck_after_s = recheck_after_s
        self.claims = list(claims)
        self.calls: list[list[DeviceView]] = []

    def identify(self, devices: Sequence[DeviceView]) -> Iterable[NameClaim | TypeClaim | Hint]:
        self.calls.append(list(devices))
        return self.claims


def make(devices: list[DeviceView]) -> tuple[PollIdentity, World]:
    w = World()
    return PollIdentity(lambda: devices, ClaimIdentity(w.uow, w.bus), w.clock), w


def test_picks_at_most_128_then_the_rest() -> None:
    devices = [view(i) for i in range(200)]
    poll, _ = make(devices)
    provider = _Provider()
    poll("identity", provider)
    poll("identity", provider)
    assert [len(c) for c in provider.calls] == [128, 72]
    first = {d.key for d in provider.calls[0]}
    second = {d.key for d in provider.calls[1]}
    assert not first & second and len(first | second) == 200
    poll("identity", provider)  # all of them were just checked: the provider is not called at all
    assert len(provider.calls) == 2


def test_device_checked_within_the_recheck_interval_is_skipped_until_it_expires() -> None:
    poll, w = make([view(1)])
    provider = _Provider(recheck_after_s=100)
    poll("identity", provider)
    w.clock.advance(99_000)
    poll("identity", provider)
    assert [len(c) for c in provider.calls] == [1]
    w.clock.advance(1_000)
    poll("identity", provider)
    assert [len(c) for c in provider.calls] == [1, 1]


def test_self_and_offline_devices_are_never_passed() -> None:
    poll, _ = make([view(1, is_self=True), view(2, status="offline"), view(3, status="quiet"), view(4)])
    provider = _Provider()
    poll("identity", provider)
    assert sorted(d.key for d in provider.calls[0]) == ["k003", "k004"]


def test_never_checked_devices_go_before_checked_ones() -> None:
    devices = [view(i) for i in range(130)]
    poll, w = make(devices)
    provider = _Provider()
    poll("identity", provider)  # 128 checked at t0
    w.clock.advance(10_000)
    never = {d.key for d in devices} - {d.key for d in provider.calls[0]}
    poll("identity", provider)
    assert {d.key for d in provider.calls[1]} == never


def test_checked_is_tracked_per_plugin() -> None:
    poll, _ = make([view(1)])
    a, b = _Provider(), _Provider()
    poll("a", a)
    poll("b", b)
    assert len(a.calls[0]) == 1 and len(b.calls[0]) == 1


def test_devices_are_marked_checked_even_when_nothing_was_claimed() -> None:
    poll, _ = make([view(1)])
    provider = _Provider()
    poll("identity", provider)
    poll("identity", provider)
    assert [len(c) for c in provider.calls] == [1]


def test_claims_are_recorded() -> None:
    d = view(1)
    poll, w = make([d])
    provider = _Provider(claims=[NameClaim(d.key, "nas", "mDNS", 3, 5)])
    poll("identity", provider)
    with w.uow() as uow:
        assert [c.name for c in uow.identity.claims(d.key)] == ["nas"]
