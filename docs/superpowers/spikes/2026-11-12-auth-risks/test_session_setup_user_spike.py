"""Spike: mid-session disable (incl. SSE), setup race on NetView's real SQLite engine, username normalization."""

import asyncio
import re
import threading
import time
import unicodedata
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from netview.infrastructure.db.engine import make_engine

# ---------- Risk 2: a user disabled while signed in -------------------------------------------------

SESSIONS: dict[str, str] = {}          # token -> username
DISABLED: set[str] = set()
KEEPALIVE_S = 0.05


def resolve(token: str | None) -> str | None:
    user = SESSIONS.get(token or "")
    return None if user is None or user in DISABLED else user


def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/state")
    def state(request: Request) -> Any:
        user = resolve(request.cookies.get("netview_session"))
        if user is None:
            return StreamingResponse(iter([b'{"error":"sign in required"}']), status_code=401)
        return {"user": user}

    @app.get("/api/v1/stream")
    async def stream(request: Request) -> StreamingResponse:
        token = request.cookies.get("netview_session")
        if resolve(token) is None:
            return StreamingResponse(iter([b""]), status_code=401)

        async def frames() -> Any:
            while True:
                await asyncio.sleep(KEEPALIVE_S)
                if resolve(token) is None:      # the fix: re-check at every keep-alive
                    return
                yield b": keep-alive\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return app


def test_disabled_user_next_request_is_401() -> None:
    SESSIONS.clear(); DISABLED.clear(); SESSIONS["t1"] = "kdoe"
    c = TestClient(build_app(), cookies={"netview_session": "t1"})
    assert c.get("/api/v1/state").status_code == 200
    DISABLED.add("kdoe")
    assert c.get("/api/v1/state").status_code == 401


@pytest.mark.parametrize("how", ["disable", "delete_session"])
def test_open_stream_ends_after_user_disabled(how: str) -> None:
    SESSIONS.clear(); DISABLED.clear(); SESSIONS["t2"] = "kdoe"
    c = TestClient(build_app(), cookies={"netview_session": "t2"})
    ended = threading.Event()
    frames: list[bytes] = []

    def reader() -> None:
        with c.stream("GET", "/api/v1/stream") as r:
            for chunk in r.iter_bytes():
                frames.append(chunk)
        ended.set()

    threading.Thread(target=reader, daemon=True).start()
    time.sleep(KEEPALIVE_S * 4)
    assert frames, "stream should be live before the change"
    if how == "disable":
        DISABLED.add("kdoe")
    else:
        SESSIONS.pop("t2")
    assert ended.wait(KEEPALIVE_S * 10), "stream did not close"


# ---------- Risk 3: two setup requests at once ------------------------------------------------------

def make_users_table(engine: sa.Engine, with_index: bool) -> sa.Table:
    md = sa.MetaData()
    users = sa.Table(
        "users", md,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String, nullable=False, unique=True),
        sa.Column("builtin", sa.Boolean, nullable=False, default=False),
    )
    if with_index:
        sa.Index("uq_users_one_builtin", users.c.builtin, unique=True, sqlite_where=users.c.builtin.is_(True),
                 postgresql_where=users.c.builtin.is_(True))
    md.create_all(engine)
    return users


def race(engine: sa.Engine, users: sa.Table, n: int = 8) -> tuple[int, list[str]]:
    sessions = sessionmaker(engine)
    barrier = threading.Barrier(n)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(i: int) -> None:
        barrier.wait()
        try:
            with sessions() as s, s.begin():
                count = s.execute(sa.select(sa.func.count()).select_from(users)).scalar_one()
                if count:
                    raise RuntimeError("conflict: setup already done")
                time.sleep(0.02)  # widen the window between the check and the insert
                s.execute(users.insert().values(username=f"admin{i}", builtin=True))
            result = "created"
        except Exception as exc:  # noqa: BLE001
            result = type(exc).__name__
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with sessions() as s:
        rows = s.execute(sa.select(sa.func.count()).select_from(users)).scalar_one()
    return rows, outcomes


def test_setup_race_netview_engine_begin_immediate(tmp_path: Any) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'nv.db'}")
    users = make_users_table(engine, with_index=False)
    rows, outcomes = race(engine, users)
    assert rows == 1 and outcomes.count("created") == 1, outcomes


def test_setup_race_plain_engine_needs_the_index(tmp_path: Any) -> None:
    """Without BEGIN IMMEDIATE (e.g. another database), the partial unique index is the backstop."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'plain.db'}", connect_args={"check_same_thread": False})
    users = make_users_table(engine, with_index=True)
    rows, outcomes = race(engine, users)
    assert rows == 1 and outcomes.count("created") == 1, outcomes


def test_partial_index_allows_many_ordinary_users(tmp_path: Any) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'nv2.db'}")
    users = make_users_table(engine, with_index=True)
    with engine.begin() as c:
        c.execute(users.insert(), [{"username": f"u{i}", "builtin": False} for i in range(5)])
        c.execute(users.insert().values(username="admin", builtin=True))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as c:
        c.execute(users.insert().values(username="admin2", builtin=True))


# ---------- Risk 4: usernames that differ only in case or spaces ------------------------------------

_ALLOWED = re.compile(r"^[a-z0-9._@+-]{1,128}$")


def normalize_username(raw: str) -> str:
    value = unicodedata.normalize("NFKC", raw).strip().casefold()
    if not _ALLOWED.fullmatch(value):
        raise ValueError(f"invalid username {raw!r}")
    return value


@pytest.mark.parametrize("raw", ["admin", " Admin ", "ADMIN", "\tadmin\n", "ＡＤＭＩＮ", "Admin "])
def test_same_user(raw: str) -> None:
    assert normalize_username(raw) == "admin"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "ad min",
        "аdmin",          # Cyrillic а: a lookalike, rejected instead of becoming a second "admin"
        "admın",          # dotless ı
        "admin​",    # zero-width space
        "x" * 129,
    ],
)
def test_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_username(raw)


def test_emails_allowed() -> None:
    assert normalize_username("KDoe+lab@Corp.com") == "kdoe+lab@corp.com"


def test_negative_control_race_is_real_without_either_fix(tmp_path: Any) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bare.db'}", connect_args={"check_same_thread": False})
    users = make_users_table(engine, with_index=False)
    rows, outcomes = race(engine, users)
    assert rows > 1, f"expected the unprotected race to create several admins, got {rows}: {outcomes}"
