"""
Password hashing (argon2id) and opaque token helpers for Cyphward Auth.

Opaque tokens (refresh tokens, reset links, Google exchange codes) are
generated with 256 bits of entropy and stored only as SHA-256 hashes.
"""
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_opaque_token() -> str:
    """URL-safe 32-byte random token (only its hash is ever stored)."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
