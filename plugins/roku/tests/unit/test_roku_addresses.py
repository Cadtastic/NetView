from __future__ import annotations

import pytest
from netview_local_plugins.roku.addresses import is_allowed_ip


@pytest.mark.parametrize("ip", ["10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.1.60"])
def test_private_allowed(ip: str) -> None:
    assert is_allowed_ip(ip)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "169.254.1.1",
        "224.0.0.1",
        "8.8.8.8",
        "172.32.0.1",
        "192.168.1",
        "x",
        "::1",
        "",
        "0.0.0.0",
    ],
)
def test_others_refused(ip: str) -> None:
    assert not is_allowed_ip(ip)
