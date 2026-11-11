"""SystemServiceProbes, driven by fake sockets; nothing here touches the network."""

import socket
import struct
from typing import Any

import pytest

from netview.application.ports.probes import DnsRecord, SsdpEntry
from netview.infrastructure.net import common
from netview.infrastructure.net.probes import HTTP_READ_LIMIT, SystemServiceProbes, decode_cert, xml_fields

IP = "192.0.2.50"


class FakeUdp:
    def __init__(self, replies: list[tuple[bytes, tuple[str, int]]] | None = None) -> None:
        self.replies = list(replies or [])
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.options: list[tuple[int, int, Any]] = []
        self.closed = False

    def settimeout(self, value: float | None) -> None:
        pass

    def setsockopt(self, level: int, option: int, value: Any) -> None:
        self.options.append((level, option, value))

    def sendto(self, data: bytes, addr: tuple[str, int]) -> int:
        self.sent.append((data, addr))
        return len(data)

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        if not self.replies:
            raise TimeoutError
        return self.replies.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeTcp:
    def __init__(self, chunks: list[bytes] | None = None, endless: bytes | None = None) -> None:
        self.chunks = list(chunks or [])
        self.endless = endless
        self.delivered = 0
        self.sent = b""
        self.closed = False
        self.cert: bytes | None = None
        self.tls_version: str | None = None

    def settimeout(self, value: float | None) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, size: int) -> bytes:
        if self.endless is not None:
            chunk = (self.endless * (size // len(self.endless) + 1))[:size]
        elif self.chunks:
            chunk = self.chunks.pop(0)[:size]
        else:
            return b""
        self.delivered += len(chunk)
        return chunk

    def getpeercert(self, binary_form: bool = False) -> bytes | None:
        return self.cert

    def version(self) -> str | None:
        return self.tls_version

    def close(self) -> None:
        self.closed = True


class FakeSockets:
    def __init__(self) -> None:
        self.udps: list[FakeUdp] = []
        self.next_udp = FakeUdp()
        self.tcp: dict[tuple[str, int], FakeTcp | Exception] = {}
        self.connects: list[tuple[str, int]] = []
        self.tls_sock: FakeTcp | None = None
        self.udp_calls = 0

    def udp(self) -> FakeUdp:
        self.udp_calls += 1
        self.udps.append(self.next_udp)
        return self.next_udp

    def connect(self, ip: str, port: int, timeout_s: float) -> Any:
        self.connects.append((ip, port))
        result = self.tcp.get((ip, port), ConnectionRefusedError())
        if isinstance(result, Exception):
            raise result
        return result

    def wrap_tls(self, raw: Any) -> Any:
        assert self.tls_sock is not None
        return self.tls_sock


def _probes(sockets: FakeSockets, **kwargs: Any) -> SystemServiceProbes:
    return SystemServiceProbes(sockets, local_ip=lambda: "192.0.2.95", **kwargs)


def _name(text: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in text.split(".") if p) + b"\0"


def _ptr_answer() -> bytes:
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    target = _name("printer.local")
    return header + _name("50.2.0.192.in-addr.arpa") + struct.pack(">HHIH", 12, 1, 120, len(target)) + target


# ---------------------------------------------------------------------- mDNS


def test_mdns_query_collects_records_only_from_the_asked_host() -> None:
    sockets = FakeSockets()
    sockets.next_udp = FakeUdp(
        [(_ptr_answer(), ("192.0.2.99", 5353)), (b"short", (IP, 5353)), (_ptr_answer(), (IP, 5353))]
    )
    records = _probes(sockets).mdns_query(IP, "50.2.0.192.in-addr.arpa", timeout_s=0.1)
    assert records == [DnsRecord("50.2.0.192.in-addr.arpa", 12, "printer.local")]
    udp = sockets.udps[0]
    assert udp.sent[0][1] == (IP, 5353)
    assert udp.closed


def test_mdns_query_survives_a_hostile_answer() -> None:
    loop = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0) + b"\xc0\x0c" + bytes(14)
    sockets = FakeSockets()
    sockets.next_udp = FakeUdp([(loop, (IP, 5353)), (_ptr_answer(), (IP, 5353))])
    records = _probes(sockets).mdns_query(IP, "x.local", timeout_s=0.1)
    assert len(records) == 1  # the loop is dropped, the good answer kept


def test_mdns_query_with_an_unencodable_name_sends_nothing() -> None:
    sockets = FakeSockets()
    assert _probes(sockets).mdns_query(IP, "a" * 70 + ".local") == []
    assert sockets.udp_calls == 0


# ---------------------------------------------------------------------- NetBIOS


def _node_status(names: list[tuple[str, int, int]], mac: bytes) -> bytes:
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    body = bytes([len(names)])
    for name, suffix, flags in names:
        body += name.ljust(15).encode() + bytes([suffix]) + struct.pack(">H", flags)
    body += mac + bytes(46)
    rr = b"\xc0\x0c" + struct.pack(">HHIH", 0x21, 1, 0, len(body))
    return header + rr + body


def test_netbios_returns_workstation_workgroup_and_mac() -> None:
    reply = _node_status(
        [("DESK01", 0, 0x0400), ("WORKGROUP", 0, 0x8400), ("DESK01", 0x20, 0x0400)],
        bytes.fromhex("02005e100012"),
    )
    sockets = FakeSockets()
    sockets.next_udp = FakeUdp([(reply, (IP, 137))])
    info = _probes(sockets).netbios(IP)
    assert info is not None
    assert (info.name, info.workgroup, info.mac) == ("DESK01", "WORKGROUP", "02:00:5e:10:00:12")
    assert [(n.name, n.suffix, n.group) for n in info.names] == [
        ("DESK01", 0, False),
        ("WORKGROUP", 0, True),
        ("DESK01", 0x20, False),
    ]
    assert sockets.udps[0].sent[0][1] == (IP, 137)


def test_netbios_with_a_truncated_or_silent_host_gives_none() -> None:
    reply = _node_status([("DESK01", 0, 0x0400)], bytes(6))
    sockets = FakeSockets()
    sockets.next_udp = FakeUdp([(reply[:40], (IP, 137))])
    assert _probes(sockets).netbios(IP) is None
    sockets.next_udp = FakeUdp([])
    assert _probes(sockets).netbios(IP) is None


def test_netbios_ignores_an_answer_from_another_host() -> None:
    sockets = FakeSockets()
    sockets.next_udp = FakeUdp([(_node_status([("X", 0, 0)], bytes(6)), ("192.0.2.99", 137))])
    assert _probes(sockets).netbios(IP) is None


# ---------------------------------------------------------------------- SSDP and UPnP


def _ssdp(st: str, location: str = "http://192.0.2.50:5000/desc.xml", usn: str = "uuid:1") -> bytes:
    return (
        f"HTTP/1.1 200 OK\r\nST: {st}\r\nUSN: {usn}\r\nLOCATION: {location}\r\nSERVER: Linux UPnP/1.0\r\n\r\n"
    ).encode()


def test_ssdp_search_filters_to_the_target_and_merges_st() -> None:
    sockets = FakeSockets()
    sockets.next_udp = FakeUdp(
        [
            (_ssdp("upnp:rootdevice"), (IP, 1900)),
            (_ssdp("urn:schemas-upnp-org:device:MediaServer:1"), (IP, 1900)),
            (_ssdp("upnp:rootdevice", location="http://192.0.2.99/x.xml"), ("192.0.2.99", 1900)),
        ]
    )
    found = _probes(sockets).ssdp_search(IP, timeout_s=0.1)
    assert found == [
        SsdpEntry(
            IP,
            "http://192.0.2.50:5000/desc.xml",
            "Linux UPnP/1.0",
            "uuid:1",
            ("upnp:rootdevice", "urn:schemas-upnp-org:device:MediaServer:1"),
        )
    ]
    udp = sockets.udps[0]
    destinations = [addr for _, addr in udp.sent]
    assert (IP, 1900) in destinations
    assert ("239.255.255.250", 1900) in destinations
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("192.0.2.95")) in udp.options


def test_ssdp_search_without_a_target_returns_every_responder() -> None:
    sockets = FakeSockets()
    other = _ssdp("b", location="", usn="uuid:2")
    sockets.next_udp = FakeUdp([(_ssdp("a", usn="uuid:1"), (IP, 1900)), (other, ("192.0.2.60", 1900))])
    found = _probes(sockets).ssdp_search(timeout_s=0.1)
    assert {e.ip for e in found} == {IP, "192.0.2.60"}
    assert [addr for _, addr in sockets.udps[0].sent] == [("239.255.255.250", 1900)]


XML = (
    '<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
    "<friendlyName>{name}</friendlyName><manufacturer>Acme</manufacturer>"
    "<modelName>Box</modelName></device></root>"
)


def _http_ok(body: str) -> bytes:
    return b"HTTP/1.0 200 OK\r\nContent-Type: text/xml\r\n\r\n" + body.encode()


def test_upnp_description_reads_fields_and_truncates_to_120() -> None:
    sockets = FakeSockets()
    sockets.tcp[(IP, 5000)] = FakeTcp([_http_ok(XML.format(name="N" * 300))])
    fields = _probes(sockets).upnp_description(IP, f"http://{IP}:5000/desc.xml")
    assert fields["friendlyName"] == "N" * 120
    assert fields["manufacturer"] == "Acme"
    assert fields["modelName"] == "Box"
    assert b"GET /desc.xml HTTP/1.0" in sockets.tcp[(IP, 5000)].sent  # type: ignore[union-attr]


def test_upnp_description_refuses_a_doctype() -> None:
    body = '<!DOCTYPE r [<!ENTITY a "x">]>' + XML.format(name="&a;")
    sockets = FakeSockets()
    sockets.tcp[(IP, 80)] = FakeTcp([_http_ok(body)])
    assert _probes(sockets).upnp_description(IP, f"http://{IP}/d.xml") == {}


@pytest.mark.parametrize(
    "location",
    [
        "http://192.0.2.99/desc.xml",  # another host
        f"https://{IP}/desc.xml",  # not http
        f"ftp://{IP}/desc.xml",
        f"http://{IP}:99999/desc.xml",
        f"http://{IP}/a b",
        f"http://{IP}/x\r\nHost: evil",
        "",
    ],
)
def test_upnp_description_never_connects_for_a_foreign_or_unsafe_location(location: str) -> None:
    sockets = FakeSockets()
    assert _probes(sockets).upnp_description(IP, location) == {}
    assert sockets.connects == []


def test_upnp_description_reads_at_most_64_kib() -> None:
    sockets = FakeSockets()
    tcp = FakeTcp(endless=b"x")
    sockets.tcp[(IP, 80)] = tcp
    assert _probes(sockets).upnp_description(IP, f"http://{IP}/d.xml") == {}
    assert tcp.delivered <= HTTP_READ_LIMIT


def test_a_script_in_a_friendly_name_is_kept_as_literal_text() -> None:
    fields = xml_fields(XML.format(name="&lt;script&gt;alert(1)&lt;/script&gt;"))
    assert fields["friendlyName"] == "<script>alert(1)</script>"


# ---------------------------------------------------------------------- HTTP and TLS


def test_http_probe_reads_a_401_with_a_realm_and_a_raw_title() -> None:
    response = (
        b"HTTP/1.1 401 Unauthorized\r\nServer: Apache\r\nWWW-Authenticate: Basic realm=\"iDRAC\"\r\n\r\n"
        b"<html><head><TITLE>a <script></title></head></html>"
    )
    sockets = FakeSockets()
    tcp = FakeTcp([response])
    sockets.tcp[(IP, 8080)] = tcp
    result = _probes(sockets).http_probe(IP, 8080, tls=False)
    assert result is not None
    assert (result.scheme, result.status, result.reason) == ("http", 401, "Unauthorized")
    assert (result.auth, result.realm, result.server) == ("Basic", "iDRAC", "Apache")
    assert result.title == "a <script>"
    assert result.url == f"http://{IP}:8080/"
    assert result.cert is None and result.tls is None
    assert b"Host: 192.0.2.50:8080" in tcp.sent
    assert tcp.closed


def test_http_probe_reads_generator_location_and_powered_by() -> None:
    response = (
        b"HTTP/1.1 302 Found\r\nLocation: /login\r\nX-Powered-By: PHP/8\r\n\r\n"
        b'<meta name="generator" content="WordPress 6">'
    )
    sockets = FakeSockets()
    sockets.tcp[(IP, 80)] = FakeTcp([response])
    result = _probes(sockets).http_probe(IP, 80, tls=False)
    assert result is not None
    assert (result.location, result.powered_by, result.generator) == ("/login", "PHP/8", "WordPress 6")
    assert result.url == f"http://{IP}/"


def test_http_probe_caps_a_one_megabyte_body_at_64_kib() -> None:
    sockets = FakeSockets()
    tcp = FakeTcp(endless=b"HTTP/1.1 200 OK\r\n\r\n" + b"z" * 1000)
    sockets.tcp[(IP, 80)] = tcp
    result = _probes(sockets).http_probe(IP, 80, tls=False)
    assert result is not None and result.status == 200
    assert tcp.delivered <= HTTP_READ_LIMIT


def test_http_probe_gives_none_for_plain_non_http() -> None:
    sockets = FakeSockets()
    sockets.tcp[(IP, 22)] = FakeTcp([b"SSH-2.0-OpenSSH_9\r\n"])
    assert _probes(sockets).http_probe(IP, 22, tls=False) is None


def test_http_probe_non_http_tls_answer_is_https_without_status() -> None:
    sockets = FakeSockets()
    sockets.tcp[(IP, 8883)] = FakeTcp()
    tls = FakeTcp([b"\x15\x03\x01\x00\x02\x02\x28"])
    tls.tls_version = "TLSv1.2"
    sockets.tls_sock = tls
    result = _probes(sockets).http_probe(IP, 8883, tls=True)
    assert result is not None
    assert (result.scheme, result.status, result.tls, result.cert) == ("https", None, "TLSv1.2", None)
    assert result.url == f"https://{IP}:8883/"


def test_http_probe_over_tls_keeps_the_certificate_hash() -> None:
    sockets = FakeSockets()
    sockets.tcp[(IP, 443)] = FakeTcp()
    tls = FakeTcp([b"HTTP/1.1 200 OK\r\nServer: nginx\r\n\r\n<title>Hi</title>"])
    tls.cert = b"not a certificate"
    tls.tls_version = "TLSv1.3"
    sockets.tls_sock = tls
    result = _probes(sockets).http_probe(IP, 443, tls=True)
    assert result is not None and result.cert is not None
    assert result.cert.sha256 == decode_cert(b"not a certificate").sha256
    assert (result.title, result.tls, result.url) == ("Hi", "TLSv1.3", f"https://{IP}/")


def test_http_probe_gives_none_when_the_connection_fails() -> None:
    assert _probes(FakeSockets()).http_probe(IP, 80, tls=False) is None


# ---------------------------------------------------------------------- banner and reverse DNS


def test_tcp_banner_is_none_when_the_connection_is_refused() -> None:
    assert _probes(FakeSockets()).tcp_banner(IP, 22) is None


def test_tcp_banner_returns_what_the_service_says_or_empty_bytes() -> None:
    sockets = FakeSockets()
    sockets.tcp[(IP, 22)] = FakeTcp([b"SSH-2.0-OpenSSH_9.6\r\n"])
    assert _probes(sockets).tcp_banner(IP, 22) == b"SSH-2.0-OpenSSH_9.6\r\n"
    silent = FakeTcp()
    silent.recv = lambda size: (_ for _ in ()).throw(TimeoutError())  # type: ignore[method-assign]
    sockets.tcp[(IP, 9100)] = silent
    assert _probes(sockets).tcp_banner(IP, 9100) == b""
    assert silent.closed


def test_reverse_dns_returns_the_name_and_gives_up_on_a_slow_resolver() -> None:
    sockets = FakeSockets()
    probes = SystemServiceProbes(sockets, resolver=lambda ip: ("nas.lan", [], [ip]))
    assert probes.reverse_dns(IP) == "nas.lan"

    def failing(ip: str) -> tuple[str, list[str], list[str]]:
        raise socket.herror(1, "nope")

    assert SystemServiceProbes(sockets, resolver=failing).reverse_dns(IP) == ""

    import threading

    release = threading.Event()

    def slow(ip: str) -> tuple[str, list[str], list[str]]:
        release.wait(5)
        return ("late.lan", [], [])

    try:
        assert SystemServiceProbes(sockets, resolver=slow).reverse_dns(IP, timeout_s=0.05) == ""
    finally:
        release.set()


def test_decode_cert_falls_back_to_the_hash_for_garbage() -> None:
    cert = decode_cert(b"garbage")
    assert len(cert.sha256) == 64 and cert.subject == ""


# ---------------------------------------------------------------------- bad input


BAD = "x; rm -rf"


def test_bad_input_returns_the_empty_value_and_touches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    sockets = FakeSockets()
    touched: list[str] = []

    def forbid(*args: Any, **kwargs: Any) -> Any:
        touched.append("called")
        raise AssertionError("must not be called")

    monkeypatch.setattr(common, "run", forbid)
    monkeypatch.setattr(sockets, "udp", forbid)
    monkeypatch.setattr(sockets, "connect", forbid)
    probes = SystemServiceProbes(sockets, resolver=forbid)
    assert probes.reverse_dns(BAD) == ""
    assert probes.netbios(BAD) is None
    assert probes.mdns_query(BAD, "x.local") == []
    assert probes.ssdp_search(BAD) == []
    assert probes.upnp_description(BAD, f"http://{BAD}/x") == {}
    assert probes.http_probe(BAD, 80, tls=False) is None
    assert probes.http_probe(BAD, 443, tls=True) is None
    assert probes.tcp_banner(BAD, 22) is None
    assert probes.http_probe(IP, 0, tls=False) is None
    assert probes.http_probe(IP, 70000, tls=False) is None
    assert probes.tcp_banner(IP, -1) is None
    assert touched == []
    assert common.valid_ipv4(IP)
