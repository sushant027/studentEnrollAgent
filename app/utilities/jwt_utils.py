"""JWT issue/verify. Claims are `sub` (student_id) and `exp` only — no PII in the token."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings
from app.constants.constants import Events
from app.utilities.logger import get_logger

log = get_logger(__name__)


class TokenError(Exception):
    """Raised for any invalid, expired or malformed token."""


def create_access_token(student_id: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes)
    token = jwt.encode(
        {"sub": student_id, "exp": expires_at},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    log.event(
        "TOKEN_ISSUED",
        "access token issued",
        student_id_issued=student_id,
        expires_in_minutes=settings.jwt_expiry_minutes,
    )
    return token


def verify_access_token(token: str) -> str:
    """Return the `student_id` carried by a valid token, else raise `TokenError`.

    This is the ONLY source of student identity in the application.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        log.warn(Events.TOKEN_REJECTED, "token expired", reason="expired")
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        log.warn(Events.TOKEN_REJECTED, "token invalid", reason="invalid")
        raise TokenError("Invalid token") from exc

    student_id = claims.get("sub")
    if not student_id:
        log.warn(Events.TOKEN_REJECTED, "token missing subject", reason="no_subject")
        raise TokenError("Invalid token")

    log.debug(Events.TOKEN_VERIFIED, "token verified", student_id_verified=student_id)
    return student_id
