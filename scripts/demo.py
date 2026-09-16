"""Five-turn demonstration against the real model (SPEC section 12).

    python scripts/demo.py

Runs the five required turns in one session as STUDENT-001, printing each message, the tools
the model chose, and the reply. A sixth turn demonstrates that STUDENT-001 cannot read
STUDENT-002's application.

Needs OPENAI_API_KEY in `.env`. The deterministic suite (`pytest`) does not.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.constants.constants import ESCALATION_MESSAGE  # noqa: E402
from app.repository.student_repository import init_db  # noqa: E402
from app.service.agent.graph import build_graph  # noqa: E402
from app.utilities.logger import configure_logging, set_context  # noqa: E402

TURNS = [
    "Hi, what programs do you offer in computer science?",
    "What's the application deadline for that?",
    "I already applied. My ID is APP-1042. What's my status?",
    "Can I get a fee waiver?",
    "What documents do I still need to submit?",
]

STUDENT_ID = "STUDENT-001"
SESSION_ID = "SESSION-001"

BOLD, DIM, GREEN, YELLOW, CYAN, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"
)


def run_turn(graph, number: int, message: str, student_id: str = STUDENT_ID) -> None:
    print(f"\n{BOLD}{'=' * 78}{RESET}")
    print(f"{BOLD}Turn {number}{RESET}  {DIM}(as {student_id}){RESET}")
    print(f"{CYAN}Student:{RESET} {message}")

    before = graph.get_state(
        {"configurable": {"thread_id": f"{student_id}:{SESSION_ID}"}}
    ).values.get("messages", [])

    state = graph.invoke(
        {"messages": [HumanMessage(content=message)]},
        {
            "configurable": {
                "thread_id": f"{student_id}:{SESSION_ID}",
                "student_id": student_id,
                "session_id": SESSION_ID,
            }
        },
    )

    new_messages = state["messages"][len(before):]
    for msg in new_messages:
        for call in getattr(msg, "tool_calls", None) or []:
            print(f"{YELLOW}  -> tool:{RESET} {call['name']}({call['args']})")
        if msg.type == "tool":
            print(f"{DIM}     result: {msg.content}{RESET}")

    reply = ""
    for msg in reversed(state["messages"]):
        if msg.type == "ai" and isinstance(msg.content, str) and msg.content.strip():
            reply = msg.content
            break

    status = state.get("status", "success")
    marker = f"{YELLOW}[ESCALATED]{RESET} " if reply == ESCALATION_MESSAGE else ""
    print(f"{GREEN}Assistant:{RESET} {marker}{reply}")
    print(f"{DIM}status={status}{RESET}")


def main() -> int:
    settings = get_settings()
    if not settings.has_openai_key:
        print("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        print("The deterministic test suite runs without one:  pytest -q")
        return 1

    # Quiet the structured logs so the transcript is readable; raise to INFO to see them.
    configure_logging(os.getenv("DEMO_LOG_LEVEL", "WARNING"))
    set_context(request_id="demo", session_id=SESSION_ID, student_id=STUDENT_ID)
    init_db()

    graph = build_graph()
    print(f"{BOLD}Student Enrollment Assistant — five-turn demonstration{RESET}")
    print(f"{DIM}model={settings.openai_model}  session={SESSION_ID}  student={STUDENT_ID}{RESET}")

    for number, message in enumerate(TURNS, start=1):
        run_turn(graph, number, message)

    print(f"\n{BOLD}{'=' * 78}{RESET}")
    print(f"{BOLD}Bonus: student data isolation{RESET}")
    print(f"{DIM}STUDENT-001 asking for APP-1043, which belongs to STUDENT-002.{RESET}")
    run_turn(graph, 6, "What's the status of application APP-1043?")

    print(f"\n{DIM}Expected: Turns 1-3 call tools; Turns 4-5 escalate; Turn 6 finds nothing "
          f"and reveals nothing about the other student.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
