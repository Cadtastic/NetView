from __future__ import annotations

import socket
from typing import Any

import pytest
from netview_local_plugins.geotrace.addresses import (
    ResolveError,
    classify,
    family_of,
    resolve,
    valid_address,
)


def fake_dns(table: dict[tuple[str, int], list[str] | int]) -> Any:
    """A getaddrinfo stand-in: table maps (host, family) to addresses or a gaierror code.

    A family of AF_UNSPEC is answered from whichever families the host has.
    """

    def getaddrinfo(host: str, port: Any, family: int = 0, *args: Any, **kwargs: Any) -> Any:
        families = (socket.AF_INET, socket.AF_INET6) if family == socket.AF_UNSPEC else (family,)
        found: list[tuple[Any, ...]] = []
        for fam in families:
            entry = table.get((host, fam), socket.EAI_NONAME)
            if isinstance(entry, int):
                if len(families) == 1:
                    raise socket.gaierror(entry, "fake")
                continue
            found += [(fam, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in entry]
        if not found:
            raise socket.gaierror(socket.EAI_NONAME, "fake")
        return found

    return getaddrinfo


def never(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("DNS must not be asked for an IP literal")


def test_literal_returns_itself_and_own_family_wins() -> None:
    assert resolve("8.8.8.8", "ipv6", never) == "8.8.8.8"
    assert resolve("2001:db8::1", "ipv4", never) == "2001:db8::1"


def test_host_name_uses_first_result_of_matching_family() -> None:
    dns = fake_dns(
        {
            ("netflix.com", socket.AF_INET): ["1.1.1.1", "2.2.2.2"],
            ("netflix.com", socket.AF_INET6): ["2001:db8::5"],
        }
    )
    assert resolve("netflix.com", "ipv4", dns) == "1.1.1.1"
    assert resolve("netflix.com", "ipv6", dns) == "2001:db8::5"


def test_no_aaaa_record_is_has_no_ipv6_address() -> None:
    dns = fake_dns({("v4only.example", socket.AF_INET): ["9.9.9.9"]})
    with pytest.raises(ResolveError, match=r"^v4only.example has no IPv6 address$"):
        resolve("v4only.example", "ipv6", dns)


def test_no_a_record_is_has_no_ipv4_address() -> None:
    dns = fake_dns({("v6only.example", socket.AF_INET6): ["2001:db8::9"]})
    with pytest.raises(ResolveError, match=r"^v6only.example has no IPv4 address$"):
        resolve("v6only.example", "ipv4", dns)


def test_nodata_error_for_one_family_is_has_no_address() -> None:
    nodata = getattr(socket, "EAI_NODATA", socket.EAI_NONAME)

    def dns(host: str, port: Any, family: int = 0, *a: Any, **k: Any) -> Any:
        if family == socket.AF_UNSPEC:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("9.9.9.9", 0))]
        raise socket.gaierror(nodata, "no data")

    with pytest.raises(ResolveError, match=r"^x.example has no IPv6 address$"):
        resolve("x.example", "ipv6", dns)


def test_unknown_name_is_cannot_find() -> None:
    with pytest.raises(ResolveError, match=r"^cannot find nope.example$"):
        resolve("nope.example", "ipv4", fake_dns({}))


def test_empty_result_is_has_no_address() -> None:
    with pytest.raises(ResolveError, match="has no IPv4 address"):
        resolve("empty.example", "ipv4", lambda *a, **k: [])


def test_other_dns_failure_is_cannot_find() -> None:
    def dns(*a: Any, **k: Any) -> Any:
        raise socket.gaierror(socket.EAI_AGAIN, "try again")

    with pytest.raises(ResolveError, match=r"^cannot find slow.example$"):
        resolve("slow.example", "ipv4", dns)


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("8.8.8.8", "public"),
        ("2606:4700::1111", "public"),
        ("10.1.2.3", "private"),
        ("172.16.0.1", "private"),
        ("172.31.255.255", "private"),
        ("172.32.0.1", "public"),
        ("192.168.1.1", "private"),
        ("127.0.0.1", "private"),
        ("::1", "private"),
        ("169.254.1.1", "private"),
        ("fe80::1", "private"),
        ("fc00::1", "private"),
        ("fd12:3456::1", "private"),
        ("100.64.0.1", "cgnat"),
        ("100.127.255.254", "cgnat"),
        ("100.128.0.1", "public"),
        ("100.63.255.255", "public"),
        ("", "none"),
        ("not an ip", "none"),
        ("fe80::1%eth0", "none"),
        ("1.2.3", "none"),
        ("netflix.com", "none"),
    ],
)
def test_classify(ip: str, expected: str) -> None:
    assert classify(ip) == expected


def test_family_of() -> None:
    assert family_of("1.2.3.4") == "ipv4"
    assert family_of("2001:db8::1") == "ipv6"


@pytest.mark.parametrize(
    "text",
    [
        "8.8.8.8",
        "2001:db8::1",
        "netflix.com",
        "a",
        "my-host.local",
        "a.b-c.example.org",
        "x" * 63,
        "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 61,
    ],
)
def test_valid_address_accepts(text: str) -> None:
    assert valid_address(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "https://netflix.com/",
        "http://netflix.com",
        "netflix.com/path",
        "netflix.com:443",
        "net flix.com",
        " netflix.com",
        "netflix.com ",
        "netflix.com.",
        ".",
        "..",
        ".netflix.com",
        "net..flix.com",
        "-bad.example",
        "bad-.example",
        "under_score.example",
        "fe80::1%eth0",
        "1.2.3.4%eth0",
        "[2001:db8::1]",
        "a" * 64,
        "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 63,
    ],
)
def test_valid_address_rejects(text: str) -> None:
    assert not valid_address(text)
