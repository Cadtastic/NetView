"""Reading SNMP agents. The port plugins see as ``ctx.snmp``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

Oid = tuple[int, ...]
SnmpValue = int | str | bytes | Oid | None
# int: Integer, Counter32/64, Gauge32 and TimeTicks (hundredths of a second)
# str: IpAddress, as a dotted quad
# bytes: OctetString, raw
# Oid: an OBJECT IDENTIFIER value
# None: noSuchObject, noSuchInstance or endOfMibView


@dataclass(frozen=True)
class SnmpV2c:
    community: str

    def __repr__(self) -> str:
        return "SnmpV2c(community=***)"


@dataclass(frozen=True)
class SnmpV3:
    user: str
    auth_protocol: Literal["none", "md5", "sha"]
    auth_key: str | None
    priv_protocol: Literal["none", "des", "aes128"]
    priv_key: str | None

    def __repr__(self) -> str:
        return (
            f"SnmpV3(user={self.user!r}, auth_protocol={self.auth_protocol!r}, auth_key=***, "
            f"priv_protocol={self.priv_protocol!r}, priv_key=***)"
        )


@dataclass(frozen=True)
class SnmpTarget:
    host: str
    credentials: SnmpV2c | SnmpV3
    port: int = 161
    timeout_s: float = 2.0
    retries: int = 1


class SnmpError(Exception):
    """An SNMP request failed. The message never contains credentials."""


class SnmpTimeout(SnmpError):
    """No answer in time (also what a v2c agent does with a wrong community)."""


class SnmpAuthError(SnmpError):
    """The agent rejected the v3 user, digest or privacy key."""


class SnmpClient(Protocol):
    def get(self, target: SnmpTarget, oids: Sequence[Oid]) -> dict[Oid, SnmpValue]: ...

    def walk(
        self, target: SnmpTarget, prefix: Oid, max_rows: int = 10_000
    ) -> list[tuple[Oid, SnmpValue]]: ...


def parse_oid(text: str) -> Oid:
    """``"1.3.6"`` or ``".1.3.6"`` to ``(1, 3, 6)``; ``ValueError`` for anything else."""
    parts = text.strip().lstrip(".").split(".")
    if not parts or any(not p.isdigit() for p in parts):
        raise ValueError(f"not a numeric OID: {text!r}")
    return tuple(int(p) for p in parts)
