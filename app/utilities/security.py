"""Password hashing. bcrypt directly — no plaintext is ever stored or logged."""

from __future__ import annotations

import bcrypt

#: bcrypt hashes at most 72 bytes and raises on longer input in bcrypt>=4.
_MAX_PASSWORD_BYTES = 72


def _encode(password: str) -> bytes:
    return (password or "").encode("utf-8")[:_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time comparison via bcrypt. Never raises on malformed stored hashes."""
    try:
        return bcrypt.checkpw(_encode(password), (password_hash or "").encode("utf-8"))
    except (ValueError, TypeError):
        return False
