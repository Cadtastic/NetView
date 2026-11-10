"""Review fixes M11 and M18 for the state queries."""

import pytest
from usecase_helpers import SELF_IP, World, seen

from netview.application.plugins.jobs import JobSpec, JobStatus
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.queries.read_models import HostInfo
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.sdk.testing import fakes
from netview.sdk.testing.fakes import FakeVendors

HOST = HostInfo("test-host", SELF_IP, "192.168.1.1", "192.168.1.0/24", "linux")
MAC = "aa:bb:cc:dd:ee:01"


class StubScheduler:
    def add(self, owner: str, spec: JobSpec) -> None: ...
    def remove_owner(self, owner: str) -> None: ...
    def run_now(self, owner: str, name: str) -> None: ...
    def status(self) -> list[JobStatus]:
        return []


def _state(w: World, vendors: FakeVendors | None = None) -> GetNetworkState:
    return GetNetworkState(w.uow, CapabilityRegistry(), StubScheduler(), lambda: HOST, vendors)


def test_vendor_is_computed_at_read_time_when_stored_vendor_is_empty() -> None:
    w = World()  # World's FakeVendors knows nothing, so the stored vendor stays empty
    w.record([seen("192.168.1.20", MAC)])
    vendors = FakeVendors({MAC: "Acme"})
    assert _state(w, vendors)().devices[0].vendor == "Acme"
    assert GetDevice(w.uow, vendors)(MAC).vendor == "Acme"


def test_stored_vendor_wins_over_lookup() -> None:
    w = World()
    w.vendors.table[MAC] = "Stored"
    w.record([seen("192.168.1.20", MAC)])
    assert _state(w, FakeVendors({MAC: "Other"}))().devices[0].vendor == "Stored"


def test_state_loads_claims_nicknames_and_watches_once(monkeypatch: pytest.MonkeyPatch) -> None:
    w = World()
    w.record([seen(f"192.168.1.{i}", f"aa:bb:cc:dd:ee:{i:02x}") for i in range(2, 12)])
    calls: dict[str, int] = {"claims": 0, "nick_get": 0, "nick_all": 0, "watches": 0, "all_claims": 0}

    def counting(cls: type, name: str, label: str) -> None:
        original = getattr(cls, name)

        def wrapper(self: object, *args: object, **kwargs: object) -> object:
            calls[label] += 1
            return original(self, *args, **kwargs)

        monkeypatch.setattr(cls, name, wrapper)

    counting(fakes._Identity, "claims", "claims")
    counting(fakes._Identity, "all_claims", "all_claims")
    counting(fakes._Nicknames, "get", "nick_get")
    counting(fakes._Nicknames, "all", "nick_all")
    counting(fakes._Watches, "list", "watches")
    assert len(_state(w)().devices) == 10
    assert calls == {"claims": 0, "nick_get": 0, "nick_all": 1, "watches": 1, "all_claims": 1}
