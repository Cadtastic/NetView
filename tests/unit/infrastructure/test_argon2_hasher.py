from netview.infrastructure.auth.argon2_hasher import Argon2Hasher


def test_argon2_roundtrip_and_wrong_password() -> None:
    hasher = Argon2Hasher()
    hashed = hasher.hash("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert hasher.verify(hashed, "correct horse battery") is True
    assert hasher.verify(hashed, "wrong horse battery") is False
    assert hasher.verify("not a hash", "anything") is False
    assert hasher.needs_rehash(hashed) is False
