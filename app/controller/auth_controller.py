"""Login route."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.dto.schemas import LoginRequest, LoginResponse
from app.service.auth_service import InvalidCredentials, login

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login_route(payload: LoginRequest) -> LoginResponse:
    try:
        result = login(payload.email, payload.password)
    except InvalidCredentials as exc:
        # Same message for unknown email and wrong password — no account enumeration.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    return LoginResponse(**result)
