from __future__ import annotations

import pytest
from netview_local_plugins.roku.keys import KEYS, app_path, key_path, text_paths


def test_key_paths() -> None:
    assert key_path("Home") == "/keypress/Home"
    assert key_path("Right", "down") == "/keydown/Right"
    assert key_path("Right", "up") == "/keyup/Right"
    assert key_path("Lit_a") == "/keypress/Lit_a"


def test_key_list_has_the_cheat_sheet_keys() -> None:
    for k in ("Home", "InputHDMI1", "InputHDMI4", "InputAV1", "FindRemote", "PowerOff", "ChannelUp"):
        assert k in KEYS


@pytest.mark.parametrize("bad", ["home", "Home/../x", "Lit_", "Lit_ab", "PowerOn?x=1", ""])
def test_key_path_refuses(bad: str) -> None:
    with pytest.raises(ValueError):
        key_path(bad)


def test_key_path_refuses_unknown_action() -> None:
    with pytest.raises(ValueError):
        key_path("Home", "sideways")


def test_app_paths() -> None:
    assert app_path("12") == "/launch/12"
    assert app_path("tvinput.hdmi4") == "/launch/tvinput.hdmi4"
    assert app_path("tvinput.dtv") == "/launch/tvinput.dtv"
    assert app_path("tvinput.cvbs") == "/launch/tvinput.cvbs"


@pytest.mark.parametrize("bad", ["tvinput.hdmi5", "12a", "12345678901", "../x", "", "12\n"])
def test_app_path_refuses(bad: str) -> None:
    with pytest.raises(ValueError):
        app_path(bad)


def test_text_paths_encode_each_character() -> None:
    assert text_paths("a b&é/+") == [
        "/keypress/Lit_a",
        "/keypress/Lit_%20",
        "/keypress/Lit_b",
        "/keypress/Lit_%26",
        "/keypress/Lit_%C3%A9",
        "/keypress/Lit_%2F",
        "/keypress/Lit_%2B",
    ]


def test_text_paths_refuse_empty_and_over_100() -> None:
    with pytest.raises(ValueError):
        text_paths("")
    with pytest.raises(ValueError):
        text_paths("x" * 101)
    assert len(text_paths("x" * 100)) == 100
