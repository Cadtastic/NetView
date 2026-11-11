from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from snmp_responder import (
    BIG_COUNTER,
    IF_DESCR,
    IF_HC_IN,
    SYS_DESCR,
    SYS_UPTIME,
    Responder,
)

from netview.infrastructure.net.snmp import PysnmpClient
from netview.sdk import SnmpAuthError, SnmpError, SnmpTarget, SnmpTimeout, SnmpV2c, SnmpV3

pytestmark = pytest.mark.snmp


@pytest.fixture
def client() -> Iterator[PysnmpClient]:
    c = PysnmpClient()
    try:
        yield c
    finally:
        c.close()


def v2c(r: Responder, community: str = "public", timeout_s: float = 2.0, retries: int = 1) -> SnmpTarget:
    return SnmpTarget("127.0.0.1", SnmpV2c(community), port=r.port, timeout_s=timeout_s, retries=retries)


def v3(r: Responder, auth_key: str | None = None) -> SnmpTarget:
    creds = SnmpV3(r.v3_user, "sha", auth_key or r.v3_auth_key, "des", r.v3_priv_key)
    return SnmpTarget("127.0.0.1", creds, port=r.port, timeout_s=1.0, retries=0)


def test_get_v2c_sysdescr(client: PysnmpClient, snmp_responder: Responder) -> None:
    oid = (*SYS_DESCR, 0)
    value = client.get(v2c(snmp_responder), [oid])[oid]
    assert isinstance(value, bytes)
    assert value.startswith(b"PySNMP engine")


def test_walk_v2c_ifdescr_returns_five_rows_in_order(client: PysnmpClient, snmp_responder: Responder) -> None:
    rows = client.walk(v2c(snmp_responder), IF_DESCR)
    assert [oid for oid, _ in rows] == [(*IF_DESCR, i) for i in range(1, 6)]
    assert [v for _, v in rows] == [f"port {i}".encode() for i in range(1, 6)]


def test_walk_stops_at_prefix_end(client: PysnmpClient, snmp_responder: Responder) -> None:
    # ifType rows follow ifDescr in the MIB; they must not be returned
    rows = client.walk(v2c(snmp_responder), IF_DESCR)
    assert len(rows) == 5
    assert all(oid[: len(IF_DESCR)] == IF_DESCR for oid, _ in rows)


def test_walk_respects_max_rows(client: PysnmpClient, snmp_responder: Responder) -> None:
    assert len(client.walk(v2c(snmp_responder), IF_DESCR, max_rows=3)) == 3


def test_timeticks_is_int(client: PysnmpClient, snmp_responder: Responder) -> None:
    oid = (*SYS_UPTIME, 0)
    value = client.get(v2c(snmp_responder), [oid])[oid]
    assert type(value) is int
    assert value >= 0


def test_counter64_is_int(client: PysnmpClient, snmp_responder: Responder) -> None:
    oid = (*IF_HC_IN, 1)
    value = client.get(v2c(snmp_responder), [oid])[oid]
    assert value == BIG_COUNTER
    assert type(value) is int


def test_missing_oid_is_none(client: PysnmpClient, snmp_responder: Responder) -> None:
    oid = (1, 3, 6, 1, 2, 1, 1, 99, 0)
    assert client.get(v2c(snmp_responder), [oid]) == {oid: None}


def test_get_v3_authpriv(client: PysnmpClient, snmp_responder: Responder) -> None:
    oid = (*SYS_DESCR, 0)
    value = client.get(v3(snmp_responder), [oid])[oid]
    assert isinstance(value, bytes)
    assert value.startswith(b"PySNMP engine")


def test_wrong_community_times_out_as_snmp_timeout(client: PysnmpClient, snmp_responder: Responder) -> None:
    target = v2c(snmp_responder, "wrongcomm", timeout_s=0.5, retries=0)
    with pytest.raises(SnmpTimeout) as info:
        client.get(target, [(*SYS_DESCR, 0)])
    assert "wrongcomm" not in str(info.value)


def test_wrong_v3_key_is_snmp_auth_error(client: PysnmpClient, snmp_responder: Responder) -> None:
    with pytest.raises(SnmpAuthError) as info:
        client.get(v3(snmp_responder, auth_key="notthekey99"), [(*SYS_DESCR, 0)])
    assert "notthekey99" not in str(info.value)


@pytest.fixture
def silent_port() -> Iterator[int]:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    try:
        yield int(s.getsockname()[1])
    finally:
        s.close()


def test_timeout_releases_slot(client: PysnmpClient, silent_port: int, snmp_responder: Responder) -> None:
    dead = SnmpTarget("127.0.0.1", SnmpV2c("public"), port=silent_port, timeout_s=0.3, retries=0)
    with pytest.raises(SnmpTimeout):
        client.get(dead, [(*SYS_DESCR, 0)])
    # same host, another port: the per-host slot must be free again at once
    started = time.monotonic()
    assert client.get(v2c(snmp_responder), [(*SYS_DESCR, 0)])
    assert time.monotonic() - started < 1.0


def test_requests_to_one_host_are_serialised(
    client: PysnmpClient, snmp_responder: Responder, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}
    real = client._walk_async

    async def watched(*args: Any, **kwargs: Any) -> Any:
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        try:
            await asyncio.sleep(0.05)
            return await real(*args, **kwargs)
        finally:
            with lock:
                state["now"] -= 1

    monkeypatch.setattr(client, "_walk_async", watched)
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(len(client.walk(v2c(snmp_responder), IF_DESCR))))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert results == [5, 5, 5, 5]
    assert state["peak"] == 1


def test_unresolvable_host_is_snmp_error(client: PysnmpClient) -> None:
    target = SnmpTarget("no-such-host.invalid", SnmpV2c("public"), timeout_s=0.5, retries=0)
    with pytest.raises(SnmpError):
        client.get(target, [(*SYS_DESCR, 0)])


def test_short_v3_auth_key_is_snmp_error_without_key(client: PysnmpClient, snmp_responder: Responder) -> None:
    with pytest.raises(SnmpError) as info:
        client.get(v3(snmp_responder, auth_key="short6"), [(*SYS_DESCR, 0)])
    assert "short6" not in str(info.value)
