"""Password hashing and session token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def hash_password(password: str, *, secret: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        (salt + secret).encode("utf-8"),
        120_000,
    )
    return f"pbkdf2${salt}${digest.hex()}"


def verify_password(password: str, stored: str, *, secret: str) -> bool:
    try:
        _algo, salt, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        (salt + secret).encode("utf-8"),
        120_000,
    ).hex()
    return hmac.compare_digest(expected, digest_hex)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
