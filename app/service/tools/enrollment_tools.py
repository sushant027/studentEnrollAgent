"""The three business tools (SPEC section 7).

There is no fourth escalation tool — escalation is a graph outcome.

Security note on `check_application_status`: the `config: RunnableConfig` parameter is
invisible to the model. LangChain strips it from the JSON schema sent to OpenAI, so the LLM
cannot see, set, or reason about `student_id`; LangGraph injects it at call time from the
value the HTTP layer read out of the verified JWT. The model chooses *which tool*, the
application decides *whose data*.
"""

from __future__ import annotations

from typing import Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.constants import (
    ERROR_UNKNOWN_PROGRAM,
    NOT_FOUND_PAYLOAD,
    Events,
)
from app.repository import enrollment_repository
from app.service import application_service
from app.utilities.logger import get_logger

log = get_logger(__name__)


def _student_id_from(config: RunnableConfig | None) -> str | None:
    """Pull the authenticated student out of the runtime config (never out of the model)."""
    if not config:
        return None
    return (config.get("configurable") or {}).get("student_id")


@tool
def get_program_info(program_name: str) -> dict:
    """Get details about a university program: duration, tuition and prerequisites.

    Args:
        program_name: The name of the program, e.g. "Computer Science".
    """
    with log.timed(Events.TOOL_EXECUTED, "get_program_info", tool="get_program_info",
                   program_name=program_name):
        record = enrollment_repository.get_program(program_name)

    if record is None:
        log.warn(
            Events.TOOL_EXECUTED,
            "unknown program requested",
            tool="get_program_info",
            program_name=program_name,
            result="unknown_program",
        )
        return {"error": ERROR_UNKNOWN_PROGRAM}

    log.event(
        Events.TOOL_EXECUTED,
        "program info returned",
        tool="get_program_info",
        program_name=record["program_name"],
        result="ok",
    )
    return record


@tool
def get_deadlines(program_name: str) -> dict:
    """Get the application, document submission and decision dates for a program.

    Args:
        program_name: The name of the program, e.g. "Computer Science".
    """
    with log.timed(Events.TOOL_EXECUTED, "get_deadlines", tool="get_deadlines",
                   program_name=program_name):
        record = enrollment_repository.get_deadlines(program_name)

    if record is None:
        log.warn(
            Events.TOOL_EXECUTED,
            "unknown program requested",
            tool="get_deadlines",
            program_name=program_name,
            result="unknown_program",
        )
        return {"error": ERROR_UNKNOWN_PROGRAM}

    log.event(
        Events.TOOL_EXECUTED,
        "deadlines returned",
        tool="get_deadlines",
        program_name=record["program_name"],
        result="ok",
    )
    return record


@tool
def check_application_status(
    applicant_id: Optional[str] = None, config: RunnableConfig = None
) -> dict:
    """Check the status of the CURRENT student's own application.

    Only ever returns the authenticated student's application. Use it when the student asks
    about their status, decision, or what happens next with their application.

    Args:
        applicant_id: The student's application ID, e.g. "APP-1042". Optional — omit it if
            the student has not given one, and their own application will be used.
    """
    student_id = _student_id_from(config)

    log.event(
        Events.TOOL_SELECTED,
        "check_application_status invoked",
        tool="check_application_status",
        applicant_id=applicant_id or "(not supplied)",
        has_authenticated_student=bool(student_id),
    )

    with log.timed(Events.TOOL_EXECUTED, "check_application_status",
                   tool="check_application_status"):
        result = application_service.get_application_status(student_id, applicant_id)

    if result.get("error"):
        # Identical payload whether the ID is unknown or belongs to someone else.
        return dict(NOT_FOUND_PAYLOAD)
    return result


#: Registered in this order; the ToolNode and `bind_tools` both consume this list.
BUSINESS_TOOLS = [get_program_info, get_deadlines, check_application_status]
TOOL_NAMES = [t.name for t in BUSINESS_TOOLS]
