"""Argon2id password hashing (library defaults)."""

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2Hasher:
    def __init__(self) -> None:
        self._hasher = _Argon2()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(hash)
        except InvalidHashError:
            return True
