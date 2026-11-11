"""Login hash tests."""

from __future__ import annotations

import hashlib

from netview_local_plugins.gs105e.auth import login_hash, merge


def test_merge_interleaves_characters() -> None:
    assert merge("abc", "12") == "a1b2c"
    assert merge("", "9") == "9"
    assert merge("ab", "") == "ab"


def test_login_hash_is_md5_of_merged_text() -> None:
    assert login_hash("t1e2s3t4"[::2], "1234") == hashlib.md5(b"t1e2s3t4").hexdigest()


def test_login_hash_encodes_non_ascii_as_utf8() -> None:
    expected = hashlib.md5(merge("pässwörd", "123").encode("utf-8")).hexdigest()
    assert login_hash("pässwörd", "123") == expected


def test_login_hash_long_password() -> None:
    password = "p" * 20
    expected = hashlib.md5(merge(password, "12345678").encode("utf-8")).hexdigest()
    assert login_hash(password, "12345678") == expected
