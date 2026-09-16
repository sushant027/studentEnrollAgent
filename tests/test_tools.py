"""Test 1 — the three business tools return correct mock data."""

from app.constants.constants import ALLOWED_STATUSES, ERROR_UNKNOWN_PROGRAM
from app.service.tools.enrollment_tools import (
    TOOL_NAMES,
    check_application_status,
    get_deadlines,
    get_program_info,
)

STUDENT_1 = {"configurable": {"student_id": "STUDENT-001"}}


def test_exactly_three_tools_are_registered():
    assert TOOL_NAMES == ["get_program_info", "get_deadlines", "check_application_status"]


def test_get_program_info_returns_all_four_fields():
    result = get_program_info.invoke({"program_name": "Computer Science"})
    assert result == {
        "program_name": "Computer Science",
        "duration": "4 years",
        "tuition": "$40,000/year",
        "prerequisites": "High school diploma with mathematics",
    }


def test_program_lookup_is_case_insensitive():
    assert get_program_info.invoke({"program_name": "computer science"})["program_name"] == (
        "Computer Science"
    )
    assert get_program_info.invoke({"program_name": "  NURSING  "})["program_name"] == "Nursing"


def test_unknown_program_reports_an_error_instead_of_inventing_one():
    assert get_program_info.invoke({"program_name": "Underwater Basket Weaving"}) == {
        "error": ERROR_UNKNOWN_PROGRAM
    }
    assert get_deadlines.invoke({"program_name": "Astrology"}) == {
        "error": ERROR_UNKNOWN_PROGRAM
    }


def test_get_deadlines_returns_all_three_dates():
    assert get_deadlines.invoke({"program_name": "Computer Science"}) == {
        "program_name": "Computer Science",
        "application_deadline": "March 15, 2027",
        "document_submission_deadline": "March 20, 2027",
        "decision_notification_date": "April 15, 2027",
    }


def test_all_three_programs_have_program_and_deadline_data():
    for program in ("Computer Science", "Business Administration", "Nursing"):
        assert get_program_info.invoke({"program_name": program})["duration"]
        assert get_deadlines.invoke({"program_name": program})["application_deadline"]


def test_check_application_status_returns_the_four_public_fields():
    result = check_application_status.invoke(
        {"applicant_id": "APP-1042"}, config=STUDENT_1
    )
    assert result == {
        "applicant_name": "John Smith",
        "program": "Computer Science",
        "status": "Under Review",
        "next_step": "Submit remaining required documents",
    }
    assert result["status"] in ALLOWED_STATUSES


def test_status_tool_never_returns_the_ownership_field():
    """`student_id` is an internal ownership edge and must not reach the model."""
    result = check_application_status.invoke({"applicant_id": "APP-1042"}, config=STUDENT_1)
    assert "student_id" not in result


def test_applicant_id_is_optional_and_resolves_the_students_own_application():
    result = check_application_status.invoke({}, config=STUDENT_1)
    assert result["applicant_name"] == "John Smith"
    assert result["program"] == "Computer Science"


def test_student_id_is_hidden_from_the_llm_facing_schema():
    """The model must not be able to see, set, or reason about whose data is fetched."""
    assert set(check_application_status.args) == {"applicant_id"}
    assert "student_id" not in check_application_status.args
    assert "config" not in check_application_status.args
