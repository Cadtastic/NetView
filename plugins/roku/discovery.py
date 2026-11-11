"""Built-in scan: SSDP ``roku:ecp`` search plus a port 8060 sweep of the subnet (spec 5.1)."""

from __future__ import annotations

import ipaddress
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from netview.sdk import ServiceProbes

from .addresses import is_allowed_ip
from .ecp import ECP_PORT, DeviceInfo, EcpClient, EcpError
from .model import ScanHit

MAX_SWEEP = 1024
SSDP_TARGET = "roku:ecp"

_LOCATION = re.compile(rf"^http://(\d{{1,3}}(?:\.\d{{1,3}}){{3}}):{ECP_PORT}(?:/|$)")


@dataclass(frozen=True)
class ScanResult:
    hits: list[ScanHit]
    subnet: str | None
    by_ssdp: int
    by_sweep: int
    duration_s: float


def _ssdp_ips(probes: ServiceProbes, timeout_s: float) -> set[str]:
    ips: set[str] = set()
    for entry in probes.ssdp_search(timeout_s=timeout_s, st=SSDP_TARGET):
        match = _LOCATION.match(entry.location)
        if match and is_allowed_ip(match.group(1)):
            ips.add(match.group(1))
    return ips


def _sweep_ips(subnet: str | None) -> list[str]:
    if not subnet:
        return []
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return []
    if network.version != 4 or network.num_addresses > MAX_SWEEP:
        return []
    return [str(ip) for ip in network.hosts() if is_allowed_ip(str(ip))]


def scan(
    probes: ServiceProbes,
    ecp: EcpClient,
    subnet: str | None,
    timeout_s: float,
    workers: int = 128,
    clock: Callable[[], float] = time.monotonic,
) -> ScanResult:
    started = clock()
    sweep_ips = _sweep_ips(subnet)
    swept = set(sweep_ips)

    def fetch(ip: str) -> tuple[str, DeviceInfo | None]:
        try:
            return ip, ecp.device_info(ip)
        except EcpError:
            return ip, None

    with ThreadPoolExecutor(max_workers=workers + 1) as pool:
        ssdp_future = pool.submit(_ssdp_ips, probes, timeout_s)
        sweep_results = list(pool.map(fetch, sweep_ips)) if sweep_ips else []
        ssdp_ips = ssdp_future.result()
        extra = sorted(ssdp_ips - swept)
        extra_results = list(pool.map(fetch, extra)) if extra else []

    infos = dict(sweep_results + extra_results)
    hits: list[ScanHit] = []
    by_ssdp = by_sweep = 0
    for ip, info in infos.items():
        if info is None:
            continue
        in_ssdp = ip in ssdp_ips
        in_sweep = ip in swept
        if not (in_ssdp or in_sweep):
            continue
        by_ssdp += in_ssdp
        by_sweep += in_sweep
        found_by = "ssdp+sweep" if in_ssdp and in_sweep else "ssdp" if in_ssdp else "sweep"
        hits.append(
            ScanHit(
                ip=ip,
                serial=info.serial,
                name=info.name,
                model=info.model,
                location=info.location,
                tv=info.tv,
                found_by=found_by,
            )
        )
    hits.sort(key=lambda h: ipaddress.IPv4Address(h.ip))
    return ScanResult(hits, subnet, by_ssdp, by_sweep, clock() - started)
