"""Read access to the mock business data.

This layer returns raw records and performs NO authorization. The ownership check lives in
`service/application_service.py`, one level up, so that every caller goes through it.
"""

from __future__ import annotations

from app.constants.constants import Events
from app.repository import mock_data
from app.utilities.logger import get_logger

log = get_logger(__name__)


def _normalize(program_name: str) -> str:
    """Case- and whitespace-insensitive key: 'computer science' == '  Computer Science '."""
    return " ".join((program_name or "").split()).lower()


def get_program(program_name: str) -> dict | None:
    key = _normalize(program_name)
    record = mock_data.PROGRAMS.get(key)
    log.debug(
        Events.REPOSITORY_LOOKUP,
        "program lookup",
        table="programs",
        key=key,
        found=record is not None,
    )
    return dict(record) if record else None


def get_deadlines(program_name: str) -> dict | None:
    key = _normalize(program_name)
    record = mock_data.DEADLINES.get(key)
    log.debug(
        Events.REPOSITORY_LOOKUP,
        "deadline lookup",
        table="deadlines",
        key=key,
        found=record is not None,
    )
    return dict(record) if record else None


def get_application(applicant_id: str) -> dict | None:
    """Return the raw application record, ownership edge included. Caller must authorize."""
    key = (applicant_id or "").strip().upper()
    record = mock_data.APPLICATIONS.get(key)
    log.debug(
        Events.REPOSITORY_LOOKUP,
        "application lookup",
        table="applications",
        applicant_id=key,
        found=record is not None,
    )
    return dict(record) if record else None


def get_application_for_student(student_id: str) -> dict | None:
    """The authenticated student's own application, for when no ID was supplied."""
    for record in mock_data.APPLICATIONS.values():
        if record["student_id"] == student_id:
            log.debug(
                Events.REPOSITORY_LOOKUP,
                "application lookup by owner",
                table="applications",
                found=True,
                applicant_id=record["applicant_id"],
            )
            return dict(record)
    log.debug(
        Events.REPOSITORY_LOOKUP, "application lookup by owner", table="applications", found=False
    )
    return None


def list_program_names() -> list[str]:
    return [p["program_name"] for p in mock_data.PROGRAMS.values()]
