"""Shared helper: the label used in event texts."""

from netview.application.ports.uow import UnitOfWork
from netview.domain.naming import NameClaim, best_claim, display_name
from netview.domain.watch import Watch


class LabelResolver:
    """Display names for event texts. Claims, nicknames and watches are loaded once, on first use.

    Call ``reset`` after changing any of them in the same unit of work (for example after a rekey).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow
        self._claims: dict[str, list[NameClaim]] | None = None
        self._nicknames: dict[str, str] = {}
        self._watches: dict[str, Watch] = {}

    def reset(self) -> None:
        self._claims = None

    def label(self, key: str, ip: str | None) -> str:
        """Nickname, best claim or watch label for ``key`` (watched by ``ip``), or '' when none."""
        if self._claims is None:
            self._claims = self._uow.identity.all_claims()
            self._nicknames = self._uow.nicknames.all()
            self._watches = {w.ip: w for w in self._uow.watches.list()}
        watch = self._watches.get(ip) if ip else None
        return display_name(
            self._nicknames.get(key),
            best_claim(self._claims.get(key, [])),
            watch.label if watch else None,
        )
