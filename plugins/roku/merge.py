"""Merge scan results into the saved list (spec 5.2)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from .model import SavedTv, ScanHit


@dataclass(frozen=True)
class MergeResult:
    tvs: list[SavedTv]
    added: int
    updated: int


def _find(saved: list[SavedTv], hit: ScanHit) -> int | None:
    if hit.serial:
        for i, tv in enumerate(saved):
            if tv.serial == hit.serial:
                return i
    for i, tv in enumerate(saved):
        if tv.ip == hit.ip and not (tv.serial and hit.serial):
            return i
    return None


def merge(saved: list[SavedTv], hits: list[ScanHit], now_iso: str, new_id: Callable[[], str]) -> MergeResult:
    tvs = list(saved)
    added = 0
    updated: set[str] = set()
    created: set[str] = set()
    for hit in hits:
        i = _find(tvs, hit)
        if i is None:
            tv = SavedTv(
                id=new_id(),
                serial=hit.serial,
                ip=hit.ip,
                name=hit.name,
                label="",
                model=hit.model,
                location=hit.location,
                tv=hit.tv,
                found_by=hit.found_by,
                first_seen=now_iso,
                last_seen=now_iso,
            )
            tvs.append(tv)
            created.add(tv.id)
            added += 1
            continue
        old = tvs[i]
        tvs[i] = replace(
            old,
            ip=hit.ip,
            serial=old.serial or hit.serial,
            name=hit.name or old.name,
            model=hit.model or old.model,
            location=hit.location or old.location,
            tv=hit.tv,
            found_by=hit.found_by or old.found_by,
            last_seen=now_iso,
        )
        if old.id not in created:
            updated.add(old.id)
    return MergeResult(tvs, added, len(updated))
