import pytest

from netview.domain.errors import ValidationError
from netview.domain.nickname import normalize_nickname


def test_trims():
    assert normalize_nickname("  Jessi's Kindle ") == "Jessi's Kindle"


def test_empty_is_none():
    assert normalize_nickname("") is None
    assert normalize_nickname("   ") is None
    assert normalize_nickname(None) is None


def test_html_and_unicode_stored_exactly():
    assert normalize_nickname("Café <b>") == "Café <b>"


def test_sixty_ok_sixty_one_rejected():
    assert normalize_nickname("x" * 60) == "x" * 60
    with pytest.raises(ValidationError):
        normalize_nickname("x" * 61)
