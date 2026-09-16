"""Test fixtures.

The whole suite runs without an OPENAI_API_KEY and without network access: the agent tests
drive the real graph with a scripted fake chat model, so routing, trimming, tool execution
and the authorization boundary are all exercised for real.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.config import get_settings
from app.dto.schemas import GuardrailVerdict

_ids = itertools.count(1)


def ai(content: str = "", tool_calls: list[dict] | None = None) -> AIMessage:
    """Build an AIMessage with a unique id (RemoveMessage needs one)."""
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        id=f"ai-{next(_ids)}",
    )


def tool_call(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call-{next(_ids)}", "type": "tool_call"}


class FakeChatModel(BaseChatModel):
    """Replays a scripted queue of AIMessages and records what it was asked."""

    responses: list = []
    received: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any):  # noqa: ANN401
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        if not self.responses:
            raise AssertionError("FakeChatModel ran out of scripted responses")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


class FakeGuardrailClassifier:
    """Stands in for the structured-output guardrail call."""

    def __init__(self, verdict: GuardrailVerdict | None = None) -> None:
        self.verdict = verdict or GuardrailVerdict(
            is_injection=False, is_in_scope=True, reason="ok"
        )
        self.calls: list = []

    def invoke(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(messages)
        return self.verdict


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Point every test at a throwaway database and a fixed JWT secret."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-do-not-use-in-production")
    monkeypatch.setenv("JWT_EXPIRY_MINUTES", "30")
    monkeypatch.setenv("MAX_CHAT_HISTORY", "10")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded_db():
    from app.repository.student_repository import init_db

    init_db()
    return get_settings().database_path


@pytest.fixture
def make_graph():
    """Build the real graph with a scripted model and a permissive guardrail."""
    from app.service.agent.graph import build_graph
    from app.service.guardrails.input_guardrail import InputGuardrail

    def _make(responses: list, verdict: GuardrailVerdict | None = None):
        model = FakeChatModel(responses=list(responses), received=[])
        guard = InputGuardrail(classifier=FakeGuardrailClassifier(verdict))
        return build_graph(llm=model, guardrail=guard), model

    return _make


def run_turn(graph, student_id: str, session_id: str, message: str) -> dict:
    """Invoke the graph the way chat_service does, including identity injection."""
    from langchain_core.messages import HumanMessage

    return graph.invoke(
        {"messages": [HumanMessage(content=message)]},
        {
            "configurable": {
                "thread_id": f"{student_id}:{session_id}",
                "student_id": student_id,
                "session_id": session_id,
            }
        },
    )


def last_ai_text(state: dict) -> str:
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content
    return ""
