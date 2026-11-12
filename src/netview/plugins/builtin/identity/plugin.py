"""Device names and types from UPnP, NetBIOS, mDNS and reverse DNS (ported from LM discover_names)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from netview.plugins.builtin.identity.settings import IdentitySettings
from netview.sdk import (
    NAME_RANKS,
    Capability,
    DeviceView,
    Hint,
    NameClaim,
    Permission,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    TypeClaim,
    vendor_type,
)

_MAX_NAME = 80  # LM 1640
_LOCAL_SUFFIX = re.compile(r"\.local\.?$", re.IGNORECASE)
_PTR = 12


@dataclass(frozen=True)
class _Found:
    netbios: str
    mdns: str
    dns: str


def _private_mac(mac: str | None) -> bool:
    """True when the locally-administered bit of the first octet is set."""
    if not mac:
        return False
    try:
        return bool(int(re.split(r"[:-]", mac.strip())[0], 16) & 0x02)
    except ValueError:
        return False


def _text(value: object) -> str:
    """The first usable string of a DNS record value."""
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        return next((v for v in value if isinstance(v, str) and v), "")
    return ""


class _Identity:
    def __init__(self, plugin: IdentityPlugin, ctx: PluginContext) -> None:
        self._plugin = plugin
        self._ctx = ctx

    @property
    def recheck_after_s(self) -> float:
        settings: IdentitySettings = self._plugin.settings
        return float(settings.recheck_after_s)

    def identify(self, devices: Sequence[DeviceView]) -> list[NameClaim | TypeClaim | Hint]:
        try:
            return self._identify(devices)
        except Exception:  # a failed round must not stop the job
            self._ctx.log.warning("identity lookup failed", exc_info=True)
            return []

    def _identify(self, devices: Sequence[DeviceView]) -> list[NameClaim | TypeClaim | Hint]:
        if not devices:
            return []
        ctx = self._ctx
        settings: IdentitySettings = self._plugin.settings
        upnp = self._upnp_names({d.ip for d in devices}, settings)

        def one(device: DeviceView) -> _Found:
            return _Found(
                self._guard(self._netbios, device.ip, settings),
                self._guard(self._mdns, device.ip, settings),
                self._guard(self._rdns, device.ip, settings),
            )

        with ThreadPoolExecutor(max_workers=settings.workers) as pool:
            found = list(pool.map(one, devices))

        now = ctx.clock.now_ms()
        claims: list[NameClaim | TypeClaim | Hint] = []
        for device, f in zip(devices, found, strict=True):
            for source, name in (
                ("UPnP", upnp.get(device.ip, "")),
                ("NetBIOS", f.netbios),
                ("mDNS", f.mdns),
                ("DNS", f.dns),
            ):
                name = name.strip()[:_MAX_NAME]
                if name:
                    claims.append(NameClaim(device.key, name, source, NAME_RANKS[source], now))
            kind = vendor_type(device.vendor, device.ttl, _private_mac(device.mac))
            if kind:
                claims.append(TypeClaim(device.key, kind, "guess from maker", "vendor", now))
        return claims

    def _guard(self, fn: Any, ip: str, settings: IdentitySettings) -> str:
        try:
            return str(fn(ip, settings) or "")
        except Exception:
            self._ctx.log.debug("%s lookup for %s failed", getattr(fn, "__name__", "name"), ip, exc_info=True)
            return ""

    def _upnp_names(self, wanted: set[str], settings: IdentitySettings) -> dict[str, str]:
        """``{ip: friendlyName}`` for the devices in ``wanted`` that answer UPnP discovery (LM 802-811)."""
        probes = self._ctx.probes
        names: dict[str, str] = {}
        try:
            entries = probes.ssdp_search(None, settings.ssdp_timeout_s)
        except Exception:
            self._ctx.log.debug("ssdp search failed", exc_info=True)
            return names
        for entry in entries:
            if entry.ip not in wanted or entry.ip in names:
                continue
            try:
                name = probes.upnp_description(entry.ip, entry.location).get("friendlyName", "")
            except Exception:
                self._ctx.log.debug("upnp description for %s failed", entry.ip, exc_info=True)
                continue
            if name:
                names[entry.ip] = name
        return names

    def _netbios(self, ip: str, settings: IdentitySettings) -> str:
        info = self._ctx.probes.netbios(ip, settings.netbios_timeout_s)
        return info.name if info is not None else ""

    def _mdns(self, ip: str, settings: IdentitySettings) -> str:
        reverse = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
        for record in self._ctx.probes.mdns_query(ip, reverse, _PTR, settings.mdns_timeout_s):
            if record.rtype == _PTR and (name := _text(record.value)):
                return _LOCAL_SUFFIX.sub("", name)
        return ""

    def _rdns(self, ip: str, settings: IdentitySettings) -> str:
        return self._ctx.probes.reverse_dns(ip, settings.rdns_timeout_s)


class IdentityPlugin(Plugin):
    manifest = PluginManifest(
        id="identity",
        name="Identity",
        version="0.1.0",
        description=(
            "Names devices from UPnP, NetBIOS, mDNS and reverse DNS, and guesses their type from the maker"
        ),
        guid="4b77e778-dc26-4ac0-8b2e-fe3995363df1",
        display_name="Identity",
        plugin_type=PluginType.SOFTWARE,
        sdk_version=">=1.1,<2",
        capabilities=frozenset({Capability.IDENTITY}),
        permissions=frozenset(
            {
                Permission.DEVICES_READ,
                Permission.NAMES_WRITE,
                Permission.TYPES_WRITE,
                Permission.NETWORK_PROBE,
            }
        ),
    )
    settings_model = IdentitySettings

    def __init__(self) -> None:
        self._identity: _Identity | None = None

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        self._identity = _Identity(self, ctx)

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.IDENTITY: self._identity} if self._identity else {}
