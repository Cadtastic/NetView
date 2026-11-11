"""Capture the web pages of a NETGEAR GS105Ev2 so the netview plugin's parsers can be written and tested.

Usage:
    python -I capture.py --host 192.168.1.3                        # dry run: reads the login page only
    python -I capture.py --host 192.168.1.3 --out DIR --execute    # logs in, saves the pages, logs out
        [--session-check MINUTES] [--gap-ms 300] [--max-pages 120] [--keep-raw]

The password is read from the environment variable named by --password-env (default GS105E_PASSWORD), or
asked for at a prompt. It is never taken from the command line, printed or written anywhere.

What --execute does:
  1. Logs in the way the switch's login.js does: md5(merge(password, rand)), posted to /login.cgi.
  2. Fetches every .htm/.cgi page it can find linked from the pages and scripts it reads, by GET only and
     without query strings. Pages whose names suggest an action (reboot, reset, factory, upgrade, restore,
     logout, ...) are never requested.
  3. Checks session behaviour: whether a second login ends the first session, and, with --session-check,
     how long a session lasts: kept busy for MINUTES (a page every 30 s), then idle for 1 and 3 minutes.
  4. Logs out.

Outputs, under --out:
  pages/<name>       each page, scrubbed: serial number, MAC addresses and IPv4 addresses are replaced with
                     stable placeholders (masks such as 255.255.255.0 are kept)
  raw/<name>         unscrubbed pages, only with --keep-raw (never commit these)
  capture.json       schema "netview.gs105e/capture@1": model, firmware, pages (status, bytes, title, saved
                     name), session findings, and which placeholders replaced what kind of value

Script and stylesheet files are read only to find links and are never saved (they are NETGEAR's code).
Close any browser tab logged in to the switch first: the session checks may log it out.
Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import gzip
import hashlib
import http.client
import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCHEMA = "netview.gs105e/capture@1"
TIMEOUT_S = 8.0
MAX_BODY = 2 << 20
START = [
    "/",
    "/index.htm",
    "/index.cgi",
    "/switch_info.htm",
    "/switch_info.cgi",
    "/status.htm",
    "/status.cgi",
    "/portStatistics.cgi",
    "/port_statistics.htm",
    "/menu.htm",
    "/top.htm",
    "/left.htm",
]
UNSAFE = re.compile(
    r"reboot|reset|factory|default|upgrade|firmware|restore|logout|login|save|apply|delete|"
    r"del_|clear|erase|backup|download|upload|tftp",
    re.I,
)
# a .cgi is where a form posts; one named like these might act even on a plain GET, so it is never requested
CGI_UNSAFE = re.compile(r"test|run|start|set_|_set|cfg|config|add|remove|enable|disable|cycle", re.I)
LINK = re.compile(r"""["'(=\s/]((?:[A-Za-z0-9_\-]+/)*[A-Za-z0-9_\-]+\.(?:htm|html|cgi|js))\b""")
MAC = re.compile(r"\b[0-9A-Fa-f]{2}(?:[:\-][0-9A-Fa-f]{2}){5}\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
LOGIN_MARKERS = ("RedirectToLoginPage", "id='rand'", 'id="rand"')


def merge(a: str, b: str) -> str:
    """Characters of a and b alternately, then the rest of the longer one (the switch's login.js merge)."""
    out = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return "".join(out)


def login_hash(password: str, rand: str) -> str:
    return hashlib.md5(merge(password, rand).encode("utf-8")).hexdigest()


class Switch:
    def __init__(self, host: str, gap_s: float, port: int = 80) -> None:
        self.port = port
        self.host = host
        self.gap_s = gap_s
        self.cookie: str | None = None
        self._last = 0.0

    def request(
        self, method: str, path: str, body: bytes | None = None, cookie: str | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        wait = self._last + self.gap_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        headers = {"Accept-Encoding": "gzip", "Connection": "close"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        use = cookie if cookie is not None else self.cookie
        if use:
            headers["Cookie"] = use
        conn = http.client.HTTPConnection(self.host, self.port, timeout=TIMEOUT_S)
        hdrs: dict[str, str] = {}
        try:
            conn.request(method, path, body, headers)
            resp = conn.getresponse()
            data = resp.read(MAX_BODY)
            for k, v in resp.getheaders():
                k = k.lower()
                hdrs[k] = hdrs[k] + "\n" + v if k in hdrs else v
            status = resp.status
        except http.client.BadStatusLine:
            # some pages come back as bare (often gzipped) bytes with no status line or headers; read it raw
            status, data = 0, self._raw(method, path, body, headers)
            hdrs = {"x-capture": "no HTTP headers"}
        finally:
            conn.close()
            self._last = time.monotonic()
        if hdrs.get("content-encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
            with contextlib.suppress(OSError):
                data = gzip.decompress(data)
        return status, hdrs, data

    def _raw(self, method: str, path: str, body: bytes | None, headers: dict[str, str]) -> bytes:
        lines = [f"{method} {path} HTTP/1.1", f"Host: {self.host}"] + [
            f"{k}: {v}" for k, v in headers.items()
        ]
        if body is not None:
            lines.append(f"Content-Length: {len(body)}")
        payload = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + (body or b"")
        with socket.create_connection((self.host, self.port), TIMEOUT_S) as s:
            s.sendall(payload)
            chunks = []
            total = 0
            while total < MAX_BODY:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        data = b"".join(chunks)
        if data.startswith(b"HTTP/"):
            data = data.partition(b"\r\n\r\n")[2]
        return data

    def login_page(self) -> tuple[str, str, str]:
        _, _, data = self.request("GET", "/login.cgi", cookie="")
        text = data.decode("utf-8", "replace")
        rand = re.search(r"id=['\"]rand['\"]\s+value=['\"](\d+)['\"]", text)
        title = re.search(r"<title>([^<]*)</title>", text, re.I)
        fw = re.search(r"\?a(\d+(?:\.\d+)+)", text)
        return (
            (rand.group(1) if rand else ""),
            (title.group(1).strip() if title else ""),
            (fw.group(1) if fw else ""),
        )

    def login(self, password: str, diag_dir: Path | None = None) -> str:
        rand, _, _ = self.login_page()
        if not rand:
            raise SystemExit("login page has no rand value: not a GS105Ev2-style login")
        body = ("password=" + login_hash(password, rand)).encode("ascii")
        status, hdrs, data = self.request("POST", "/login.cgi", body, cookie="")
        cookie = None
        for line in hdrs.get("set-cookie", "").split("\n"):
            m = re.match(r"\s*((?:GS108)?SID)=([^;]+)", line)
            if m:
                cookie = f"{m.group(1)}={m.group(2)}"
        if cookie is None:
            text = data.decode("utf-8", "replace")
            err = None
            for tag in re.findall(r"<input[^>]*err_msg[^>]*>", text, re.I):
                v = re.search(r"value=['\"]([^'\"]*)['\"]", tag)
                if v and v.group(1):
                    err = v.group(1)
            title = re.search(r"<title>([^<]*)</title>", text, re.I)
            cookies = [
                c.split("=", 1)[0].strip() + "=<hidden>" for c in hdrs.get("set-cookie", "").split("\n") if c
            ]
            print(
                f"  login reply: HTTP {status}, title {title.group(1).strip() if title else None!r}, "
                f"cookies {cookies or 'none'}, error {err!r}",
                flush=True,
            )
            if diag_dir is not None:
                diag_dir.mkdir(parents=True, exist_ok=True)
                lines = [f"HTTP {status}"]
                for k, hv in sorted(hdrs.items()):
                    lines.append(f"{k}: {'<hidden>' if k == 'set-cookie' else hv}")
                scrubbed = Scrubber().scrub(text)
                (diag_dir / "login-failure.txt").write_text(
                    "\n".join(lines) + "\n\n" + scrubbed, encoding="utf-8"
                )
                print(f"  saved the reply to {diag_dir / 'login-failure.txt'}", flush=True)
            raise SystemExit("login failed" + (f": switch says '{err}'" if err else " (no session cookie)"))
        return cookie

    def logged_in(self, cookie: str) -> bool:
        status, _, data = self.request("GET", "/switch_info.cgi", cookie=cookie)
        text = data.decode("utf-8", "replace")
        return status == 200 and not any(m in text for m in LOGIN_MARKERS)


class Scrubber:
    def __init__(self) -> None:
        self.macs: dict[str, str] = {}
        self.ips: dict[str, str] = {}
        self.serials: dict[str, str] = {}

    def learn_serial(self, text: str) -> None:
        m = re.search(r"Serial\s*Number.*?(?:value=['\"]|<td[^>]*>\s*)([A-Za-z0-9]{8,20})", text, re.I | re.S)
        if m and m.group(1) not in self.serials:
            self.serials[m.group(1)] = (
                "SERIAL" + "0" * (len(m.group(1)) - 6) if len(m.group(1)) > 6 else "SERIAL"
            )

    def learn_token(self, text: str) -> None:
        """The form token (<input name="hash">) that every write needs; replaced with a fixed dummy value."""
        m = re.search(r"name=['\"]?hash['\"]?[^>]*value=['\"](\d+)['\"]", text, re.I)
        if m and m.group(1) not in self.serials:
            self.serials[m.group(1)] = "12345"

    def _mac(self, m: re.Match[str]) -> str:
        key = re.sub(r"[:\-]", "", m.group(0)).lower()
        if key not in self.macs:
            self.macs[key] = "02:00:00:00:00:%02X" % (len(self.macs) + 1)
        sep = m.group(0)[2]
        return self.macs[key].replace(":", sep)

    def _ip(self, m: re.Match[str]) -> str:
        ip = m.group(0)
        a, b = (int(x) for x in ip.split(".")[:2])
        private = (
            a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 169 and b == 254)
        )
        if not private:  # masks, multicast ranges, version numbers such as 1.6.0.11: not identifying
            return ip
        if ip not in self.ips:
            self.ips[ip] = f"192.0.2.{len(self.ips) + 1}"
        return self.ips[ip]

    def scrub(self, text: str) -> str:
        for serial, repl in self.serials.items():
            text = text.replace(serial, repl)
        text = MAC.sub(self._mac, text)
        return IPV4.sub(self._ip, text)


def safe_name(path: str) -> str:
    name = path.strip("/") or "root"
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", name)


def crawl(sw: Switch, max_pages: int) -> tuple[dict[str, bytes], list[dict[str, Any]], bool]:
    queue = list(START)
    seen = set()
    pages: dict[str, bytes] = {}
    log: list[dict[str, Any]] = []
    expired = False
    while queue and len(pages) < max_pages:
        path = queue.pop(0)
        if not path.startswith("/"):
            path = "/" + path
        if path in seen:
            continue
        seen.add(path)
        base = path.rsplit("/", 1)[-1]
        if UNSAFE.search(base) or (base.endswith(".cgi") and CGI_UNSAFE.search(base)):
            log.append({"path": path, "skipped": "looks like an action"})
            continue
        try:
            status, hdrs, data = sw.request("GET", path)
        except (OSError, http.client.HTTPException) as exc:
            log.append({"path": path, "error": type(exc).__name__})
            continue
        if "x-capture" in hdrs:
            print(f"  {path}: {hdrs['x-capture']}", flush=True)
        text = data.decode("utf-8", "replace")
        is_script = path.endswith((".js", ".css"))
        for link in LINK.findall(text):
            target = "/" + link.lstrip("/")
            if target not in seen:
                queue.append(target)
        if is_script:
            log.append(
                {"path": path, "status": status, "bytes": len(data), "saved": None, "note": "read for links"}
            )
            continue
        if any(m in text for m in LOGIN_MARKERS) and path not in ("/",):
            expired = expired or status == 200
            log.append(
                {
                    "path": path,
                    "status": status,
                    "bytes": len(data),
                    "saved": None,
                    "note": "answered with the login page",
                }
            )
            continue
        title = re.search(r"<title>([^<]*)</title>", text, re.I)
        pages[path] = data
        log.append(
            {
                "path": path,
                "status": status,
                "bytes": len(data),
                "saved": safe_name(path),
                "title": title.group(1).strip() if title else None,
                "content_type": hdrs.get("content-type"),
                "note": hdrs.get("x-capture"),
            }
        )
    return pages, sorted(log, key=lambda e: e["path"]), expired


def session_check(sw: Switch, cookie: str, minutes: float) -> dict[str, Any]:
    """Keep the session busy (a page every 30 s, like netview's polling) for `minutes`, then leave it idle for
    1 and then 3 minutes. Records when, if ever, the switch drops it."""
    start = time.monotonic()
    while time.monotonic() - start < minutes * 60:
        time.sleep(30)
        if not sw.logged_in(cookie):
            return {"busy_session_dropped_after_min": round((time.monotonic() - start) / 60, 1)}
    found: dict[str, Any] = {"busy_session_alive_after_min": minutes}
    for gap in (1, 3):
        print(f"  idle gap of {gap} min ...", flush=True)
        time.sleep(gap * 60)
        alive = sw.logged_in(cookie)
        found[f"alive_after_{gap}_min_idle"] = alive
        if not alive:
            break
    return found


def write_pages(
    out: Path, pages: dict[str, bytes], keep_raw: bool, counts: bool = False
) -> dict[str, int] | int:
    """Scrub and save each page under out/pages (and the bytes as-is under out/raw with keep_raw)."""
    scrub = Scrubber()
    for path, data in pages.items():
        if "switch_info" in path:
            scrub.learn_serial(data.decode("utf-8", "replace"))
        scrub.learn_token(data.decode("utf-8", "replace"))
    (out / "pages").mkdir(parents=True, exist_ok=True)
    for path, data in sorted(pages.items()):
        text = data.decode("utf-8", "replace")
        (out / "pages" / safe_name(path)).write_text(scrub.scrub(text), encoding="utf-8")
        if keep_raw:
            (out / "raw").mkdir(exist_ok=True)
            (out / "raw" / safe_name(path)).write_bytes(data)
    if counts:
        return {"serials": len(scrub.serials), "macs": len(scrub.macs), "ipv4": len(scrub.ips)}
    return len(pages)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True, help="switch address, e.g. 192.168.1.3")
    ap.add_argument("--out", help="output folder (required with --execute)")
    ap.add_argument("--execute", action="store_true", help="log in and capture; without it, a dry run")
    ap.add_argument(
        "--password-env", default="GS105E_PASSWORD", help="environment variable holding the password"
    )
    ap.add_argument("--gap-ms", type=int, default=300, help="pause between requests (default 300)")
    ap.add_argument(
        "--max-pages", type=int, default=120, help="stop after this many saved pages (default 120)"
    )
    ap.add_argument(
        "--session-check", type=float, default=0, help="keep a session busy for MINUTES, then test idle gaps"
    )
    ap.add_argument("--keep-raw", action="store_true", help="also save unscrubbed pages under raw/")
    ap.add_argument(
        "--rescrub",
        action="store_true",
        help="no network: rebuild pages/ from raw/ under --out with the current scrub rules",
    )
    ap.add_argument(
        "--sessions-only",
        action="store_true",
        help="skip reading pages; only run the session checks and write session.json",
    )
    args = ap.parse_args(argv)

    if args.rescrub:
        if not args.out:
            ap.error("--rescrub needs --out")
        raw = {"/" + f.name: f.read_bytes() for f in sorted((Path(args.out) / "raw").iterdir())}
        n = write_pages(Path(args.out), raw, keep_raw=False)
        print(f"rescrubbed {n} pages from {Path(args.out) / 'raw'}")
        return 0
    sw = Switch(args.host, args.gap_ms / 1000.0)
    rand, title, fw = sw.login_page()
    print(f"switch: {title or '?'}, firmware {fw or '?'}, login challenge {'present' if rand else 'MISSING'}")
    if not args.execute:
        print(
            "dry run: would log in, read every linked page by GET, check sessions, log out. "
            "Add --execute --out DIR."
        )
        return 0
    if not args.out:
        ap.error("--out is required with --execute")
    out = Path(args.out)
    password = os.environ.get(args.password_env) or getpass.getpass("GS105E admin password (not shown): ")
    if not password:
        raise SystemExit("no password given")

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 - keeps Python 3.9 support
        "model_title": title,
        "firmware": fw,
        "session": {},
    }
    print("logging in ...", flush=True)
    sw.cookie = sw.login(password, out)
    cookies = [sw.cookie]
    pages: dict[str, bytes] = {}
    try:
        report["session"]["cookie_name"] = sw.cookie.split("=", 1)[0]
        print("reading pages ...", flush=True)
        pages, log, expired = ({}, [], False) if args.sessions_only else crawl(sw, args.max_pages)
        report["pages"] = log
        report["session"]["login_page_during_crawl"] = expired
        print(f"  read {len(pages)} pages", flush=True)

        print("checking whether a second login ends the first session ...", flush=True)
        first = sw.cookie
        second = sw.login(password, out)
        cookies.append(second)
        report["session"]["first_alive_after_second_login"] = sw.logged_in(first)
        report["session"]["second_alive"] = sw.logged_in(second)
        sw.cookie = second
        if args.session_check > 0:
            print(
                f"checking session lifetime ({args.session_check:g} min busy, then 4 min idle; "
                "leave it running) ...",
                flush=True,
            )
            report["session"].update(session_check(sw, second, args.session_check))
    finally:
        password = ""
        for cookie in reversed(cookies):  # always log out, even after an error, so no session is left open
            with contextlib.suppress(OSError, http.client.HTTPException):
                sw.request("GET", "/logout.cgi", cookie=cookie)
        print("logged out", flush=True)

    if args.sessions_only:
        out.mkdir(parents=True, exist_ok=True)
        (out / "session.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"session findings: {report['session']}; saved {out / 'session.json'}")
        return 0
    report["scrubbed"] = write_pages(out, pages, args.keep_raw, counts=True)
    report["firmware"] = fw
    (out / "capture.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"saved {len(pages)} pages to {out / 'pages'}; report {out / 'capture.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
