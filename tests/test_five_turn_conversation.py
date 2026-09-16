"""Test 7 — the required five-turn conversation (SPEC section 12).

Driven by a scripted model so it is deterministic and needs no API key. What it proves is the
plumbing: context carries across turns, the right tools run with the right arguments, and
Turns 4 and 5 produce the escalation constant rather than an answer.

`scripts/demo.py` runs the same five turns against the real model, which is what proves the
model *chooses* correctly.
"""

from tests.conftest import ai, last_ai_text, run_turn, tool_call

from app.constants.constants import ESCALATE_TOKEN, ESCALATION_MESSAGE, ChatStatus

STUDENT = "STUDENT-001"
SESSION = "SESSION-001"


def _five_turn_script():
    """The model's scripted replies, in the order the graph will ask for them."""
    return [
        # Turn 1: call get_program_info, then answer from the result.
        ai(tool_calls=[tool_call("get_program_info", program_name="Computer Science")]),
        ai("We offer a Computer Science program: 4 years, $40,000/year, and it requires a high "
           "school diploma with mathematics."),
        # Turn 2: "that" resolves to Computer Science.
        ai(tool_calls=[tool_call("get_deadlines", program_name="Computer Science")]),
        ai("The application deadline for Computer Science is March 15, 2027."),
        # Turn 3: status lookup for the student's own application.
        ai(tool_calls=[tool_call("check_application_status", applicant_id="APP-1042")]),
        ai("Your application APP-1042 for Computer Science is Under Review. The next step is to "
           "submit your remaining required documents."),
        # Turn 4: no fee-waiver tool.
        ai(ESCALATE_TOKEN),
        # Turn 5: no tool lists required documents.
        ai(ESCALATE_TOKEN),
    ]


def test_five_turn_conversation(make_graph):
    graph, model = make_graph(_five_turn_script())

    # --- Turn 1 -------------------------------------------------------------
    state = run_turn(graph, STUDENT, SESSION, "Hi, what programs do you offer in computer science?")
    assert state["status"] == ChatStatus.SUCCESS
    calls = [m for m in state["messages"] if m.type == "ai" and m.tool_calls]
    assert calls[0].tool_calls[0]["name"] == "get_program_info"
    assert calls[0].tool_calls[0]["args"]["program_name"] == "Computer Science"
    assert "4 years" in last_ai_text(state)

    # --- Turn 2: "that" must resolve from context ---------------------------
    state = run_turn(graph, STUDENT, SESSION, "What's the application deadline for that?")
    assert state["status"] == ChatStatus.SUCCESS
    deadline_call = [
        c for m in state["messages"] if m.type == "ai" for c in (m.tool_calls or [])
        if c["name"] == "get_deadlines"
    ][0]
    assert deadline_call["args"]["program_name"] == "Computer Science"
    assert "March 15, 2027" in last_ai_text(state)
    # The model saw Turn 1 when resolving "that".
    assert any("computer science" in str(m.content).lower()
               for m in model.received[-1] if m.type == "human")

    # --- Turn 3 -------------------------------------------------------------
    state = run_turn(graph, STUDENT, SESSION,
                     "I already applied. My ID is APP-1042. What's my status?")
    assert state["status"] == ChatStatus.SUCCESS
    status_tool_output = [m for m in state["messages"] if m.type == "tool"][-1]
    assert "Under Review" in str(status_tool_output.content)
    assert "Under Review" in last_ai_text(state)

    # --- Turn 4: in scope, but no tool covers it ----------------------------
    state = run_turn(graph, STUDENT, SESSION, "Can I get a fee waiver?")
    assert state["status"] == ChatStatus.ESCALATED
    assert last_ai_text(state) == ESCALATION_MESSAGE

    # --- Turn 5: must not infer documents from next_step --------------------
    state = run_turn(graph, STUDENT, SESSION, "What documents do I still need to submit?")
    assert state["status"] == ChatStatus.ESCALATED
    assert last_ai_text(state) == ESCALATION_MESSAGE

    reply = last_ai_text(state)
    for invented in ("transcript", "reference", "essay", "test score", "passport", "letter"):
        assert invented not in reply.lower()

    assert model.responses == []  # every scripted reply was consumed


def test_turn_five_does_not_reuse_next_step_as_a_document_list(make_graph):
    """`next_step` is in the history by Turn 5 — it still must not become an answer."""
    graph, model = make_graph(_five_turn_script())
    for message in (
        "Hi, what programs do you offer in computer science?",
        "What's the application deadline for that?",
        "I already applied. My ID is APP-1042. What's my status?",
        "Can I get a fee waiver?",
        "What documents do I still need to submit?",
    ):
        state = run_turn(graph, STUDENT, SESSION, message)

    assert last_ai_text(state) == ESCALATION_MESSAGE
    # The tempting phrase is present in the context the model was given...
    context = " ".join(str(m.content) for m in model.received[-1])
    assert "Submit remaining required documents" in context
    # ...but it is not what the student was told.
    assert "documents" not in last_ai_text(state).lower()


def test_history_stays_within_the_configured_window(make_graph, monkeypatch):
    """MAX_CHAT_HISTORY caps what is sent to the model, without orphaning tool results."""
    graph, model = make_graph(_five_turn_script())
    for message in (
        "Hi, what programs do you offer in computer science?",
        "What's the application deadline for that?",
        "I already applied. My ID is APP-1042. What's my status?",
        "Can I get a fee waiver?",
        "What documents do I still need to submit?",
    ):
        run_turn(graph, STUDENT, SESSION, message)

    for sent in model.received:
        payload = sent[1:]  # drop the system prompt
        assert len(payload) <= 10
        # A window must never begin with an orphan tool result — OpenAI rejects that.
        assert payload[0].type == "human"
        # Every tool result must follow an AI message that requested it.
        requested = {c["id"] for m in payload if m.type == "ai" for c in (m.tool_calls or [])}
        for message in payload:
            if message.type == "tool":
                assert message.tool_call_id in requested
