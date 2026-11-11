"""SNMP over pysnmp (lextudio, asyncio API) behind the synchronous ``SnmpClient`` port.

This is the only module that imports ``pysnmp``. One private event loop runs on a daemon thread; the
sync methods submit coroutines to it. Requests to one host are limited to ``max_in_flight_per_host``
(default 1), and a request that times out is cancelled and awaited *before* its slot is released, so
an abandoned request never keeps talking to the agent.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Awaitable, Sequence
from typing import Any, TypeVar

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    bulk_walk_cmd,
    get_cmd,
    usmAesCfb128Protocol,
    usmDESPrivProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmNoAuthProtocol,
    usmNoPrivProtocol,
)
from pysnmp.proto import errind
from pysnmp.proto.rfc1902 import (
    Counter32,
    Counter64,
    Gauge32,
    Integer,
    IpAddress,
    ObjectIdentifier,
    OctetString,
    TimeTicks,
    Unsigned32,
)
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject

from netview.application.ports.snmp import (
    Oid,
    SnmpAuthError,
    SnmpError,
    SnmpTarget,
    SnmpTimeout,
    SnmpV2c,
    SnmpV3,
    SnmpValue,
)

log = logging.getLogger(__name__)

_T = TypeVar("_T")
_MAX_REPETITIONS = 25

_AUTH = {"none": usmNoAuthProtocol, "md5": usmHMACMD5AuthProtocol, "sha": usmHMACSHAAuthProtocol}
_PRIV = {"none": usmNoPrivProtocol, "des": usmDESPrivProtocol, "aes128": usmAesCfb128Protocol}

_AUTH_ERRORS: tuple[type[Exception], ...] = (
    errind.WrongDigest,
    errind.UnknownUserName,
    errind.DecryptionError,
    errind.UnsupportedSecurityLevel,
    errind.UnknownSecurityName,
)


def _credentials(target: SnmpTarget) -> CommunityData | UsmUserData:
    creds = target.credentials
    if isinstance(creds, SnmpV2c):
        return CommunityData(creds.community, mpModel=1)
    assert isinstance(creds, SnmpV3)
    return UsmUserData(
        creds.user,
        authKey=creds.auth_key if creds.auth_protocol != "none" else None,
        privKey=creds.priv_key if creds.priv_protocol != "none" else None,
        authProtocol=_AUTH[creds.auth_protocol],
        privProtocol=_PRIV[creds.priv_protocol],
    )


def _raise_for(indication: object, status: object) -> None:
    """Map pysnmp's error reporting to the port's exceptions. Never includes credentials."""
    if indication:
        if isinstance(indication, errind.RequestTimedOut):
            raise SnmpTimeout("no response from the SNMP agent")
        if isinstance(indication, _AUTH_ERRORS):
            raise SnmpAuthError(f"SNMP authentication failed: {type(indication).__name__}")
        raise SnmpError(str(indication))
    if status:
        pretty = getattr(status, "prettyPrint", None)
        raise SnmpError(pretty() if callable(pretty) else str(status))


def _convert(value: Any) -> SnmpValue:
    """pysnmp value to the port's value types. Subclasses are tested before their bases."""
    if isinstance(value, (NoSuchObject, NoSuchInstance, EndOfMibView)):
        return None
    if isinstance(value, IpAddress):
        return ".".join(str(b) for b in value.asOctets())
    if isinstance(value, (Counter32, Counter64, Gauge32, Unsigned32, TimeTicks)):
        return int(value)
    if isinstance(value, Integer):
        return int(value)
    if isinstance(value, OctetString):
        return bytes(value.asOctets())
    if isinstance(value, ObjectIdentifier):
        return tuple(int(x) for x in value)
    return None


def _oid_of(name: Any) -> Oid:
    return tuple(int(x) for x in name)


def _dotted(oid: Oid) -> str:
    return ".".join(str(x) for x in oid)


class PysnmpClient:
    def __init__(self, max_in_flight_per_host: int = 1) -> None:
        self._max_in_flight = max_in_flight_per_host
        self._slots: dict[str, threading.Semaphore] = {}
        self._slots_lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._engine: SnmpEngine | None = None
        self._closed = False
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _ensure_started(self) -> None:
        # the loop thread starts on first use, so a container that never polls SNMP costs nothing
        with self._start_lock:
            if self._thread is None and not self._closed:
                self._thread = threading.Thread(target=self._run_loop, name="netview-snmp", daemon=True)
                self._thread.start()

    def _slot(self, host: str) -> threading.Semaphore:
        with self._slots_lock:
            return self._slots.setdefault(host, threading.Semaphore(self._max_in_flight))

    def _get_engine(self) -> SnmpEngine:
        # only called on the loop thread
        if self._engine is None:
            self._engine = SnmpEngine()
        return self._engine

    def get(self, target: SnmpTarget, oids: Sequence[Oid]) -> dict[Oid, SnmpValue]:
        return self._call(target, self._get_async(target, list(oids)))

    def walk(self, target: SnmpTarget, prefix: Oid, max_rows: int = 10_000) -> list[tuple[Oid, SnmpValue]]:
        return self._call(target, self._walk_async(target, prefix, max_rows))

    def close(self) -> None:
        with self._start_lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        if thread is None:
            self._loop.close()
            return

        async def shutdown() -> None:
            if self._engine is not None:
                self._engine.close_dispatcher()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(5)
        except Exception:
            log.debug("SNMP engine shutdown failed", exc_info=True)
        self._loop.call_soon_threadsafe(self._loop.stop)
        thread.join(5)
        if not self._loop.is_running():
            self._loop.close()

    # -- plumbing ------------------------------------------------------------------------------

    def _call(self, target: SnmpTarget, coro: Awaitable[_T]) -> _T:
        if self._closed:
            raise SnmpError("SNMP client is closed")
        self._ensure_started()
        budget = target.timeout_s * (target.retries + 1) + 1
        slot = self._slot(target.host)
        slot.acquire()
        try:
            # wait_for cancels the request and waits for the cancellation to finish before it raises,
            # so the slot is only released once nothing is talking to the agent any more
            guarded = asyncio.wait_for(coro, budget)
            future = asyncio.run_coroutine_threadsafe(guarded, self._loop)
            try:
                return future.result(budget + 5)
            except (TimeoutError, concurrent.futures.TimeoutError) as exc:
                future.cancel()
                raise SnmpTimeout("no response from the SNMP agent") from exc
            except SnmpError:
                raise
            except Exception as exc:
                # pysnmp raises its own errors for bad hosts, short keys and the like; the port
                # contract is SnmpError only, and library messages may echo credentials
                raise SnmpError(f"SNMP request failed: {type(exc).__name__}") from None
        finally:
            slot.release()

    async def _transport(self, target: SnmpTarget) -> UdpTransportTarget:
        return await UdpTransportTarget.create(
            (target.host, target.port), timeout=target.timeout_s, retries=target.retries
        )

    async def _get_async(self, target: SnmpTarget, oids: list[Oid]) -> dict[Oid, SnmpValue]:
        if not oids:
            return {}
        indication, status, _index, binds = await get_cmd(
            self._get_engine(),
            _credentials(target),
            await self._transport(target),
            ContextData(),
            *[ObjectType(ObjectIdentity(_dotted(oid))) for oid in oids],
            lookupMib=False,
        )
        _raise_for(indication, status)
        found = {_oid_of(name): _convert(value) for name, value in binds}
        return {oid: found.get(oid) for oid in oids}

    async def _walk_async(
        self, target: SnmpTarget, prefix: Oid, max_rows: int
    ) -> list[tuple[Oid, SnmpValue]]:
        rows: list[tuple[Oid, SnmpValue]] = []
        transport = await self._transport(target)
        # lexicographicMode=False stops at the end of the subtree; the default walks to the end of the MIB
        walker = bulk_walk_cmd(
            self._get_engine(),
            _credentials(target),
            transport,
            ContextData(),
            0,
            _MAX_REPETITIONS,
            ObjectType(ObjectIdentity(_dotted(prefix))),
            lexicographicMode=False,
            maxRows=max_rows,
            lookupMib=False,
        )
        try:
            async for indication, status, _index, binds in walker:
                _raise_for(indication, status)
                for name, value in binds:
                    oid = _oid_of(name)
                    if oid[: len(prefix)] != prefix:
                        return rows
                    rows.append((oid, _convert(value)))
                    if len(rows) >= max_rows:
                        return rows
        finally:
            await walker.aclose()
        return rows
