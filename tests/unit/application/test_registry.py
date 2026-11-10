import pytest

from netview.application.capabilities import Capability
from netview.application.plugins.registry import CapabilityRegistry
from netview.domain.errors import CapabilityUnavailableError


def test_require_on_empty_registry_raises_with_message() -> None:
    with pytest.raises(CapabilityUnavailableError) as exc:
        CapabilityRegistry().require(Capability.DISCOVERY)
    assert str(exc.value) == "no enabled plugin provides discovery"


def test_providers_come_back_in_registration_order() -> None:
    reg = CapabilityRegistry()
    a, b = object(), object()
    reg.register("p1", Capability.HEALTH, a)
    reg.register("p2", Capability.HEALTH, b)
    assert reg.providers(Capability.HEALTH) == [("p1", a), ("p2", b)]
    assert reg.require(Capability.HEALTH) == [("p1", a), ("p2", b)]
    assert reg.providers(Capability.DISCOVERY) == []


def test_unregister_plugin_drops_only_that_plugin() -> None:
    reg = CapabilityRegistry()
    a, b, c = object(), object(), object()
    reg.register("p1", Capability.HEALTH, a)
    reg.register("p1", Capability.TRAFFIC, b)
    reg.register("p2", Capability.HEALTH, c)
    reg.unregister_plugin("p1")
    assert reg.providers(Capability.HEALTH) == [("p2", c)]
    assert reg.providers(Capability.TRAFFIC) == []


def test_capability_values_are_lower_case_names() -> None:
    assert Capability.LOCAL_HOST.value == "local_host"
    assert Capability.WEB_UI.value == "web_ui"
