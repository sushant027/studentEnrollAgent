"""Login. Wrong password and unknown email produce the same error (no account enumeration)."""

from __future__ import annotations

from app.constants.constants import Events
from app.repository import student_repository
from app.utilities.jwt_utils import create_access_token
from app.utilities.logger import get_logger, mask_email
from app.utilities.security import verify_password

log = get_logger(__name__)


class InvalidCredentials(Exception):
    pass


def login(email: str, password: str) -> dict:
    """Return `{access_token, student_id}` or raise `InvalidCredentials`."""
    log.event(Events.LOGIN_ATTEMPT, "login attempt", email_masked=mask_email(email))

    student = student_repository.find_by_email(email)
    if student is None:
        # Log the distinction for operators, but return one generic error to the caller.
        log.warn(Events.LOGIN_FAILED, "login failed", reason="unknown_email",
                 email_masked=mask_email(email))
        raise InvalidCredentials("Invalid email or password")

    if not verify_password(password, student["password_hash"]):
        log.warn(Events.LOGIN_FAILED, "login failed", reason="bad_password",
                 student_id_attempted=student["student_id"])
        raise InvalidCredentials("Invalid email or password")

    token = create_access_token(student["student_id"])
    log.event(Events.LOGIN_SUCCESS, "login succeeded", student_id_logged_in=student["student_id"])
    return {"access_token": token, "student_id": student["student_id"]}
