"""Request bodies checked by hand, and the JSON shapes the API returns.

Validation errors are ``ValueError`` with a plain message; the routes turn them into 422.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from .addresses import valid_address
from .model import Hop, Target, Trace
from .queue import VALID_INTERVALS

FAMILIES = ("ipv4", "ipv6")
MODES = ("trace", "ping")
NAME_MAX = 100


def _object(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("the body must be a JSON object")
    return body


def _address(value: Any) -> str:
    if not isinstance(value, str) or not valid_address(value.strip()):
        raise ValueError("address must be a host name or an IP address")
    return value.strip()


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("name is required")
    if len(value.strip()) > NAME_MAX:
        raise ValueError(f"name must be at most {NAME_MAX} characters")
    return value.strip()


def _family(value: Any) -> str:
    if value not in FAMILIES:
        raise ValueError("family must be ipv4 or ipv6")
    return str(value)


def _interval(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in VALID_INTERVALS:
        raise ValueError("interval_min must be 5, 15, 30 or 60")
    return value


def _enabled(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("enabled must be true or false")
    return value


def literal_family(address: str) -> str | None:
    """``ipv4`` or ``ipv6`` for an IP literal (whose own family wins over the field), else None."""
    try:
        return "ipv6" if ipaddress.ip_address(address).version == 6 else "ipv4"
    except ValueError:
        return None


def new_target(body: Any, default_family: str, default_interval: int) -> dict[str, Any]:
    """Fields for ``add_target``, with defaults filled in."""
    data = _object(body)
    address = _address(data.get("address"))
    family = _family(data.get("family", default_family))
    return {
        "name": _name(data.get("name")),
        "address": address,
        "family": literal_family(address) or family,
        "interval_min": _interval(data.get("interval_min", default_interval)),
        "enabled": _enabled(data.get("enabled", True)),
    }


def target_changes(body: Any, current: Target) -> dict[str, Any]:
    """Only the fields the body names, checked. A literal address fixes the family."""
    data = _object(body)
    out: dict[str, Any] = {}
    if "name" in data:
        out["name"] = _name(data["name"])
    if "address" in data:
        out["address"] = _address(data["address"])
    if "family" in data:
        out["family"] = _family(data["family"])
    if "interval_min" in data:
        out["interval_min"] = _interval(data["interval_min"])
    if "enabled" in data:
        out["enabled"] = _enabled(data["enabled"])
    literal = literal_family(out.get("address", current.address))
    if literal is not None and ("address" in out or "family" in out):
        out["family"] = literal
    return out


def trace_once(body: Any, default_family: str) -> tuple[str, str, str]:
    """``(address, family, mode)``."""
    data = _object(body)
    address = _address(data.get("address"))
    family = _family(data.get("family", default_family))
    family = literal_family(address) or family
    mode = data.get("mode", "trace")
    if mode not in MODES:
        raise ValueError("mode must be trace or ping")
    return address, family, str(mode)


# -- responses ---------------------------------------------------------------------------------


def target_json(target: Target, last: Trace | None = None, note: str = "") -> dict[str, Any]:
    return {
        "id": target.id,
        "name": target.name,
        "address": target.address,
        "family": target.family,
        "interval_min": target.interval_min,
        "enabled": target.enabled,
        "last": None
        if last is None
        else {
            "trace_id": last.id,
            "started_ms": last.started_ms,
            "status": last.status,
            "rtt_ms": last.rtt_ms,
            "loss_pct": last.loss_pct,
            "hop_count": last.hop_count,
        },
        "note": note,
    }


def hop_json(hop: Hop) -> dict[str, Any]:
    return {
        "n": hop.n,
        "ip": hop.ip,
        "rtts_ms": list(hop.rtts_ms),
        "city": hop.city,
        "region": hop.region,
        "country": hop.country,
        "lat": hop.lat,
        "lon": hop.lon,
        "asn": hop.asn,
        "as_org": hop.as_org,
        "placement": hop.placement,
        "plausible": hop.plausible,
    }


def trace_summary(trace: Trace) -> dict[str, Any]:
    """A trace without its hops, for lists."""
    return {
        "id": trace.id,
        "target_id": trace.target_id,
        "trigger": trace.trigger,
        "mode": trace.mode,
        "status": trace.status,
        "error": trace.error,
        "started_ms": trace.started_ms,
        "finished_ms": trace.finished_ms,
        "resolved_ip": trace.resolved_ip,
        "family": trace.family,
        "reached": trace.reached,
        "hop_count": trace.hop_count,
        "rtt_ms": trace.rtt_ms,
        "loss_pct": trace.loss_pct,
        "jitter_ms": trace.jitter_ms,
        "ping_min_ms": trace.ping_min_ms,
        "ping_max_ms": trace.ping_max_ms,
    }


def trace_json(trace: Trace) -> dict[str, Any]:
    return {**trace_summary(trace), "hops": [hop_json(h) for h in trace.hops]}


def live_json(
    snapshot_id: int,
    status: str,
    error: str | None,
    started_ms: int,
    hops: tuple[Hop, ...],
    target_id: int | None,
    mode: str,
    trigger: str,
) -> dict[str, Any]:
    """A trace that is queued, running, or finished without being saved."""
    return {
        "id": snapshot_id,
        "target_id": target_id,
        "trigger": trigger,
        "mode": mode,
        "status": status,
        "error": error,
        "started_ms": started_ms,
        "finished_ms": None,
        "resolved_ip": None,
        "family": None,
        "reached": False,
        "hop_count": len(hops),
        "rtt_ms": None,
        "loss_pct": None,
        "jitter_ms": None,
        "ping_min_ms": None,
        "ping_max_ms": None,
        "hops": [hop_json(h) for h in hops],
    }
