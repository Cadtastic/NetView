"""Line two saved routes up hop by hop (spec 9)."""

from __future__ import annotations

from collections.abc import Sequence

from .changes import first_difference, parse_signature
from .model import Hop, Trace


def _located(hop: Hop | None) -> bool:
    return hop is not None and hop.placement == "located"


def differs(a: Hop | None, b: Hop | None) -> bool:
    """Two hops differ when their (ASN, city) do. A silent or missing hop differs only from a located one."""
    if a is not None and b is not None and _located(a) and _located(b):
        return (a.asn, a.city) != (b.asn, b.city)
    return _located(a) != _located(b)


def pairs(a: Sequence[Hop], b: Sequence[Hop]) -> list[tuple[int, Hop | None, Hop | None]]:
    """``(hop number, hop of a, hop of b)`` for every number either route has."""
    by_a = {h.n: h for h in a}
    by_b = {h.n: h for h in b}
    return [(n, by_a.get(n), by_b.get(n)) for n in sorted(by_a.keys() | by_b.keys())]


def _starts(hops: Sequence[Hop]) -> list[int]:
    """The first hop number of each signature entry (located hops, consecutive duplicates merged)."""
    out: list[int] = []
    last: tuple[int | None, str] | None = None
    for h in hops:
        if h.placement != "located":
            continue
        key = (h.asn, h.city)
        if key != last:
            out.append(h.n)
            last = key
    return out


def split_after(a: Trace, b: Trace) -> int | None:
    """The hop number before the first located hop where the two routes part, or None if they agree."""
    index = first_difference(parse_signature(a.signature), parse_signature(b.signature))
    if index is None:
        return None
    firsts = [s[index] for s in (_starts(a.hops), _starts(b.hops)) if index < len(s)]
    return max(min(firsts) - 1, 0) if firsts else None
