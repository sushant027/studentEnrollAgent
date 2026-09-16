"""Auth dependency: the single place student identity enters the application."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.utilities.jwt_utils import TokenError, verify_access_token
from app.utilities.logger import get_logger, set_context

log = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)


def get_current_student_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Verify the bearer token and return its `student_id`.

    Every protected route depends on this. Nothing downstream is allowed to take a
    `student_id` from anywhere else.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        student_id = verify_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    set_context(student_id=student_id)
    return student_id
