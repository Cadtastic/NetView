"""Who wins when two plugins carry the same guid: a fixed order, so a copied folder never wins."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

TIER_BUILTIN = 0
TIER_PLUGIN_DIRS = 1
TIER_DATA_DIR = 2


@dataclass(frozen=True)
class Candidate:
    """One plugin offered for loading; card_key is ``entry_point:<name>`` or ``folder:<resolved path>``."""

    card_key: str
    guid: str | None
    tier: int
    folder: str | None


def pick_winners(
    cands: Sequence[Candidate], last_folder: Mapping[str, str]
) -> tuple[list[Candidate], dict[str, Candidate]]:
    """The winner of every guid, and for each loser's card_key the candidate that beat it.

    Per guid: a built-in first; then the folder it was loaded from last time; then the lower tier; then the
    folder path. A candidate without a guid is neither (the caller makes it a failed card).
    """
    by_guid: dict[str, list[Candidate]] = {}
    for cand in cands:
        if cand.guid is not None:
            by_guid.setdefault(cand.guid, []).append(cand)

    winner_of: dict[str, Candidate] = {}
    for guid, group in by_guid.items():
        winner_of[guid] = min(
            group,
            key=lambda c: (
                c.tier != TIER_BUILTIN,
                c.folder is None or c.folder != last_folder.get(guid),
                c.tier,
                c.folder or "",
                c.card_key,
            ),
        )

    winners: list[Candidate] = []
    losers: dict[str, Candidate] = {}
    for cand in cands:
        if cand.guid is None:
            continue
        winner = winner_of[cand.guid]
        if cand is winner:
            winners.append(cand)
        else:
            losers[cand.card_key] = winner
    return winners, losers
