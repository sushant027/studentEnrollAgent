"""Chat orchestration: turns an authenticated HTTP request into one graph run.

Two things are decided here and nowhere else:

* `thread_id = f"{student_id}:{session_id}"` — `session_id` comes from the request body and is
  therefore client-controlled. Namespacing it with the JWT's `student_id` means sending
  another student's session_id opens an empty thread instead of reading their history.
* `configurable.student_id` — the identity the tools authorize against, taken from the
  verified token. The model never sees it.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.constants.constants import ESCALATION_MESSAGE, ChatStatus, Events
from app.dto.schemas import ChatResponse
from app.service.agent.graph import get_graph
from app.utilities.logger import get_logger

log = get_logger(__name__)


def build_thread_id(student_id: str, session_id: str) -> str:
    return f"{student_id}:{session_id}"


def handle_chat(
    student_id: str, session_id: str, message: str, graph=None, request_id: str = "-"
) -> ChatResponse:
    graph = graph or get_graph()
    thread_id = build_thread_id(student_id, session_id)

    log.event(
        Events.AGENT_STARTED,
        "dispatching turn to agent graph",
        thread_id=thread_id,
        message_length=len(message),
    )

    config = {
        "configurable": {
            "thread_id": thread_id,
            # Identity for the tools. Set from the verified JWT, never from the LLM.
            "student_id": student_id,
            "session_id": session_id,
            "request_id": request_id,
        }
    }

    try:
        final_state = graph.invoke({"messages": [HumanMessage(content=message)]}, config)
    except Exception as exc:
        # A failed tool or model call must never become an invented answer.
        log.error(
            Events.ERROR,
            "agent run failed; returning escalation",
            exc_info=True,
            error_type=type(exc).__name__,
            thread_id=thread_id,
        )
        return ChatResponse(
            session_id=session_id, message=ESCALATION_MESSAGE, status=ChatStatus.ERROR
        )

    status = final_state.get("status", ChatStatus.SUCCESS)
    reply = ""
    for msg in reversed(final_state["messages"]):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            reply = msg.content
            break

    if not reply:
        log.error(Events.ERROR, "agent produced no reply; escalating", thread_id=thread_id)
        reply, status = ESCALATION_MESSAGE, ChatStatus.ERROR

    log.event(
        Events.AGENT_COMPLETED,
        "turn complete",
        thread_id=thread_id,
        status=status,
        response_length=len(reply),
        history_size=len(final_state["messages"]),
    )
    return ChatResponse(session_id=session_id, message=reply, status=status)
