"""The Roku service: live status, identity checks, commands, scans and saving the TV list."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast

from netview.sdk import PluginContext

from .discovery import ScanResult, scan
from .document import (
    DocumentError,
    MergeIps,
    Replace,
    parse_document,
    to_document,
    validate_replace,
)
from .ecp import ActiveApp, App, DeviceInfo, EcpClient, EcpError
from .keys import app_path, key_path, text_paths
from .merge import merge
from .model import SavedTv, ScanHit
from .settings import RokuSettings
from .storage import TvStore

MSG_WRONG_DEVICE = "A different Roku, {name}, now answers at this address. Run a scan in Settings."
_MAX_PARALLEL = 8
_APPS_MAX_AGE_MS = 3600 * 1000
_REFRESH_DELAY_S = 1.0

Timer = Callable[[float, Callable[[], None]], None]

__all__ = ["CommandError", "DocumentError", "RokuService", "UnknownTv"]


class UnknownTv(Exception):
    def __init__(self, tv_id: str) -> None:
        super().__init__(tv_id)
        self.tv_id = tv_id


class CommandError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class _Live:
    reachable: bool = False
    power: str = "unknown"
    mode: str = ""
    active_app: ActiveApp | None = None
    apps: list[App] | None = None
    apps_read_ms: int | None = None
    apps_refused: bool = False
    wrong_device: str | None = None
    checked_at_ms: int | None = None
    confirmed_ms: int | None = None
    confirmed_ip: str = ""
    confirmed_serial: str = ""
    error: str = ""

    def view(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "power": self.power,
            "mode": self.mode,
            "active_app": (
                {"id": self.active_app.id, "name": self.active_app.name} if self.active_app else None
            ),
            "apps": [asdict(a) for a in self.apps] if self.apps is not None else None,
            "apps_refused": self.apps_refused,
            "wrong_device": self.wrong_device,
            "checked_at_ms": self.checked_at_ms,
            "error": self.error,
        }


@dataclass
class _ScanState:
    running: bool = False
    started_ms: int | None = None
    finished_ms: int | None = None
    found: int = 0
    by_ssdp: int = 0
    by_sweep: int = 0
    duration_s: float = 0.0
    error: str = ""


def _start_timer(delay_s: float, fn: Callable[[], None]) -> None:
    timer = threading.Timer(delay_s, fn)
    timer.daemon = True
    timer.start()


class RokuService:
    def __init__(
        self,
        ctx: PluginContext,
        store: TvStore,
        ecp: EcpClient,
        scanner: Callable[..., ScanResult] = scan,
        *,
        timer: Timer = _start_timer,
    ) -> None:
        self._ctx = ctx
        self._store = store
        self._ecp = ecp
        self._scanner = scanner
        self._timer = timer
        self._settings = ctx.settings if isinstance(ctx.settings, RokuSettings) else RokuSettings()
        self._lock = threading.RLock()
        self._store_lock = threading.RLock()
        self._live: dict[str, _Live] = {}
        self._scan = _ScanState()

    # ---- helpers -------------------------------------------------------

    def _now_ms(self) -> int:
        return self._ctx.clock.now_ms()

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self._now_ms() / 1000, tz=UTC).isoformat(timespec="seconds")

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:12]

    def _find(self, tv_id: str) -> SavedTv:
        for tv in self._store.load():
            if tv.id == tv_id:
                return tv
        raise UnknownTv(tv_id)

    def _apply(self, tv_id: str, updates: dict[str, Any]) -> None:
        """Publish new status values in one step, so readers never see a half-updated status."""
        with self._lock:
            live = self._live.setdefault(tv_id, _Live())
            for name, value in updates.items():
                setattr(live, name, value)

    def _snapshot(self, tv_id: str) -> _Live:
        with self._lock:
            return replace(self._live.setdefault(tv_id, _Live()))

    def settings_changed(self, settings: RokuSettings) -> None:
        self._settings = settings
        self._ecp.timeout_s = settings.request_timeout_s

    # ---- listing -------------------------------------------------------

    def list_tvs(self) -> dict[str, Any]:
        tvs = []
        for tv in self._store.load():
            with self._lock:
                status = self._live.get(tv.id, _Live()).view()
            tvs.append(asdict(tv) | {"title": tv.title, "status": status})
        return {"tvs": tvs, "scan": self.scan_state()}

    # ---- identity ------------------------------------------------------

    def _check_identity(self, tv: SavedTv, info: DeviceInfo) -> tuple[bool, dict[str, Any]]:
        """Who answers: True when it is the saved TV, plus the status values to publish about it."""
        if tv.serial and info.serial and tv.serial != info.serial:
            name = info.name or tv.ip
            return False, {
                "wrong_device": name,
                "reachable": False,
                "confirmed_ms": None,
                "error": MSG_WRONG_DEVICE.format(name=name),
            }
        serial = tv.serial
        if not tv.serial and info.serial:
            with self._store_lock:
                # Re-read: the saved entry may have changed since this poll took its snapshot.
                saved = self._store.load()
                current = next((t for t in saved if t.id == tv.id), None)
                if (
                    current is not None
                    and current.ip == tv.ip
                    and not current.serial
                    and all(t.serial != info.serial for t in saved)
                ):
                    self._store.replace(
                        [replace(t, serial=info.serial) if t.id == tv.id else t for t in saved]
                    )
                    serial = info.serial
        # The confirmation covers exactly this address and serial; a saved change to either voids it.
        return True, {
            "wrong_device": None,
            "confirmed_ip": tv.ip,
            "confirmed_serial": serial,
            "confirmed_ms": self._now_ms(),
        }

    # ---- polling -------------------------------------------------------

    def _poll_one(self, tv: SavedTv, force_apps: bool = False) -> None:
        prior = self._snapshot(tv.id)
        now = self._now_ms()
        try:
            info = self._ecp.device_info(tv.ip)
        except EcpError as err:
            self._apply(
                tv.id,
                {"reachable": False, "power": "unknown", "error": err.message, "checked_at_ms": now},
            )
            return
        ok, update = self._check_identity(tv, info)
        update["checked_at_ms"] = now
        if not ok:
            update["power"] = "unknown"
            self._apply(tv.id, update)
            return
        update.update(reachable=True, error="", power=info.power, mode=info.mode)
        active: ActiveApp | None = None
        if info.power == "on":
            try:
                active = self._ecp.active_app(tv.ip)
            except EcpError:
                active = None
        update["active_app"] = active
        refused = False if force_apps else prior.apps_refused
        update["apps_refused"] = refused
        stale = force_apps or prior.apps_read_ms is None or now - prior.apps_read_ms > _APPS_MAX_AGE_MS
        if stale and not refused:
            try:
                update["apps"] = self._ecp.apps(tv.ip)
                update["apps_read_ms"] = now
            except EcpError as err:
                if err.status == 403:
                    update["apps_refused"] = True
        self._apply(tv.id, update)

    def _safe_poll(self, tv: SavedTv) -> None:
        try:
            self._poll_one(tv)
        except Exception:
            self._ctx.log.exception("Roku status read failed for %s", tv.ip)

    def poll_status(self) -> None:
        tvs = self._store.load()
        with self._lock:
            for gone in set(self._live) - {t.id for t in tvs}:
                del self._live[gone]
        if not tvs:
            return
        with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(tvs))) as pool:
            list(pool.map(self._safe_poll, tvs))

    def refresh(self, tv_id: str) -> None:
        """On demand (the Control view opened): re-read the status and the app list."""
        self._poll_one(self._find(tv_id), force_apps=True)

    def _refresh_later(self, tv_id: str) -> None:
        """After a command only the status is re-read; the apps keep their own schedule."""

        def run() -> None:
            try:
                self._poll_one(self._find(tv_id))
            except Exception:
                self._ctx.log.debug("Roku follow-up status read failed", exc_info=True)

        self._timer(_REFRESH_DELAY_S, run)

    # ---- commands ------------------------------------------------------

    def _confirmed(self, tv: SavedTv) -> None:
        """Return only when the TV at this address is the saved one; raise CommandError otherwise."""
        live = self._snapshot(tv.id)
        window_ms = 2 * self._settings.status_interval_s * 1000
        if (
            live.confirmed_ms is not None
            and live.confirmed_ip == tv.ip
            and live.confirmed_serial == tv.serial
            and self._now_ms() - live.confirmed_ms <= window_ms
        ):
            return
        try:
            info = self._ecp.device_info(tv.ip)
        except EcpError as err:
            raise CommandError(502, err.message) from err
        ok, update = self._check_identity(tv, info)
        self._apply(tv.id, update)
        if not ok:
            raise CommandError(409, MSG_WRONG_DEVICE.format(name=update["wrong_device"]))

    def _post_all(self, tv_id: str, paths: list[str]) -> None:
        tv = self._find(tv_id)
        self._confirmed(tv)
        try:
            for path in paths:
                self._ecp.post(tv.ip, path)
        except EcpError as err:
            raise CommandError(502, err.message) from err
        self._refresh_later(tv_id)

    def send_key(self, tv_id: str, key: str, action: str = "press") -> None:
        self._find(tv_id)
        path = key_path(key, cast("Literal['press', 'down', 'up']", action))
        self._post_all(tv_id, [path])

    def launch(self, tv_id: str, app: str) -> None:
        self._find(tv_id)
        self._post_all(tv_id, [app_path(app)])

    def type_text(self, tv_id: str, text: str) -> None:
        self._find(tv_id)
        self._post_all(tv_id, text_paths(text))

    def icon(self, tv_id: str, app_id: str) -> tuple[bytes, str]:
        tv = self._find(tv_id)
        app_path(app_id)  # same allow-list as launching
        self._confirmed(tv)
        try:
            return self._ecp.icon(tv.ip, app_id)
        except EcpError as err:
            raise CommandError(502, err.message) from err

    # ---- saved list ----------------------------------------------------

    def document(self) -> dict[str, Any]:
        return to_document(self._store.load())

    def _probe_ips(self, ips: list[str]) -> tuple[list[ScanHit], list[str]]:
        def one(ip: str) -> ScanHit | None:
            try:
                info = self._ecp.device_info(ip)
            except EcpError:
                return None
            return ScanHit(ip, info.serial, info.name, info.model, info.location, info.tv, "manual")

        with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(ips))) as pool:
            results = list(pool.map(one, ips))
        hits = [r for r in results if r is not None]
        skipped = [ip for ip, r in zip(ips, results, strict=True) if r is None]
        return hits, skipped

    def save_document(self, text: str) -> dict[str, Any]:
        parsed = parse_document(text)
        now_iso = self._now_iso()
        if isinstance(parsed, Replace):
            tvs = validate_replace(parsed.tvs, self._new_id, now_iso)
            with self._store_lock:
                self._store.replace(tvs)
            return {"message": f"Saved: {len(tvs)} {'TV' if len(tvs) == 1 else 'TVs'}"}
        skipped: list[str] = []
        if isinstance(parsed, MergeIps):
            hits, skipped = self._probe_ips(list(dict.fromkeys(parsed.ips)))
        else:
            hits = parsed.hits
        with self._store_lock:
            result = merge(self._store.load(), hits, now_iso, self._new_id)
            self._store.replace(result.tvs)
        message = f"Merged: {result.added} added, {result.updated} updated"
        if skipped:
            message += f". Skipped (no Roku answered): {', '.join(skipped)}"
        return {"message": message, "skipped": skipped}

    # ---- scanning ------------------------------------------------------

    def scan_state(self) -> dict[str, Any]:
        with self._lock:
            s = self._scan
            return {
                "running": s.running,
                "started_ms": s.started_ms,
                "finished_ms": s.finished_ms,
                "found": s.found,
                "by_ssdp": s.by_ssdp,
                "by_sweep": s.by_sweep,
                "duration_s": s.duration_s,
                "error": s.error,
            }

    def _begin_scan(self) -> bool:
        with self._lock:
            if self._scan.running:
                return False
            self._scan = _ScanState(running=True, started_ms=self._now_ms())
            return True

    def _scan_body(self) -> None:
        error = ""
        result: ScanResult | None = None
        try:
            subnet = self._ctx.core.host().subnet
            result = self._scanner(self._ctx.probes, self._ecp, subnet, self._settings.scan_timeout_s)
            with self._store_lock:
                merged = merge(self._store.load(), result.hits, self._now_iso(), self._new_id)
                self._store.replace(merged.tvs)
        except Exception as err:
            self._ctx.log.exception("Roku scan failed")
            error = str(err) or type(err).__name__
        with self._lock:
            s = self._scan
            s.finished_ms = self._now_ms()
            s.error = error
            if result is not None and not error:
                s.found = len(result.hits)
                s.by_ssdp = result.by_ssdp
                s.by_sweep = result.by_sweep
                s.duration_s = result.duration_s
            s.running = False

    def start_scan(self) -> bool:
        if not self._begin_scan():
            return False
        threading.Thread(target=self._scan_body, name="roku-scan", daemon=True).start()
        return True

    def run_scan(self) -> None:
        if self._begin_scan():
            self._scan_body()
