"""Authorization for application data — the security boundary (SPEC section 5).

Everything about who may see what is decided here, in application code, from the
`student_id` the caller passes in. That value originates from the verified JWT and nowhere
else: not the user's message, not the request body, not the LLM.

The non-revealing denial matters. "This application belongs to STUDENT-002" and "no such
application" return the *same* payload, because a distinguishable error would confirm that
APP-1043 exists and so leak the existence of another student's application.
"""

from __future__ import annotations

from app.constants.constants import NOT_FOUND_PAYLOAD, Events
from app.repository import enrollment_repository
from app.utilities.logger import get_logger

log = get_logger(__name__)


def get_application_status(student_id: str | None, applicant_id: str | None = None) -> dict:
    """Return the student's application, or the shared `not_found` payload.

    `applicant_id` is optional: when omitted, the authenticated student's own application is
    resolved. Both paths are scoped to `student_id`, so omitting the ID cannot widen access.
    """
    if not student_id:
        # No verified identity: fail closed. Reaching here means a wiring bug, not a user error.
        log.error(
            Events.AUTHZ_DENIED,
            "status requested without an authenticated student",
            reason="no_authenticated_student",
            applicant_id=applicant_id,
        )
        return dict(NOT_FOUND_PAYLOAD)

    if applicant_id:
        record = enrollment_repository.get_application(applicant_id)
        if record is None:
            log.warn(
                Events.AUTHZ_DENIED,
                "application not found",
                reason="unknown_applicant",
                applicant_id=applicant_id,
                owner_student_id=student_id,
            )
            return dict(NOT_FOUND_PAYLOAD)

        if record["student_id"] != student_id:
            # The one case that must be indistinguishable from the one above.
            log.warn(
                Events.AUTHZ_DENIED,
                "cross-student access denied",
                reason="not_owner",
                applicant_id=applicant_id,
                requested_by=student_id,
            )
            return dict(NOT_FOUND_PAYLOAD)
    else:
        record = enrollment_repository.get_application_for_student(student_id)
        if record is None:
            log.warn(
                Events.AUTHZ_DENIED,
                "no application on file for student",
                reason="no_application_for_student",
                requested_by=student_id,
            )
            return dict(NOT_FOUND_PAYLOAD)

    log.event(
        Events.AUTHZ_GRANTED,
        "application access granted",
        applicant_id=record["applicant_id"],
        requested_by=student_id,
    )
    # Project to the four public fields — `student_id` never leaves the service layer.
    return {
        "applicant_name": record["applicant_name"],
        "program": record["program"],
        "status": record["status"],
        "next_step": record["next_step"],
    }
