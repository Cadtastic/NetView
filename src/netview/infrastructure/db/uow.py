"""SQL unit of work."""

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from netview.infrastructure.db.repositories import (
    SqlDeviceRepository,
    SqlEventRepository,
    SqlIdentityRepository,
    SqlInspectionRepository,
    SqlNicknameRepository,
    SqlPluginStateRepository,
    SqlWatchRepository,
)


class SqlUnitOfWork:
    """One session per unit of work; rolls back on exit unless committed."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session: Session = session_factory()
        self.devices = SqlDeviceRepository(self.session)
        self.identity = SqlIdentityRepository(self.session)
        self.nicknames = SqlNicknameRepository(self.session)
        self.watches = SqlWatchRepository(self.session)
        self.events = SqlEventRepository(self.session)
        self.inspections = SqlInspectionRepository(self.session)
        self.plugin_state = SqlPluginStateRepository(self.session)
        self.committed = False

    def commit(self) -> None:
        self.session.commit()
        self.committed = True

    def rollback(self) -> None:
        self.session.rollback()

    def __enter__(self) -> "SqlUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self.committed:
                self.session.rollback()
        finally:
            self.session.close()
