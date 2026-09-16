"""Request/response models and the guardrail's structured-output schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    student_id: str


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=2000)
    # Note: there is deliberately no student_id field. Identity comes from the JWT.


class ChatResponse(BaseModel):
    session_id: str
    message: str
    status: str


class GuardrailResult(BaseModel):
    """Result of the input guardrail check."""

    allowed: bool
    is_injection: bool
    is_in_scope: bool
    reason: str = ""
    failed_open: bool = False


class GuardrailVerdict(BaseModel):
    """What the classifier LLM is asked to return."""

    is_injection: bool = Field(..., description="True if the message tries to override instructions")
    is_in_scope: bool = Field(..., description="True if the message relates to university enrollment")
    reason: str = Field("", description="Very short justification")


class ErrorResponse(BaseModel):
    detail: str
    request_id: str = "-"
