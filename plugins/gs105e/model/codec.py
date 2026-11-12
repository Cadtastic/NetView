"""JSON form of a ``Snapshot``, for storage across restarts and for API reads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast, get_args

from .config import (
    IgmpConfig,
    ManagementConfig,
    ManagementMode,
    MirrorConfig,
    QosConfig,
    QosMode,
    RateLimit,
    VlanConfig,
    VlanMembers,
    VlanMode,
)
from .port import PortStatus
from .snapshot import PollGroup, Snapshot
from .switch import SwitchInfo

SCHEMA = "netview.gs105e.snapshot/1"


def _literal(value: object, allowed: Any) -> Any:
    if value not in get_args(allowed):
        raise ValueError(f"unexpected value {value!r} in snapshot")
    return value


def _opt(data: Mapping[str, Any] | None, build: Any) -> Any:
    return None if data is None else build(data)


def snapshot_to_json(s: Snapshot) -> str:
    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "t_ms": s.t_ms,
        "groups": sorted(s.groups),
        "info": None
        if s.info is None
        else {
            "product": s.info.product,
            "name": s.info.name,
            "serial": s.info.serial,
            "mac": s.info.mac,
            "bootloader": s.info.bootloader,
            "firmware": s.info.firmware,
            "dhcp": s.info.dhcp,
            "ip": s.info.ip,
            "mask": s.info.mask,
            "gateway": s.info.gateway,
        },
        "ports": [
            {
                "port": p.port,
                "description": p.description,
                "up": p.up,
                "speed_setting": p.speed_setting,
                "link_mbps": p.link_mbps,
                "flow_control": p.flow_control,
                "max_mtu": p.max_mtu,
            }
            for p in s.ports
        ],
        "vlans": None
        if s.vlans is None
        else {
            "mode": s.vlans.mode,
            "vlan_ids": list(s.vlans.vlan_ids),
            "shown": None
            if s.vlans.shown is None
            else {"vid": s.vlans.shown.vid, "members": list(s.vlans.shown.members)},
            "pvids": [[p, v] for p, v in s.vlans.pvids],
        },
        "qos": None
        if s.qos is None
        else {
            "mode": s.qos.mode,
            "rate_limits": [
                {"port": r.port, "ingress_kbps": r.ingress_kbps, "egress_kbps": r.egress_kbps}
                for r in s.qos.rate_limits
            ],
            "storm_control": s.qos.storm_control,
        },
        "igmp": None
        if s.igmp is None
        else {
            "enabled": s.igmp.enabled,
            "vlan": s.igmp.vlan,
            "validate_v3_header": s.igmp.validate_v3_header,
            "block_unknown": s.igmp.block_unknown,
            "router_port": s.igmp.router_port,
        },
        "mirror": None
        if s.mirror is None
        else {
            "enabled": s.mirror.enabled,
            "destination": s.mirror.destination,
            "sources": list(s.mirror.sources),
        },
        "management": None
        if s.management is None
        else {
            "mode": s.management.mode,
            "tftp": s.management.tftp,
            "access_list": [[ip, mask] for ip, mask in s.management.access_list],
            "power_saving": s.management.power_saving,
            "loop_detection": s.management.loop_detection,
        },
    }
    return json.dumps(doc, separators=(",", ":"), sort_keys=True)


def snapshot_from_json(text: str) -> Snapshot:
    doc = json.loads(text)
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError(f"unknown snapshot schema (expected {SCHEMA!r})")
    try:
        return _build(doc)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed snapshot: {exc!r}") from None


def _vlans(d: Mapping[str, Any]) -> VlanConfig:
    return VlanConfig(
        mode=cast("VlanMode", _literal(d["mode"], VlanMode)),
        vlan_ids=tuple(int(v) for v in d["vlan_ids"]),
        shown=_opt(d["shown"], lambda m: VlanMembers(int(m["vid"]), tuple(m["members"]))),
        pvids=tuple((int(p), int(v)) for p, v in d["pvids"]),
    )


def _qos(d: Mapping[str, Any]) -> QosConfig:
    return QosConfig(
        mode=cast("QosMode", _literal(d["mode"], QosMode)),
        rate_limits=tuple(
            RateLimit(r["port"], r["ingress_kbps"], r["egress_kbps"]) for r in d["rate_limits"]
        ),
        storm_control=d["storm_control"],
    )


def _management(d: Mapping[str, Any]) -> ManagementConfig:
    return ManagementConfig(
        mode=cast("ManagementMode", _literal(d["mode"], ManagementMode)),
        tftp=d["tftp"],
        access_list=tuple((ip, mask) for ip, mask in d["access_list"]),
        power_saving=d["power_saving"],
        loop_detection=d["loop_detection"],
    )


def _build(doc: Mapping[str, Any]) -> Snapshot:
    return Snapshot(
        t_ms=int(doc["t_ms"]),
        groups=frozenset(cast("list[PollGroup]", [_literal(g, PollGroup) for g in doc["groups"]])),
        info=_opt(doc["info"], lambda d: SwitchInfo(**d)),
        ports=tuple(PortStatus(**d) for d in doc["ports"]),
        vlans=_opt(doc["vlans"], _vlans),
        qos=_opt(doc["qos"], _qos),
        igmp=_opt(doc["igmp"], lambda d: IgmpConfig(**d)),
        mirror=_opt(
            doc["mirror"], lambda d: MirrorConfig(d["enabled"], d["destination"], tuple(d["sources"]))
        ),
        management=_opt(doc["management"], _management),
    )
