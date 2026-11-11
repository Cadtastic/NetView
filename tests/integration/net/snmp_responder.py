"""A real pysnmp command responder on 127.0.0.1, for testing the SNMP adapter end to end."""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp, context
from pysnmp.proto.api import v2c

SYS_DESCR = (1, 3, 6, 1, 2, 1, 1, 1)
SYS_UPTIME = (1, 3, 6, 1, 2, 1, 1, 3)
IF_DESCR = (1, 3, 6, 1, 2, 1, 2, 2, 1, 2)
IF_TYPE = (1, 3, 6, 1, 2, 1, 2, 2, 1, 3)
IF_HC_IN = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 6)
BIG_COUNTER = 2**40 + 5


@dataclass(frozen=True)
class Responder:
    port: int
    community: str = "public"
    v3_user: str = "nv"
    v3_auth_key: str = "authkey123"
    v3_priv_key: str = "privkey123"


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _build(port: int) -> engine.SnmpEngine:
    snmp_engine = engine.SnmpEngine()
    config.add_transport(
        snmp_engine, udp.DOMAIN_NAME, udp.UdpTransport().open_server_mode(("127.0.0.1", port))
    )
    config.add_v1_system(snmp_engine, "area", "public")
    config.add_vacm_user(snmp_engine, 2, "area", "noAuthNoPriv", (1, 3, 6), (1, 3, 6))
    config.add_v3_user(
        snmp_engine,
        "nv",
        config.USM_AUTH_HMAC96_SHA,
        "authkey123",
        config.USM_PRIV_CBC56_DES,
        "privkey123",
    )
    config.add_vacm_user(snmp_engine, 3, "nv", "authPriv", (1, 3, 6), (1, 3, 6))

    snmp_context = context.SnmpContext(snmp_engine)
    builder = snmp_context.get_mib_instrum().get_mib_builder()
    mib_scalar, mib_instance = builder.import_symbols("SNMPv2-SMI", "MibScalar", "MibScalarInstance")

    exports: list[object] = []

    def column(oid: tuple[int, ...], syntax: object, values: dict[tuple[int, ...], object]) -> None:
        exports.append(mib_scalar(oid, syntax))
        for index, value in values.items():
            exports.append(mib_instance(oid, index, value))

    # sysDescr and sysUpTime come from the engine's built-in SNMPv2-MIB
    column(IF_DESCR, v2c.OctetString(), {(i,): v2c.OctetString(f"port {i}") for i in range(1, 6)})
    column(IF_TYPE, v2c.Integer32(), {(i,): v2c.Integer32(6) for i in range(1, 6)})
    column(IF_HC_IN, v2c.Counter64(), {(1,): v2c.Counter64(BIG_COUNTER)})
    builder.export_symbols("__TEST_MIB", *exports)

    cmdrsp.GetCommandResponder(snmp_engine, snmp_context)
    cmdrsp.NextCommandResponder(snmp_engine, snmp_context)
    cmdrsp.BulkCommandResponder(snmp_engine, snmp_context)
    return snmp_engine


@pytest.fixture(scope="module")
def snmp_responder() -> Iterator[Responder]:
    port = _free_udp_port()
    ready = threading.Event()
    stop: dict[str, object] = {}

    def run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        snmp_engine = _build(port)
        snmp_engine.transport_dispatcher.job_started(1)
        stop["loop"] = loop
        loop.call_soon(ready.set)
        try:
            loop.run_forever()
        finally:
            snmp_engine.transport_dispatcher.close_dispatcher()
            loop.close()

    thread = threading.Thread(target=run, name="snmp-test-responder", daemon=True)
    thread.start()
    assert ready.wait(10), "responder did not start"
    try:
        yield Responder(port)
    finally:
        loop = stop["loop"]
        assert isinstance(loop, asyncio.AbstractEventLoop)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
