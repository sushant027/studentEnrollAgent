"""Chat route. Student identity comes from the token dependency, never the request body."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.constants.constants import Events
from app.controller.dependencies import get_current_student_id
from app.dto.schemas import ChatRequest, ChatResponse
from app.service.chat_service import handle_chat
from app.utilities.logger import get_context, get_logger, set_context

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/enrollment", tags=["enrollment"])


@router.post("/chat", response_model=ChatResponse)
def chat_route(
    payload: ChatRequest,
    student_id: str = Depends(get_current_student_id),
) -> ChatResponse:
    set_context(session_id=payload.session_id, student_id=student_id)
    request_id = get_context()["request_id"]

    log.event(
        Events.REQUEST_RECEIVED,
        "chat turn received",
        message_length=len(payload.message),
    )

    response = handle_chat(
        student_id=student_id,
        session_id=payload.session_id,
        message=payload.message,
        request_id=request_id,
    )

    log.event(Events.RESPONSE_SENT, "chat response sent", status=response.status)
    return response
