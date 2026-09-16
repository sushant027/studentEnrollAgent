"""Fixed strings and enumerations.

Every user-visible canned response lives here so that it is emitted byte-identically
from a single place, and so tests can assert on the constant rather than on prose.
"""


class Events:
    """Structured log event names (SPEC section 13)."""

    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    INPUT_GUARD_RESULT = "INPUT_GUARD_RESULT"
    AGENT_STARTED = "AGENT_STARTED"
    TOOL_SELECTED = "TOOL_SELECTED"
    TOOL_EXECUTED = "TOOL_EXECUTED"
    ESCALATION = "ESCALATION"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    ERROR = "ERROR"

    # Supplementary events, useful when debugging a run end to end.
    LOGIN_ATTEMPT = "LOGIN_ATTEMPT"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    TOKEN_VERIFIED = "TOKEN_VERIFIED"
    TOKEN_REJECTED = "TOKEN_REJECTED"
    AUTHZ_GRANTED = "AUTHZ_GRANTED"
    AUTHZ_DENIED = "AUTHZ_DENIED"
    GRAPH_NODE_ENTER = "GRAPH_NODE_ENTER"
    GRAPH_NODE_EXIT = "GRAPH_NODE_EXIT"
    GRAPH_ROUTE = "GRAPH_ROUTE"
    LLM_CALL_STARTED = "LLM_CALL_STARTED"
    LLM_CALL_COMPLETED = "LLM_CALL_COMPLETED"
    HISTORY_TRIMMED = "HISTORY_TRIMMED"
    REPOSITORY_LOOKUP = "REPOSITORY_LOOKUP"
    DB_INITIALIZED = "DB_INITIALIZED"
    RESPONSE_SENT = "RESPONSE_SENT"


class ChatStatus:
    """Values for the `status` field of the chat response."""

    SUCCESS = "success"
    ESCALATED = "escalated"
    BLOCKED = "blocked"
    ERROR = "error"


# --- Canned responses -------------------------------------------------------

#: Emitted whenever the three business tools cannot answer the question.
ESCALATION_MESSAGE = (
    "I'd recommend speaking with an enrollment counselor for that. "
    "Would you like me to connect you?"
)

#: Routing signal the model emits to request escalation. The escalate node discards
#: the model's content entirely, so this token can never reach the student.
ESCALATE_TOKEN = "ESCALATE"

#: Guardrail rejected the message as off-topic (not an injection attempt).
OFF_TOPIC_MESSAGE = (
    "I can help with university programs, application deadlines, and your application "
    "status. Could you ask me something along those lines?"
)

#: Rendered when a tool reports `not_found`. Identical for "does not exist" and
#: "belongs to another student" so that neither case confirms the other.
NOT_FOUND_MESSAGE = (
    "I couldn't find an application with that ID on your account. "
    "Please double-check the ID, or I can connect you with an enrollment counselor."
)

# --- Tool error codes -------------------------------------------------------

ERROR_NOT_FOUND = "not_found"
ERROR_UNKNOWN_PROGRAM = "unknown_program"
ERROR_UNAUTHENTICATED = "unauthenticated"

#: The single payload returned for both "no such application" and "not yours".
NOT_FOUND_PAYLOAD = {"error": ERROR_NOT_FOUND}

# --- Domain values ----------------------------------------------------------

ALLOWED_STATUSES = ("Under Review", "Accepted", "Documents Pending")
