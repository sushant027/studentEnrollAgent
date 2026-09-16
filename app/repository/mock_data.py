"""Mock business data (SPEC section 6).

The assignment calls for hardcoded data, so programs, deadlines and applications live here
as plain dicts. Only student credentials go to SQLite, because password hashing needs a real
store. Everything is reached through `enrollment_repository`, so swapping these dicts for a
real SIS later does not touch the tools or the agent.

`applications[*]["student_id"]` is the ownership edge the authorization check reads.
"""

PROGRAMS: dict[str, dict] = {
    "computer science": {
        "program_name": "Computer Science",
        "duration": "4 years",
        "tuition": "$40,000/year",
        "prerequisites": "High school diploma with mathematics",
    },
    "business administration": {
        "program_name": "Business Administration",
        "duration": "3 years",
        "tuition": "$32,000/year",
        "prerequisites": "High school diploma with economics or mathematics",
    },
    "nursing": {
        "program_name": "Nursing",
        "duration": "4 years",
        "tuition": "$36,000/year",
        "prerequisites": "High school diploma with biology and chemistry",
    },
}

DEADLINES: dict[str, dict] = {
    "computer science": {
        "program_name": "Computer Science",
        "application_deadline": "March 15, 2027",
        "document_submission_deadline": "March 20, 2027",
        "decision_notification_date": "April 15, 2027",
    },
    "business administration": {
        "program_name": "Business Administration",
        "application_deadline": "April 1, 2027",
        "document_submission_deadline": "April 10, 2027",
        "decision_notification_date": "May 5, 2027",
    },
    "nursing": {
        "program_name": "Nursing",
        "application_deadline": "February 28, 2027",
        "document_submission_deadline": "March 7, 2027",
        "decision_notification_date": "April 1, 2027",
    },
}

APPLICATIONS: dict[str, dict] = {
    "APP-1042": {
        "applicant_id": "APP-1042",
        "student_id": "STUDENT-001",
        "applicant_name": "John Smith",
        "program": "Computer Science",
        "status": "Under Review",
        "next_step": "Submit remaining required documents",
    },
    "APP-1043": {
        "applicant_id": "APP-1043",
        "student_id": "STUDENT-002",
        "applicant_name": "Maria Lopez",
        "program": "Business Administration",
        "status": "Documents Pending",
        "next_step": "Upload official transcripts",
    },
    "APP-1044": {
        "applicant_id": "APP-1044",
        "student_id": "STUDENT-003",
        "applicant_name": "Amit Rao",
        "program": "Nursing",
        "status": "Accepted",
        "next_step": "Confirm enrollment and pay the deposit",
    },
}

#: Demo credentials. Plaintext appears here only as seed input — it is hashed on insert
#: and never stored or logged.
SEED_STUDENTS: list[dict] = [
    {
        "student_id": "STUDENT-001",
        "name": "John Smith",
        "email": "john@example.com",
        "password": "password123",
    },
    {
        "student_id": "STUDENT-002",
        "name": "Maria Lopez",
        "email": "maria@example.com",
        "password": "password123",
    },
    {
        "student_id": "STUDENT-003",
        "name": "Amit Rao",
        "email": "amit@example.com",
        "password": "password123",
    },
]
