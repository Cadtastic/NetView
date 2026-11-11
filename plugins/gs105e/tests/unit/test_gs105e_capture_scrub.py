"""The capture tool's scrubber: what it replaces, and that the saved fixtures need no further scrubbing."""

from __future__ import annotations

from pathlib import Path

import pytest
from netview_local_plugins.gs105e.tools.capture import Scrubber

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fw-1.6.0.11"


def test_fixtures_are_already_scrubbed() -> None:
    for page in sorted(FIX.iterdir()):
        text = page.read_bytes().decode("utf-8", errors="replace")
        scrub = Scrubber()
        scrub.learn_serial(text)
        scrub.learn_token(text)
        assert scrub.scrub(text) == text, page.name


def test_switch_name_and_descriptions_are_replaced() -> None:
    html = (
        '<input type="text" name="switch_name" id="switch_name" value="Garage rack" size="15" />'
        '<input type="text" maxlength="16" value="Uplink to Bob" name="DESCRIPTION">'
        '<input type="text" name="DESCRIPTION" disabled maxlength="16">'
    )
    out = Scrubber().scrub(html)
    assert "Garage rack" not in out
    assert "Bob" not in out
    assert 'value="GS105E Switch"' in out
    assert out.count('value="Port description"') == 1
    assert out.endswith('<input type="text" name="DESCRIPTION" disabled maxlength="16">')  # empty stays empty


@pytest.mark.parametrize("ip", ["8.8.8.8", "203.1.2.3", "10.1.2.3", "192.168.1.9", "172.20.0.1"])
def test_every_unit_address_is_replaced(ip: str) -> None:
    out = Scrubber().scrub(f"<td>{ip}</td>")
    assert ip not in out
    assert "192.0.2.1" in out


@pytest.mark.parametrize(
    "text",
    [
        "255.255.255.0",
        "255.255.0.0",
        "0.0.0.0",
        "255.255.255.255",
        "239.255.255.250",
        "224.0.0.1",
        "192.0.2.7",
        "Firmware V1.6.0.11",
        "version 1.6.0.11",
    ],
)
def test_masks_multicast_broadcast_and_versions_are_kept(text: str) -> None:
    assert Scrubber().scrub(text) == text


def test_login_challenge_is_replaced() -> None:
    out = Scrubber().scrub("<input type=hidden id='rand' value='99887766' disabled>")
    assert "99887766" not in out
    assert "12345678" in out
