"""TOTP (authenticator-app) verification — stdlib only, RFC 6238.

30-second period, SHA-1, 6 digits, ±1 step acceptance window.
Secrets are Fernet-encrypted at rest with a key derived from
AUTH_JWT_SECRET (no plaintext TOTP seeds in the database).
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time

from cryptography.fernet import Fernet, InvalidToken

from backend.app.core.config import AUTH_JWT_SECRET

_PERIOD = 30
_DIGITS = 6
_WINDOW = 1


def _fernet() -> Fernet:
    if not AUTH_JWT_SECRET:
        raise ValueError("Authentication is not configured on the server.")
    raw = hashlib.sha256(f"cyphward-totp:{AUTH_JWT_SECRET}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def generate_secret() -> str:
    """160-bit base32 secret (no padding, authenticator-friendly)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("TOTP secret cannot be decrypted.")


def otpauth_url(secret: str, account: str, issuer: str = "Cyphward") -> str:
    from urllib.parse import quote
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account)}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


def _hotp(secret: str, counter: int) -> int:
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded.encode("ascii"))
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return code % (10 ** _DIGITS)


def verify_code(secret: str, code: str, for_time: float | None = None) -> bool:
    """Constant-time compare across the acceptance window."""
    code = (code or "").strip()
    if len(code) != _DIGITS or not code.isdigit():
        return False
    step = int((for_time if for_time is not None else time.time()) // _PERIOD)
    for delta in range(-_WINDOW, _WINDOW + 1):
        if hmac.compare_digest(f"{_hotp(secret, step + delta):06d}", code):
            return True
    return False
