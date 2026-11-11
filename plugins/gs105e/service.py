"""Joins the collector, analysis, storage and ``ctx.core``: one method per job, plus the read models.

This is where the session rules live (spec 5.3): one login at a time, a lost session is logged into once,
a second loss within ten minutes pauses polling, and a refused password stops it until the user acts.
"""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Any, Literal, cast

from netview.sdk import DeviceView, EventKind, Hint, NameClaim, PluginContext, TypeClaim

from .analysis import (
    COUNTERS_RESET_TEXT,
    LOGIN_FAILED_TEXT,
    PAUSED_ANOTHER_LOGIN_TEXT,
    REACHABLE_TEXT,
    UNREACHABLE_TEXT,
    compute_rates,
    counters_reset,
    crc_alerts,
    diff,
    merge_snapshot,
)
from .client import (
    AuthFailed,
    Fetch,
    SessionLost,
    SwitchSession,
    Unreachable,
    UnsupportedSwitch,
)
from .collector import read_config, read_counters, read_status
from .model import PortCounters, PortRates, Snapshot
from .pages import LOGOUT, SWITCH_INFO, PageChanged, parse_switch_info
from .settings import Gs105eSettings
from .storage import SwitchStore

SOURCE = "GS105E"
SWITCH_ID = "gs105e"
NAME_RANK = 8
MAX_BACKOFF_S = 300
MASK = "********"
RELOGIN_WINDOW_MS = 600_000
TESTED_FIRMWARE = frozenset({"V1.6.0.11"})
PORT_COUNT = 5
NOT_CONFIGURED = "not configured"
LOGIN_FAILED_REASON = "login failed; press Test connection"
PAUSED_REASON = "polling is paused"
_SWITCH_TYPE_REASON = "NETGEAR GS105E web interface"
_HOUR_MS = 3_600_000
_DAY_MS = 86_400_000
_SHUTDOWN_WAIT_S = 10.0
_LOCK_WAIT_S = 1.0  # how long pause() and settings_changed() wait for a running poll
_CONFIG_GROUPS = ("vlans", "qos", "igmp", "mirror", "management")

Resolution = Literal["raw", "5m"]
PauseReason = Literal["user", "another_login"]
Step = Callable[[SwitchSession, int], None]


class _Paused(Exception):
    """Raised inside a poll once the service has paused itself; the event is already out."""


class _Interrupted(Exception):
    """Raised before a request when a pause or a connection change makes the running poll pointless."""


class Gs105eService:
    def __init__(
        self,
        ctx: PluginContext,
        store_factory: Callable[[str], SwitchStore],
        fetch: Fetch,
    ) -> None:
        self._ctx = ctx
        self._store = store_factory(SWITCH_ID)
        self._fetch = fetch
        # One lock around each whole poll and each Test connection: the scheduler runs this plugin's jobs
        # on different threads, and a SwitchSession is not thread-safe.
        self._lock = threading.Lock()
        self._current: Snapshot | None = self._load_snapshot()
        self._session: SwitchSession | None = None
        self._session_key: tuple[str, int, str | None, int] | None = None
        self._connection = self._connection_key()
        self._pause_guard = threading.Lock()  # pause state is read and written without the poll lock
        self._pending_reset = False  # the connection changed: whoever holds the lock next drops the session
        self._bypass = False  # Test connection is allowed to talk while paused
        self._generation = 0  # counts connection changes, so an old login's refusal cannot stop new ones
        self._stopped = False  # the switch refused the password: no login until the user acts
        self._paused_until_ms: int | None = None
        self._pause_reason: PauseReason | None = None
        self._last_relogin_ms: int | None = None
        self._reachable: bool | None = None
        self._last_poll_ms: int | None = None
        self._errors: dict[str, str] = {}  # group -> its latest scrubbed error
        self._failures: dict[str, int] = {}
        self._next_allowed: dict[str, int] = {}
        self._last_counters: dict[int, PortCounters] = {}
        self._rates: dict[int, PortRates] = {}
        self._crc_alerted: dict[int, int] = {}
        self._claimed: dict[str, tuple[str, str]] = {}

    # ---- helpers -------------------------------------------------------------------------------

    @property
    def settings(self) -> Gs105eSettings:
        settings: Gs105eSettings = self._ctx.settings
        return settings

    def _connection_key(self) -> tuple[str, int, str | None]:
        s = self.settings
        return s.host, s.port, s.password_text()

    def _load_snapshot(self) -> Snapshot | None:
        try:
            return self._store.load_snapshot()
        except Exception:  # a missing or unreadable snapshot only means the next polls are baselines
            self._ctx.log.warning("could not load the stored GS105E snapshot", exc_info=True)
            return None

    def _scrub(self, text: str) -> str:
        password = self.settings.password_text()
        return text.replace(password, MASK) if password else text

    def _describe(self, exc: BaseException) -> str:
        text = str(exc)
        return self._scrub(f"{type(exc).__name__}: {text}" if text else type(exc).__name__)

    def _event(self, text: str) -> None:
        self._ctx.core.add_event(EventKind.PLUGIN, text, self.settings.host)

    def _own_ip(self) -> str | None:
        """The IPv4 address netview reaches the switch from, or None when unknown or not valid."""
        host = getattr(self._ctx.core, "host", None)  # the test fake has no host()
        if host is None:
            return None
        try:
            ip = host().ip
            return str(ipaddress.IPv4Address(ip)) if isinstance(ip, str) else None
        except Exception:
            return None

    # ---- the session ---------------------------------------------------------------------------

    def _drop_session(self) -> None:
        """Log out (best effort) and forget the session. The lock must be held."""
        self._logout()
        self._session = None
        self._session_key = None

    def _interrupted(self) -> bool:
        return self._pause_active(self._ctx.clock.now_ms()) or self._pending_reset

    def _guarded_fetch(
        self,
        host: str,
        port: int,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        """Every request goes through here, so a pause or new settings stop a poll between two pages."""
        if path != LOGOUT and not self._bypass and self._interrupted():
            raise _Interrupted
        return self._fetch(host, port, method, path, body, headers, timeout_s)

    def _apply_reset(self) -> None:
        """Apply a connection change recorded by ``settings_changed``. The lock must be held."""
        if self._pending_reset:
            self._pending_reset = False
            self._last_relogin_ms = None
            self._last_counters = {}
            self._rates = {}
            self._drop_session()

    def _settle(self) -> None:
        """At the end of a locked section: honour a pause or connection change that arrived meanwhile."""
        if self._pause_active(self._ctx.clock.now_ms()):
            self._logout()
        self._apply_reset()

    def _logout(self) -> None:
        session = self._session
        if session is not None and session.logged_in:
            session.logout()

    def _ensure_session(self) -> SwitchSession:
        """The logged-in session, logging in on demand. The lock must be held."""
        s = self.settings
        key = (s.host, s.port, s.password_text(), s.page_gap_ms)
        if self._session is None or self._session_key != key:
            self._drop_session()
            self._session = SwitchSession(
                s.host, s.port, s.password_text() or "", self._guarded_fetch, gap_s=s.page_gap_ms / 1000
            )
            self._session_key = key
        if not self._session.logged_in:
            self._session.login()
        return self._session

    def _with_session(self, step: Step, now: int) -> None:
        """Run a step, logging in again once when the switch forgets the session."""
        for _ in range(2):
            session = self._ensure_session()
            try:
                step(session, now)
                return
            except SessionLost:
                recent = self._last_relogin_ms
                if recent is not None and now - recent < RELOGIN_WINDOW_MS:
                    self._pause_after_second_loss()
                    raise _Paused from None
                self._last_relogin_ms = now
        # the retry is the second loss in a row, which the check above has already turned into a pause
        self._pause_after_second_loss()
        raise _Paused

    def _pause_after_second_loss(self) -> None:
        self._set_pause("another_login")
        self._logout()
        self._event(PAUSED_ANOTHER_LOGIN_TEXT)

    # ---- pause, resume, shutdown, settings -----------------------------------------------------

    def _set_pause(self, reason: PauseReason) -> None:
        with self._pause_guard:
            self._paused_until_ms = self._ctx.clock.now_ms() + self.settings.pause_minutes * 60_000
            self._pause_reason = reason
            self._last_relogin_ms = None

    def pause(self, reason: PauseReason = "user") -> None:
        """Stop polling for the pause length and give the switch's login back.

        Returns quickly. A running poll sees the pause before its next request, stops, and logs out
        itself before it releases the lock.
        """
        self._set_pause(reason)
        if self._lock.acquire(timeout=_LOCK_WAIT_S):
            try:
                self._logout()
            finally:
                self._lock.release()

    def resume(self) -> None:
        with self._pause_guard:
            self._paused_until_ms = None
            self._pause_reason = None
            self._last_relogin_ms = None

    def _expire_pause(self, now: int) -> None:
        """Clear a pause that has run out; never one that was set meanwhile."""
        with self._pause_guard:
            until = self._paused_until_ms
            if until is not None and now >= until:
                self._paused_until_ms = None
                self._pause_reason = None

    def _pause_active(self, now: int) -> bool:
        until = self._paused_until_ms
        return until is not None and now < until

    def settings_changed(self) -> None:
        """New settings: try the switch again at once; a new address or password also logs out."""
        key = self._connection_key()
        self._failures.clear()
        self._next_allowed.clear()
        self._errors.clear()
        if key != self._connection:
            self._connection = key
            self._generation += 1
            self._stopped = False
            self._reachable = None
            self._pending_reset = True  # a running poll stops before its next request
            if self._lock.acquire(timeout=_LOCK_WAIT_S):
                try:
                    self._apply_reset()
                finally:
                    self._lock.release()

    def shutdown(self) -> None:
        if self._lock.acquire(timeout=_SHUTDOWN_WAIT_S):
            try:
                self._drop_session()
            finally:
                self._lock.release()

    # ---- running polls -------------------------------------------------------------------------

    def poll_block_reason(self) -> str | None:
        """Why a poll would not run right now, or None."""
        if not self.settings.configured():
            return NOT_CONFIGURED
        if self._stopped:
            return LOGIN_FAILED_REASON
        if self._pause_active(self._ctx.clock.now_ms()):
            return PAUSED_REASON
        return None

    def _run(self, group: str, interval_s: int, step: Step, force: bool) -> bool:
        """One poll, with the lock already held. False when the switch did not answer."""
        try:
            self._apply_reset()
            return self._run_poll(group, interval_s, step, force)
        finally:
            self._settle()

    def _run_poll(self, group: str, interval_s: int, step: Step, force: bool) -> bool:
        if self.poll_block_reason() is not None:
            return True
        now = self._ctx.clock.now_ms()
        self._expire_pause(now)
        generation = self._generation
        if not force and now < self._next_allowed.get(group, 0):
            return True
        try:
            self._with_session(step, now)
        except (_Paused, _Interrupted):
            return True
        except AuthFailed:
            if generation == self._generation:  # not the refusal of a password that was just replaced
                self._answered()
                self._stop_after_refusal()
            return True
        except Unreachable as exc:
            self._failed(group, interval_s, exc, now)
            return False
        except UnsupportedSwitch as exc:
            self._answered()
            self._record_error(group, f"not a GS105E: {exc}")
            self._back_off(group, interval_s, now)
            return True
        except PageChanged as exc:
            self._answered()
            self._record_error(group, str(exc))
            return True
        except Exception as exc:  # a bug must not take the other groups down with it
            self._record_error(group, self._describe(exc))
            return True
        self._succeeded(group, now)
        return True

    def _locked(self, group: str, interval_s: int, step: Step) -> None:
        with self._lock:
            self._run(group, interval_s, step, force=False)

    def poll_counters(self) -> None:
        self._locked("counters", self.settings.counters_interval_s, self._counters)

    def poll_status(self) -> None:
        self._locked("status", self.settings.status_interval_s, self._status)

    def poll_config(self) -> None:
        self._locked("config", self.settings.config_interval_s, self._config)

    def _run_all(self) -> None:
        s = self.settings
        steps: list[tuple[str, int, Step]] = [
            ("status", s.status_interval_s, self._status),
            ("config", s.config_interval_s, self._config),
            ("counters", s.counters_interval_s, self._counters),
        ]
        for group, interval_s, step in steps:
            if not self._run(group, interval_s, step, force=True):
                break  # the switch is not answering: do not wait for two more timeouts

    def start_poll_all(self) -> bool:
        """Every group now, on a background thread, ignoring the backoff.

        False (decided now) when polling is blocked (see ``poll_block_reason``) or a poll is running.
        """
        if self.poll_block_reason() is not None or not self._lock.acquire(blocking=False):
            return False

        def work() -> None:
            try:
                self._run_all()
            except Exception:
                self._ctx.log.warning("GS105E poll failed", exc_info=False)
            finally:
                self._lock.release()

        try:
            threading.Thread(target=work, name="gs105e-poll-all", daemon=True).start()
        except BaseException:
            self._lock.release()
            raise
        return True

    def prune(self) -> None:
        """Roll up and delete old samples. Storage only, so it does not wait for (or block) a poll."""
        s = self.settings
        self._store.rollup_and_prune(
            self._ctx.clock.now_ms(), s.raw_retention_h * _HOUR_MS, s.rollup_retention_d * _DAY_MS
        )

    def test_connection(self) -> dict[str, str]:
        """Log in with the current settings and read the switch info. A good result clears a login stop."""
        if not self.settings.configured():
            return {"ok": "false", "error": NOT_CONFIGURED}
        with self._lock:
            self._apply_reset()
            self._drop_session()
            self._bypass = True
            try:
                session = self._ensure_session()
                info = parse_switch_info(session.get(SWITCH_INFO))
            except AuthFailed as exc:
                self._stopped = True
                return {"ok": "false", "error": self._scrub(str(exc))}
            except UnsupportedSwitch as exc:
                return {"ok": "false", "error": self._scrub(f"not a GS105E: {exc}")}
            except (Unreachable, SessionLost, PageChanged) as exc:
                return {"ok": "false", "error": self._describe(exc)}
            except Exception as exc:
                return {"ok": "false", "error": self._describe(exc)}
            finally:
                self._bypass = False
            self._stopped = False
            self._failures.clear()
            self._next_allowed.clear()
            self._answered()
            if self._pause_active(self._ctx.clock.now_ms()):
                self._logout()  # the user paused: do not keep the session the test opened
            return {"ok": "true", "product": info.product, "firmware": info.firmware, "name": info.name}

    # ---- outcomes ------------------------------------------------------------------------------

    def _record_error(self, group: str, message: str) -> None:
        text = self._scrub(message)
        self._errors[group] = text
        self._ctx.log.warning("GS105E %s poll failed: %s", group, text)

    def _back_off(self, group: str, interval_s: int, now: int) -> None:
        failures = min(self._failures.get(group, 0) + 1, 10)
        self._failures[group] = failures
        delay_s = min(MAX_BACKOFF_S, interval_s * 2**failures)
        self._next_allowed[group] = now + int(delay_s * 1000)

    def _failed(self, group: str, interval_s: int, exc: Unreachable, now: int) -> None:
        self._record_error(group, self._describe(exc))
        self._back_off(group, interval_s, now)
        if self._reachable is not False:
            self._reachable = False
            self._event(UNREACHABLE_TEXT)

    def _answered(self) -> None:
        """The switch answered. After an outage that lifts every group's backoff."""
        was = self._reachable
        self._reachable = True
        if was is False:
            self._failures.clear()
            self._next_allowed.clear()
            self._event(REACHABLE_TEXT)

    def _succeeded(self, group: str, now: int) -> None:
        self._errors.pop(group, None)
        self._failures.pop(group, None)
        self._next_allowed.pop(group, None)
        self._last_poll_ms = now
        self._answered()

    def _stop_after_refusal(self) -> None:
        if not self._stopped:
            self._stopped = True
            self._event(LOGIN_FAILED_TEXT)

    # ---- the poll groups -----------------------------------------------------------------------

    def _counters(self, session: SwitchSession, now: int) -> None:
        counters = read_counters(session, now)
        previous = self._last_counters
        rates: dict[int, PortRates] = {}
        if counters_reset(previous, counters):
            self._event(COUNTERS_RESET_TEXT)
        else:
            snapshot = self._current
            for cur in counters:
                before = previous.get(cur.port)
                status = snapshot.port(cur.port) if snapshot is not None else None
                rate = compute_rates(before, cur, status.link_mbps if status else None) if before else None
                if rate is not None:
                    rates[cur.port] = rate
        self._last_counters = {c.port: c for c in counters}
        self._rates = rates
        if not rates:
            return
        self._store.add_samples(list(rates.values()), self._last_counters)
        for change in crc_alerts(
            list(rates.values()), self.settings.crc_alert_threshold, self._crc_alerted, now
        ):
            self._event(change.text)

    def _status(self, session: SwitchSession, now: int) -> None:
        self._apply(read_status(session, now))

    def _config(self, session: SwitchSession, now: int) -> None:
        self._apply(read_config(session, now))

    def _apply(self, part: Snapshot) -> None:
        previous = self._current
        merged = merge_snapshot(previous, part)
        for change in diff(previous, merged, own_ip=self._own_ip()):
            self._event(change.text)
        self._store.save_snapshot(merged)
        self._current = merged
        self._claim_switch(merged)

    def _find_device(self, snapshot: Snapshot) -> DeviceView | None:
        devices = self._ctx.core.devices()
        host = self.settings.host
        device = next((d for d in devices if d.ip == host), None)
        if device is not None or snapshot.info is None or not snapshot.info.mac:
            return device
        mac = snapshot.info.mac.lower()
        return next((d for d in devices if d.mac and d.mac.lower() == mac), None)

    def _claim_switch(self, snapshot: Snapshot) -> None:
        info = snapshot.info
        if info is None:
            return
        device = self._find_device(snapshot)
        if device is None:
            return
        name = info.name or SOURCE
        hint = f"NETGEAR {info.product} firmware {info.firmware} serial {info.serial}"
        if self._claimed.get(device.key) == (name, hint):
            return
        items: list[NameClaim | TypeClaim | Hint] = [
            NameClaim(device.key, name, SOURCE, NAME_RANK, self._ctx.clock.now_ms()),
            TypeClaim(device.key, "switch", _SWITCH_TYPE_REASON, SOURCE),
            Hint(device.key, hint, SOURCE),
        ]
        self._ctx.core.claim(items)
        self._claimed[device.key] = (name, hint)

    # ---- read models ---------------------------------------------------------------------------

    def _login_state(self) -> str:
        if not self.settings.configured():
            return "not_configured"
        if self._stopped:
            return "failed"
        if self._pause_active(self._ctx.clock.now_ms()):
            return "paused"
        session = self._session
        return "ok" if session is not None and session.logged_in else "unknown"

    def summary(self) -> dict[str, Any]:
        snapshot = self._current
        info = snapshot.info if snapshot else None
        rates = list(self._rates.values())
        paused = self._pause_active(self._ctx.clock.now_ms())
        return {
            "configured": self.settings.configured(),
            "host": self.settings.host or None,
            "reachable": self._reachable,
            "polling": self._lock.locked(),  # a poll (a job or Poll now) holds the lock while it runs
            "login": self._login_state(),
            "paused_until_ms": self._paused_until_ms if paused else None,
            "pause_reason": self._pause_reason if paused else None,
            "last_poll_ms": self._last_poll_ms,
            "errors": dict(self._errors),
            "switch": None
            if info is None
            else {
                "name": info.name,
                "product": info.product,
                "firmware": info.firmware,
                "firmware_tested": info.firmware in TESTED_FIRMWARE,
                "serial": info.serial,
                "mac": info.mac,
                "bootloader": info.bootloader,
                "dhcp": info.dhcp,
                "ip": info.ip,
                "mask": info.mask,
                "gateway": info.gateway,
            },
            "ports": {
                "total": PORT_COUNT,
                "up": sum(1 for p in snapshot.ports if p.up) if snapshot else 0,
            },
            "throughput_bps": {
                "in": sum(r.in_bps for r in rates),
                "out": sum(r.out_bps for r in rates),
            },
        }

    def ports(self) -> list[dict[str, Any]]:
        snapshot = self._current
        if snapshot is None:
            return []
        pvids = dict(snapshot.vlans.pvids) if snapshot.vlans else {}
        shown = snapshot.vlans.shown if snapshot.vlans else None
        limits = {r.port: r for r in snapshot.qos.rate_limits} if snapshot.qos else {}
        mirror = snapshot.mirror if snapshot.mirror is not None and snapshot.mirror.enabled else None
        entries: list[dict[str, Any]] = []
        for p in snapshot.ports:
            rate = self._rates.get(p.port)
            counters = self._last_counters.get(p.port)
            limit = limits.get(p.port)
            code = shown.members[p.port - 1] if shown and 0 < p.port <= len(shown.members) else ""
            role: str | None = None
            if mirror is not None:
                if mirror.destination == p.port:
                    role = "destination"
                elif p.port in mirror.sources:
                    role = "source"
            entries.append(
                {
                    **asdict(p),
                    "in_bps": rate.in_bps if rate else None,
                    "out_bps": rate.out_bps if rate else None,
                    "util_percent": rate.util_percent if rate else None,
                    "crc_errors": counters.crc_errors if counters else None,
                    "crc_delta": rate.crc_delta if rate else None,
                    "pvid": pvids.get(p.port),
                    "vlan_member": code or None,  # in the VLAN shown on the config poll: "U" or "T"
                    "ingress_kbps": limit.ingress_kbps if limit else None,
                    "egress_kbps": limit.egress_kbps if limit else None,
                    "mirror": role,
                }
            )
        return entries

    def port(self, n: int) -> dict[str, Any] | None:
        return next((e for e in self.ports() if e["port"] == n), None)

    def samples(
        self, n: int, from_ms: int | None, to_ms: int | None, resolution: str = "raw"
    ) -> list[dict[str, Any]]:
        end = to_ms if to_ms is not None else self._ctx.clock.now_ms()
        start = from_ms if from_ms is not None else end - (_HOUR_MS if resolution == "raw" else _DAY_MS)
        rows = self._store.samples(n, start, end, cast("Resolution", resolution))
        return [asdict(r) for r in rows]

    def config(self) -> dict[str, Any]:
        snapshot = self._current
        result: dict[str, Any] = {}
        for name in _CONFIG_GROUPS:
            value = getattr(snapshot, name) if snapshot is not None else None
            result[name] = asdict(value) if value is not None else None
        return result
