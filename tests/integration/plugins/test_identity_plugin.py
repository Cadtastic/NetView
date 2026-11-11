from typing import Any

import pytest
from conftest import HostEnv

from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.identity_poll import PollIdentity
from netview.domain.naming import best_claim
from netview.plugins.builtin.identity.plugin import IdentityPlugin
from netview.plugins.builtin.identity.settings import IdentitySettings
from netview.sdk import (
    Capability,
    DeviceView,
    DnsRecord,
    NameClaim,
    NetbiosInfo,
    PluginManifest,
    SsdpEntry,
    TypeClaim,
)
from netview.sdk.testing.contract import _FakeContext, check_plugin
from netview.sdk.testing.fakes import FakeClock, FakeServiceProbes, RecordingEventBus

NOW = FakeClock().now_ms()


def device(
    ip: str, vendor: str = "", mac: str | None = None, ttl: int | None = None, key: str | None = None
) -> DeviceView:
    return DeviceView(
        key=key or f"k-{ip}",
        ip=ip,
        mac=mac,
        vendor=vendor,
        nickname=None,
        device_name="",
        name_source="",
        type="",
        hints=[],
        status="online",
        rtt_ms=None,
        ttl=ttl,
        first_seen_ms=0,
        last_seen_ms=0,
        is_new=False,
        is_self=False,
        watched=False,
        display_name="",
    )


def make_plugin(probes: FakeServiceProbes, settings: IdentitySettings | None = None) -> IdentityPlugin:
    plugin = IdentityPlugin()
    plugin.settings = settings or IdentitySettings()
    ctx = _FakeContext("identity", plugin.settings)
    ctx.probes = probes
    plugin.setup(ctx)  # type: ignore[arg-type]
    return plugin


def identify(plugin: IdentityPlugin, devices: list[DeviceView]) -> list[Any]:
    provider: Any = plugin.providers()[Capability.IDENTITY]
    return list(provider.identify(devices))


def ssdp(ip: str) -> SsdpEntry:
    return SsdpEntry(ip, f"http://{ip}:8060/desc.xml", "Roku", f"uuid:{ip}", ("upnp:rootdevice",))


def test_contract() -> None:
    check_plugin(IdentityPlugin)


def test_manifest() -> None:
    m: PluginManifest = IdentityPlugin.manifest
    assert (m.id, m.name, m.version) == ("identity", "Identity", "0.1.0")
    assert m.sdk_version == ">=1.1,<2"
    assert m.capabilities == {Capability.IDENTITY}
    assert {p.value for p in m.permissions} == {"devices:read", "names:write", "types:write", "network:probe"}


def test_settings_defaults_and_limits() -> None:
    s = IdentitySettings()
    assert (s.recheck_after_s, s.ssdp_timeout_s, s.mdns_timeout_s) == (1800, 3.0, 1.0)
    assert (s.netbios_timeout_s, s.rdns_timeout_s, s.workers) == (1.0, 1.5, 16)
    for bad in (
        {"recheck_after_s": 299},
        {"recheck_after_s": 86401},
        {"workers": 0},
        {"workers": 65},
    ):
        with pytest.raises(ValueError):
            IdentitySettings(**bad)


def test_claims_one_per_source_with_the_domain_ranks() -> None:
    q = "6.2.0.192.in-addr.arpa"
    probes = FakeServiceProbes(
        ssdp=[ssdp("192.0.2.5")],
        upnp={"192.0.2.5": {"friendlyName": "Roku TV"}},
        mdns={("192.0.2.6", q): [DnsRecord(q, 12, "jessis-ipad.local.")]},
        netbios={"192.0.2.7": NetbiosInfo("R720", "WORKGROUP", (), "")},
        rdns={"192.0.2.8": "nas.lan"},
    )
    devices = [device("192.0.2.5", "Roku, Inc")] + [device(f"192.0.2.{n}") for n in (6, 7, 8)]
    claims = identify(make_plugin(probes), devices)
    names = {(c.key, c.name, c.source, c.rank) for c in claims if isinstance(c, NameClaim)}
    assert names == {
        ("k-192.0.2.5", "Roku TV", "UPnP", 6),
        ("k-192.0.2.6", "jessis-ipad", "mDNS", 3),
        ("k-192.0.2.7", "R720", "NetBIOS", 4),
        ("k-192.0.2.8", "nas.lan", "DNS", 1),
    }
    assert {c.checked_ms for c in claims} == {NOW}
    types = [c for c in claims if isinstance(c, TypeClaim)]
    assert types == [TypeClaim("k-192.0.2.5", "Roku device", "guess from maker", "vendor", NOW)]


def test_every_source_that_answers_is_sent_so_the_domain_can_pick() -> None:
    probes = FakeServiceProbes(
        ssdp=[ssdp("192.0.2.5")],
        upnp={"192.0.2.5": {"friendlyName": "Roku TV"}},
        rdns={"192.0.2.5": "roku.lan"},
        netbios={"192.0.2.5": NetbiosInfo("ROKU", "", (), "")},
    )
    claims = identify(make_plugin(probes), [device("192.0.2.5")])
    assert [(c.source, c.name) for c in claims if isinstance(c, NameClaim)] == [
        ("UPnP", "Roku TV"),
        ("NetBIOS", "ROKU"),
        ("DNS", "roku.lan"),
    ]


def test_only_the_devices_in_the_batch_are_named_from_the_ssdp_answers() -> None:
    probes = FakeServiceProbes(
        ssdp=[ssdp("192.0.2.5"), ssdp("192.0.2.9")],
        upnp={"192.0.2.5": {"friendlyName": "Roku TV"}, "192.0.2.9": {"friendlyName": "Other"}},
    )
    claims = identify(make_plugin(probes), [device("192.0.2.5")])
    assert [c.name for c in claims if isinstance(c, NameClaim)] == ["Roku TV"]


def test_the_first_ssdp_entry_with_a_friendly_name_wins() -> None:
    probes = FakeServiceProbes(ssdp=[ssdp("192.0.2.5"), ssdp("192.0.2.5")])
    probes.upnp = {"192.0.2.5": {"friendlyName": "First"}}
    names = [c.name for c in identify(make_plugin(probes), [device("192.0.2.5")]) if isinstance(c, NameClaim)]
    assert names == ["First"]


def test_mdns_names_lose_the_local_suffix_with_or_without_the_trailing_dot() -> None:
    q = "6.2.0.192.in-addr.arpa"
    q2 = "7.2.0.192.in-addr.arpa"
    probes = FakeServiceProbes(
        mdns={
            ("192.0.2.6", q): [DnsRecord(q, 12, "a.local")],
            ("192.0.2.7", q2): [DnsRecord(q2, 12, ("b.local.",))],
        }
    )
    claims = identify(make_plugin(probes), [device("192.0.2.6"), device("192.0.2.7")])
    assert {(c.key, c.name) for c in claims} == {("k-192.0.2.6", "a"), ("k-192.0.2.7", "b")}


def test_names_are_truncated_to_80_characters_and_blank_names_are_dropped() -> None:
    probes = FakeServiceProbes(rdns={"192.0.2.5": "x" * 200, "192.0.2.6": "   "})
    claims = identify(make_plugin(probes), [device("192.0.2.5"), device("192.0.2.6")])
    assert [(c.key, len(c.name)) for c in claims if isinstance(c, NameClaim)] == [("k-192.0.2.5", 80)]


def test_a_name_from_a_device_is_stored_as_typed() -> None:
    """The UI test in Task D covers the escaping."""
    probes = FakeServiceProbes(ssdp=[ssdp("192.0.2.5")], upnp={"192.0.2.5": {"friendlyName": "<b>TV</b>"}})
    [claim] = identify(make_plugin(probes), [device("192.0.2.5")])
    assert claim.name == "<b>TV</b>"


def test_type_guess_uses_the_vendor_the_ttl_and_a_private_mac() -> None:
    devices = [
        device("192.0.2.5", "Intel Corporate", ttl=128),
        device("192.0.2.6", "", mac="6a:00:00:00:00:01"),  # locally administered bit set
        device("192.0.2.7", "", mac="68:00:00:00:00:01"),
        device("192.0.2.8", "", mac="not a mac"),
    ]
    claims = identify(make_plugin(FakeServiceProbes()), devices)
    types = {c.key: c.type for c in claims if isinstance(c, TypeClaim)}
    assert types == {"k-192.0.2.5": "Windows PC", "k-192.0.2.6": "Phone, tablet or laptop"}


def test_a_probe_that_raises_counts_as_not_found_and_identify_never_raises() -> None:
    class Broken(FakeServiceProbes):
        def reverse_dns(self, ip: str, timeout_s: float = 2.0) -> str:
            raise OSError("boom")

        def netbios(self, ip: str, timeout_s: float = 1.5) -> NetbiosInfo | None:
            raise OSError("boom")

        def mdns_query(self, ip: str, qname: str, qtype: int = 12, timeout_s: float = 1.2) -> list[DnsRecord]:
            raise OSError("boom")

        def ssdp_search(self, target: str | None = None, timeout_s: float = 2.5) -> list[SsdpEntry]:
            raise OSError("boom")

    claims = identify(make_plugin(Broken()), [device("192.0.2.5", "Roku, Inc")])
    assert [type(c) for c in claims] == [TypeClaim]  # the maker guess still works


def test_a_upnp_description_that_raises_does_not_lose_the_other_names() -> None:
    class BrokenUpnp(FakeServiceProbes):
        def upnp_description(self, ip: str, location: str) -> dict[str, str]:
            raise OSError("boom")

    probes = BrokenUpnp(ssdp=[ssdp("192.0.2.5")], rdns={"192.0.2.5": "a"})
    claims = identify(make_plugin(probes), [device("192.0.2.5")])
    assert [(c.source, c.name) for c in claims] == [("DNS", "a")]


def test_nothing_in_the_batch_means_no_probing() -> None:
    class Loud(FakeServiceProbes):
        def ssdp_search(self, target: str | None = None, timeout_s: float = 2.5) -> list[SsdpEntry]:
            raise AssertionError("should not search")

    assert identify(make_plugin(Loud()), []) == []


def test_ssdp_is_searched_once_per_batch_with_the_configured_timeout() -> None:
    calls: list[tuple[str | None, float]] = []

    class Counting(FakeServiceProbes):
        def ssdp_search(self, target: str | None = None, timeout_s: float = 2.5) -> list[SsdpEntry]:
            calls.append((target, timeout_s))
            return []

    identify(
        make_plugin(Counting(), IdentitySettings(ssdp_timeout_s=2.0)),
        [device("192.0.2.5"), device("192.0.2.6"), device("192.0.2.7")],
    )
    assert calls == [(None, 2.0)]


def test_recheck_after_s_reads_the_live_setting() -> None:
    plugin = make_plugin(FakeServiceProbes())
    provider: Any = plugin.providers()[Capability.IDENTITY]
    assert provider.recheck_after_s == 1800
    plugin.on_settings_changed(IdentitySettings(recheck_after_s=600))
    assert provider.recheck_after_s == 600


def test_ranking_through_the_core_a_upnp_name_beats_a_dns_name(env: HostEnv) -> None:
    probes = FakeServiceProbes(
        ssdp=[ssdp("192.0.2.5")],
        upnp={"192.0.2.5": {"friendlyName": "Roku TV"}},
        rdns={"192.0.2.5": "dns-name.lan"},
    )
    provider: Any = make_plugin(probes).providers()[Capability.IDENTITY]
    view = device("192.0.2.5", "Roku, Inc")
    poll = PollIdentity(lambda: [view], ClaimIdentity(env.uow, RecordingEventBus()), FakeClock())

    poll("identity", provider)

    with env.uow() as uow:
        assert {c.source for c in uow.identity.claims(view.key)} == {"UPnP", "DNS"}
        best = best_claim(uow.identity.claims(view.key))
        assert best is not None and (best.name, best.source) == ("Roku TV", "UPnP")
        [t] = uow.identity.types(view.key)
        assert t.type == "Roku device"
