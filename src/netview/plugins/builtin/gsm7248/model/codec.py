"""JSON form of a ``Snapshot``, for storage across restarts and for API reads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast, get_args

from .mac import MacEntry, MacStatus
from .port import Duplex, Port, PortKind
from .snapshot import PollGroup, Snapshot
from .switch import Health, Inventory, SwitchInfo
from .vlan import LagGroup, StpPort, StpState, Vlan

SCHEMA = "netview.gsm7248.snapshot/1"


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
            "sys_name": s.info.sys_name,
            "sys_descr": s.info.sys_descr,
            "object_id": s.info.object_id,
            "uptime_cs": s.info.uptime_cs,
            "mac": s.info.mac,
        },
        "health": None
        if s.health is None
        else {
            "cpu_percent": s.health.cpu_percent,
            "mem_free_kb": s.health.mem_free_kb,
            "mem_total_kb": s.health.mem_total_kb,
        },
        "inventory": None
        if s.inventory is None
        else {"model": s.inventory.model, "serial": s.inventory.serial, "firmware": s.inventory.firmware},
        "ports": [
            {
                "if_index": p.if_index,
                "name": p.name,
                "alias": p.alias,
                "kind": p.kind,
                "admin_up": p.admin_up,
                "oper_up": p.oper_up,
                "speed_mbps": p.speed_mbps,
                "duplex": p.duplex,
                "last_change_cs": p.last_change_cs,
            }
            for p in s.ports
        ],
        "macs": [{"mac": m.mac, "vlan": m.vlan, "if_index": m.if_index, "status": m.status} for m in s.macs],
        "vlans": [
            {"vid": v.vid, "name": v.name, "egress": sorted(v.egress), "untagged": sorted(v.untagged)}
            for v in s.vlans
        ],
        "pvids": [[i, v] for i, v in s.pvids],
        "stp": [{"if_index": p.if_index, "state": p.state} for p in s.stp],
        "lags": [{"if_index": g.if_index, "name": g.name, "members": sorted(g.members)} for g in s.lags],
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


def _build(doc: Mapping[str, Any]) -> Snapshot:
    return Snapshot(
        t_ms=int(doc["t_ms"]),
        groups=frozenset(cast("list[PollGroup]", [_literal(g, PollGroup) for g in doc["groups"]])),
        info=_opt(doc["info"], lambda d: SwitchInfo(**d)),
        health=_opt(doc["health"], lambda d: Health(**d)),
        inventory=_opt(doc["inventory"], lambda d: Inventory(**d)),
        ports=tuple(
            Port(
                if_index=d["if_index"],
                name=d["name"],
                alias=d["alias"],
                kind=cast("PortKind", _literal(d["kind"], PortKind)),
                admin_up=d["admin_up"],
                oper_up=d["oper_up"],
                speed_mbps=d["speed_mbps"],
                duplex=cast("Duplex", _literal(d["duplex"], Duplex)),
                last_change_cs=d["last_change_cs"],
            )
            for d in doc["ports"]
        ),
        macs=tuple(
            MacEntry(
                mac=d["mac"],
                vlan=d["vlan"],
                if_index=d["if_index"],
                status=cast("MacStatus", _literal(d["status"], MacStatus)),
            )
            for d in doc["macs"]
        ),
        vlans=tuple(
            Vlan(d["vid"], d["name"], frozenset(d["egress"]), frozenset(d["untagged"])) for d in doc["vlans"]
        ),
        pvids=tuple((int(i), int(v)) for i, v in doc["pvids"]),
        stp=tuple(
            StpPort(d["if_index"], cast("StpState", _literal(d["state"], StpState))) for d in doc["stp"]
        ),
        lags=tuple(LagGroup(d["if_index"], d["name"], frozenset(d["members"])) for d in doc["lags"]),
    )
