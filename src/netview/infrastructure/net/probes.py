"""SystemServiceProbes: the read-only questions identity and inspection plugins ask a device.

Ported from LM (mDNS 593-666, NetBIOS 691-715, SSDP/UPnP 718-791, reverse DNS 873-885,
HTTP/TLS 466-558, banner 563-569). Everything a device answers is untrusted text: it is capped,
decoded leniently and never interpreted. Network I/O goes through a small ``SocketApi`` seam so
tests drive the probes with fake sockets and never touch the network.
"""

import contextlib
import hashlib
import html
import os
import random
import re
import socket
import ssl
import struct
import tempfile
import threading
import time
import warnings
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from netview.application.ports.probes import (
    CertInfo,
    DnsRecord,
    HttpProbe,
    NetbiosInfo,
    NetbiosName,
    SsdpEntry,
)
from netview.infrastructure.net import common, dnswire

HTTP_READ_LIMIT = 64 * 1024
UPNP_FIELDS = (
    "friendlyName",
    "manufacturer",
    "modelName",
    "modelNumber",
    "modelDescription",
    "deviceType",
    "presentationURL",
    "serialNumber",
)
_SSDP_GROUP = ("239.255.255.250", 1900)
_CONTROL_CHARS = re.compile(r"[\x00-\x20\x7f]")


class SocketApi(Protocol):
    """The three ways the probes open a socket. Tests replace this with fakes."""

    def udp(self) -> Any: ...
    def connect(self, ip: str, port: int, timeout_s: float) -> Any: ...
    def wrap_tls(self, raw: Any) -> Any: ...


def _tls_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with warnings.catch_warnings():  # old management controllers still speak TLS 1.0
        warnings.simplefilter("ignore", DeprecationWarning)
        with contextlib.suppress(ValueError, AttributeError):
            ctx.minimum_version = ssl.TLSVersion.TLSv1
    with contextlib.suppress(ssl.SSLError):
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    return ctx


class RealSockets:
    def udp(self) -> socket.socket:
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def connect(self, ip: str, port: int, timeout_s: float) -> socket.socket:
        return socket.create_connection((ip, port), timeout=timeout_s)

    def wrap_tls(self, raw: Any) -> Any:
        return _tls_context().wrap_socket(raw, server_hostname=None)


def decode_cert(der: bytes) -> CertInfo:
    """Certificate fields via CPython's private decoder; the hash alone when that is unavailable."""
    sha = hashlib.sha256(der).hexdigest()
    fd, path = tempfile.mkstemp(suffix=".pem")
    try:
        try:
            os.write(fd, ssl.DER_cert_to_PEM_cert(der).encode("ascii"))
        finally:
            os.close(fd)
        decoded = ssl._ssl._test_decode_cert(path)  # type: ignore[attr-defined]
    except Exception:
        return CertInfo(sha256=sha)
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)
    subject = dict(x[0] for x in decoded.get("subject", ()) if x)
    issuer = dict(x[0] for x in decoded.get("issuer", ()) if x)
    return CertInfo(
        sha256=sha,
        subject=subject.get("commonName", ""),
        subject_org=subject.get("organizationName", ""),
        issuer=issuer.get("commonName", ""),
        issuer_org=issuer.get("organizationName", ""),
        not_after=decoded.get("notAfter", ""),
        self_signed=subject == issuer,
        san=tuple(v for _, v in decoded.get("subjectAltName", ()))[:12],
    )


def xml_fields(text: str) -> dict[str, str]:
    """The handful of UPnP description fields we show. DTDs and entities are refused outright."""
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        return {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""
        if tag in UPNP_FIELDS and el.text and tag not in out:
            out[tag] = el.text.strip()[:120]
    return out


def _valid_port(port: object) -> bool:
    return isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535


class SystemServiceProbes:
    """Implements ServiceProbes. Never raises: failures give the empty result."""

    def __init__(
        self,
        sockets: SocketApi | None = None,
        local_ip: Callable[[], str] = common.local_ip,
        resolver: Callable[[str], tuple[str, list[str], list[str]]] = socket.gethostbyaddr,
    ) -> None:
        self._sockets: SocketApi = sockets or RealSockets()
        self._local_ip = local_ip
        self._resolver = resolver

    # ----------------------------------------------------------------- reverse DNS
    def reverse_dns(self, ip: str, timeout_s: float = 2.0) -> str:
        if not common.valid_ipv4(ip):
            return ""
        box: list[str] = []

        def look() -> None:
            with contextlib.suppress(OSError, IndexError):
                box.append(self._resolver(ip)[0])

        worker = threading.Thread(target=look, daemon=True, name="netview-rdns")
        worker.start()
        worker.join(timeout_s)
        return box[0][:253] if box else ""

    # ----------------------------------------------------------------- mDNS
    def mdns_query(self, ip: str, qname: str, qtype: int = 12, timeout_s: float = 1.2) -> list[DnsRecord]:
        """Unicast an mDNS question to the host's port 5353 and collect its records."""
        if not common.valid_ipv4(ip) or not isinstance(qtype, int) or not 0 < qtype < 0x10000:
            return []
        try:
            packet = dnswire.build_query(random.randint(0, 0xFFFF), qname, qtype, True)
        except (ValueError, UnicodeEncodeError):
            return []
        records: list[DnsRecord] = []
        sock = self._sockets.udp()
        try:
            sock.settimeout(0.3)
            sock.sendto(packet, (ip, 5353))
            end = time.monotonic() + timeout_s
            while time.monotonic() < end:
                try:
                    data, addr = sock.recvfrom(9000)
                except TimeoutError:
                    continue
                if addr[0] == ip and len(data) > 12:
                    with contextlib.suppress(ValueError):
                        records += dnswire.parse_records(data)
        except OSError:
            pass
        finally:
            sock.close()
        return records

    # ----------------------------------------------------------------- NetBIOS
    def netbios(self, ip: str, timeout_s: float = 1.5) -> NetbiosInfo | None:
        if not common.valid_ipv4(ip):
            return None
        tid = random.randint(0, 0xFFFF)
        packet = (
            struct.pack(">HHHHHH", tid, 0, 1, 0, 0, 0)
            + b"\x20CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\x00"
            + struct.pack(">HH", 0x21, 1)
        )
        sock = self._sockets.udp()
        try:
            sock.settimeout(timeout_s)
            sock.sendto(packet, (ip, 137))
            data, addr = sock.recvfrom(2048)
            if addr[0] != ip:
                return None
            return _parse_node_status(data)
        except (OSError, IndexError, struct.error):
            return None
        finally:
            sock.close()

    # ----------------------------------------------------------------- SSDP and UPnP
    def ssdp_search(self, target: str | None = None, timeout_s: float = 2.5) -> list[SsdpEntry]:
        """M-SEARCH, unicast to ``target`` (when given) and multicast; only ``target`` answers count."""
        if target is not None and not common.valid_ipv4(target):
            return []
        message = (
            b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
            b"MX: 2\r\nST: ssdp:all\r\n\r\n"
        )
        found: dict[tuple[str, str], dict[str, Any]] = {}
        sock = self._sockets.udp()
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            with contextlib.suppress(OSError):  # send on the LAN adapter, not a virtual one
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self._local_ip()))
            sock.settimeout(0.3)
            if target:
                sock.sendto(message, (target, 1900))
            sock.sendto(message, _SSDP_GROUP)
            end = time.monotonic() + timeout_s
            while time.monotonic() < end:
                try:
                    data, addr = sock.recvfrom(4096)
                except TimeoutError:
                    continue
                if target and addr[0] != target:
                    continue
                headers: dict[str, str] = {}
                for line in data.decode("utf-8", errors="replace").split("\r\n")[1:]:
                    key, _, value = line.partition(":")
                    headers[key.strip().lower()] = value.strip()
                per_ip = sum(1 for k in found if k[0] == addr[0])
                key_text = headers.get("location") or headers.get("usn") or str(per_ip)
                entry = found.setdefault(
                    (addr[0], key_text),
                    {
                        "server": headers.get("server", "")[:120],
                        "location": headers.get("location", "")[:200],
                        "usn": headers.get("usn", "")[:120],
                        "st": [],
                    },
                )
                st = headers.get("st", "")
                if st and st not in entry["st"] and len(entry["st"]) < 8:
                    entry["st"].append(st[:100])
        except OSError:
            pass
        finally:
            sock.close()
        return [
            SsdpEntry(ip, e["location"], e["server"], e["usn"], tuple(e["st"]))
            for (ip, _), e in found.items()
        ]

    def upnp_description(self, ip: str, location: str) -> dict[str, str]:
        """Fetch a UPnP device description, only over http and only from the device that announced it."""
        if not common.valid_ipv4(ip) or not isinstance(location, str) or _CONTROL_CHARS.search(location):
            return {}
        try:
            url = urlparse(location)
            port = url.port or 80
        except ValueError:
            return {}
        if url.scheme != "http" or url.hostname != ip or not _valid_port(port):
            return {}
        path = (url.path or "/") + (f"?{url.query}" if url.query else "")
        request = f"GET {path} HTTP/1.0\r\nHost: {url.netloc}\r\n\r\n".encode("ascii", errors="ignore")
        try:
            conn = self._sockets.connect(ip, port, 2.5)
        except OSError:
            return {}
        try:
            conn.sendall(request)
            body = b""
            deadline = time.monotonic() + 3
            while len(body) < HTTP_READ_LIMIT and time.monotonic() < deadline:
                chunk = conn.recv(min(8192, HTTP_READ_LIMIT - len(body)))
                if not chunk:
                    break
                body += chunk
        except OSError:
            return {}
        finally:
            conn.close()
        return xml_fields(body.partition(b"\r\n\r\n")[2].decode("utf-8", errors="replace"))

    # ----------------------------------------------------------------- HTTP and TLS
    def http_probe(self, ip: str, port: int, tls: bool, timeout_s: float = 3.0) -> HttpProbe | None:
        """GET / over plain or TLS. ``None`` when it is not HTTP (or a plain connection failed)."""
        if not common.valid_ipv4(ip) or not _valid_port(port):
            return None
        try:
            return self._http_probe(ip, port, tls, timeout_s)
        except (OSError, ssl.SSLError, ValueError):
            return None

    def _http_probe(self, ip: str, port: int, tls: bool, timeout_s: float) -> HttpProbe | None:
        raw = self._sockets.connect(ip, port, timeout_s)
        sock = raw
        cert: CertInfo | None = None
        tls_version: str | None = None
        scheme: Literal["http", "https"] = "https" if tls else "http"
        data = b""
        try:
            if tls:
                sock = self._sockets.wrap_tls(raw)
                der = sock.getpeercert(binary_form=True)
                cert = decode_cert(der) if der else None
                tls_version = sock.version()
            host = f"{ip}:{port}" if port not in (80, 443) else ip
            sock.sendall(
                (
                    f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: netview/1\r\n"
                    "Accept: text/html,*/*\r\nConnection: close\r\n\r\n"
                ).encode()
            )
            try:
                while len(data) < HTTP_READ_LIMIT:
                    chunk = sock.recv(min(8192, HTTP_READ_LIMIT - len(data)))
                    if not chunk:
                        break
                    data += chunk
            except (TimeoutError, ssl.SSLError, OSError):
                pass
        finally:
            sock.close()
            if sock is not raw:
                raw.close()
        data = data[:HTTP_READ_LIMIT]
        url = f"{scheme}://{ip}{'' if port in (80, 443) else f':{port}'}/"
        if not data.startswith(b"HTTP/"):
            if not tls:
                return None
            return HttpProbe("https", url, None, "", "", "", "", "", "", "", "", tls_version, cert)
        return _parse_response(data, scheme, url, tls_version, cert)

    # ----------------------------------------------------------------- banner
    def tcp_banner(self, ip: str, port: int, timeout_s: float = 2.0) -> bytes | None:
        """What a service that talks first says. ``None`` if it cannot be reached, ``b""`` if silent."""
        if not common.valid_ipv4(ip) or not _valid_port(port):
            return None
        try:
            conn = self._sockets.connect(ip, port, timeout_s)
        except OSError:
            return None
        try:
            conn.settimeout(1.2)
            try:
                return bytes(conn.recv(512))
            except OSError:
                return b""
        finally:
            conn.close()


def _parse_node_status(data: bytes) -> NetbiosInfo | None:
    """Parse a NetBIOS node-status reply (LM 691-715)."""
    off = (14 if data[12] & 0xC0 == 0xC0 else 46) + 10
    count, off = data[off], off + 1
    if off + 18 * count + 6 > len(data):
        return None
    names: list[NetbiosName] = []
    for i in range(count):
        chunk = data[off + 18 * i : off + 18 * (i + 1)]
        name = chunk[:15].decode("ascii", errors="replace").strip(" \x00")
        flags = struct.unpack(">H", chunk[16:18])[0]
        names.append(NetbiosName(name, chunk[15], bool(flags & 0x8000)))
    mac_bytes = data[off + 18 * count : off + 18 * count + 6]
    workstation = next((n.name for n in names if n.suffix == 0 and not n.group), "")
    workgroup = next((n.name for n in names if n.suffix == 0 and n.group), "")
    mac = ":".join(f"{b:02x}" for b in mac_bytes) if len(mac_bytes) == 6 and any(mac_bytes) else ""
    return NetbiosInfo(workstation, workgroup, tuple(names), mac)


def _title(body: bytes) -> str:
    lower = body.lower()  # ASCII-only lowering on bytes keeps offsets aligned
    start = lower.find(b"<title")
    if start < 0:
        return ""
    open_end = lower.find(b">", start)
    if open_end < 0:
        return ""
    close = lower.find(b"</title", open_end)
    if close < 0:
        return ""
    text = body[open_end + 1 : close].decode("utf-8", errors="replace")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()[:120]


def _parse_response(
    data: bytes, scheme: Literal["http", "https"], url: str, tls_version: str | None, cert: CertInfo | None
) -> HttpProbe:
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    status_line = re.match(r"HTTP/\S+\s+(\d{3})\s*(.*)", lines[0])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        key, _, value = line.partition(":")
        headers.setdefault(key.strip().lower(), value.strip())
    head_text = body[:8192].decode("utf-8", errors="replace")
    generator = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', head_text, re.I)
    refresh = re.search(
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\'>]+)', head_text, re.I
    )
    authenticate = headers.get("www-authenticate", "")
    realm = re.search(r'realm="([^"]*)"', authenticate, re.I)
    return HttpProbe(
        scheme=scheme,
        url=url,
        status=int(status_line.group(1)) if status_line else None,
        reason=(status_line.group(2) if status_line else "")[:60],
        server=headers.get("server", "")[:120],
        powered_by=headers.get("x-powered-by", "")[:80],
        location=headers.get("location", "")[:200] or (refresh.group(1).strip()[:200] if refresh else ""),
        title=_title(body),
        generator=generator.group(1)[:80] if generator else "",
        auth=authenticate.split(" ")[0][:20],
        realm=realm.group(1)[:80] if realm else "",
        tls=tls_version,
        cert=cert,
    )
