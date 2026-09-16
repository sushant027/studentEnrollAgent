"""LangGraph workflow (SPEC section 8).

    START -> guardrail -> agent -> tools -> agent -> respond  -> END
                  |         |                                     |
                  +---------+---------------> escalate -----------+
                  |
                  +-----------------------> blocked  -----------> END

Native tool calling throughout — no ReAct text parsing.

Escalation without a fourth tool: the model replies with the bare token ESCALATE when the
three business tools cannot answer. The conditional edge routes that to the `escalate` node,
which *discards the model's content* and emits the constant message. Because the node
substitutes the text rather than passing it through, the token can never reach the student,
and every escalation path produces byte-identical wording from one constant.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    RemoveMessage,
    SystemMessage,
    trim_messages,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.config import get_settings
from app.constants.constants import (
    ESCALATE_TOKEN,
    ESCALATION_MESSAGE,
    OFF_TOPIC_MESSAGE,
    ChatStatus,
    Events,
)
from app.service.agent.prompts import AGENT_SYSTEM_PROMPT
from app.service.guardrails.input_guardrail import InputGuardrail
from app.service.tools.enrollment_tools import BUSINESS_TOOLS
from app.utilities.logger import get_logger

log = get_logger(__name__)


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    status: str
    guardrail: dict
    escalation_reason: str


def _is_escalation(content: Any) -> bool:
    """True when the model's reply is the escalation signal rather than an answer.

    Tolerates the model wrapping the token in punctuation or quotes, but does not match a
    normal sentence that happens to contain the word.
    """
    if not isinstance(content, str):
        return False
    stripped = re.sub(r"[^A-Za-z]", "", content).upper()
    if stripped == ESCALATE_TOKEN:
        return True
    return content.strip().upper().startswith(ESCALATE_TOKEN) and len(content.strip()) <= 40


def build_graph(llm=None, guardrail: InputGuardrail | None = None, checkpointer=None):
    """Compile the graph. `llm`/`guardrail` are injectable so tests can run without OpenAI."""
    settings = get_settings()
    guard = guardrail or InputGuardrail()
    tool_node = ToolNode(BUSINESS_TOOLS)

    _bound: dict[str, Any] = {}

    def _llm_with_tools():
        """Bind tools lazily so importing this module never requires an API key."""
        if "llm" not in _bound:
            model = llm
            if model is None:
                from app.service.agent.llm import build_chat_model

                model = build_chat_model()
            _bound["llm"] = model.bind_tools(BUSINESS_TOOLS)
        return _bound["llm"]

    # --- nodes --------------------------------------------------------------

    def guardrail_node(state: AgentState) -> dict:
        log.event(Events.GRAPH_NODE_ENTER, "node: guardrail", node="guardrail")
        messages = state["messages"]
        last = messages[-1]
        history = messages[:-1]

        result = guard.check(getattr(last, "content", ""), history)

        log.event(
            Events.GRAPH_NODE_EXIT,
            "node: guardrail done",
            node="guardrail",
            allowed=result.allowed,
            is_injection=result.is_injection,
            is_in_scope=result.is_in_scope,
            reason=result.reason,
        )
        return {"guardrail": result.model_dump()}

    def agent_node(state: AgentState) -> dict:
        messages = state["messages"]
        log.event(
            Events.AGENT_STARTED,
            "node: agent",
            node="agent",
            message_count=len(messages),
        )

        # Trim to the configured window. `start_on="human"` is what keeps this safe: a plain
        # slice could leave an orphan ToolMessage at the window edge, which OpenAI rejects.
        trimmed = trim_messages(
            messages,
            token_counter=len,
            max_tokens=settings.max_chat_history,
            strategy="last",
            start_on="human",
            include_system=False,
            allow_partial=False,
        )
        if not trimmed:
            trimmed = messages[-1:]

        if len(trimmed) != len(messages):
            log.event(
                Events.HISTORY_TRIMMED,
                "history trimmed to window",
                node="agent",
                before=len(messages),
                after=len(trimmed),
                max_chat_history=settings.max_chat_history,
            )

        payload = [SystemMessage(content=AGENT_SYSTEM_PROMPT), *trimmed]

        log.event(
            Events.LLM_CALL_STARTED,
            "calling model",
            node="agent",
            llm_purpose="agent",
            messages_sent=len(payload),
            model=settings.openai_model,
        )
        with log.timed(Events.LLM_CALL_COMPLETED, "model responded",
                       node="agent", llm_purpose="agent"):
            response = _llm_with_tools().invoke(payload)

        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            for call in tool_calls:
                log.event(
                    Events.TOOL_SELECTED,
                    "model selected a tool",
                    node="agent",
                    tool=call.get("name"),
                    tool_args=call.get("args"),
                )
        else:
            log.event(
                Events.GRAPH_NODE_EXIT,
                "node: agent produced a final message",
                node="agent",
                escalating=_is_escalation(getattr(response, "content", "")),
                response_length=len(getattr(response, "content", "") or ""),
            )

        return {"messages": [response]}

    def respond_node(state: AgentState) -> dict:
        content = getattr(state["messages"][-1], "content", "") or ""
        log.event(
            Events.AGENT_COMPLETED,
            "node: respond",
            node="respond",
            status=ChatStatus.SUCCESS,
            response_length=len(content),
        )
        return {"status": ChatStatus.SUCCESS}

    def escalate_node(state: AgentState) -> dict:
        """Emit the constant escalation message, replacing whatever the model said."""
        reason = state.get("escalation_reason", "no_applicable_tool")
        messages = state["messages"]
        updates: list = []

        # Drop the model's ESCALATE signal so the token never enters history (and so the
        # next turn never sees it and learns to imitate it).
        last = messages[-1] if messages else None
        if isinstance(last, AIMessage) and _is_escalation(last.content) and last.id:
            updates.append(RemoveMessage(id=last.id))

        updates.append(AIMessage(content=ESCALATION_MESSAGE))

        log.event(
            Events.ESCALATION,
            "escalated to enrollment counselor",
            node="escalate",
            reason=reason,
            removed_signal_message=len(updates) > 1,
        )
        return {"messages": updates, "status": ChatStatus.ESCALATED}

    def blocked_node(state: AgentState) -> dict:
        guard_result = state.get("guardrail", {})
        log.warn(
            Events.AGENT_COMPLETED,
            "node: blocked by guardrail",
            node="blocked",
            status=ChatStatus.BLOCKED,
            reason=guard_result.get("reason"),
        )
        return {"messages": [AIMessage(content=OFF_TOPIC_MESSAGE)], "status": ChatStatus.BLOCKED}

    # --- routing ------------------------------------------------------------

    def route_after_guardrail(state: AgentState) -> str:
        guard_result = state.get("guardrail", {})
        if guard_result.get("allowed"):
            destination = "agent"
        elif guard_result.get("is_injection") or guard_result.get("reason") == "guardrail_error":
            # Injection attempts and guardrail failures get the escalation message: it reveals
            # nothing about the assistant and hands the student to a human.
            destination = "escalate"
        else:
            destination = "blocked"
        log.event(
            Events.GRAPH_ROUTE,
            f"guardrail -> {destination}",
            edge="after_guardrail",
            destination=destination,
            reason=guard_result.get("reason"),
        )
        return destination

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            destination = "tools"
        elif _is_escalation(getattr(last, "content", "")):
            destination = "escalate"
        else:
            destination = "respond"
        log.event(
            Events.GRAPH_ROUTE,
            f"agent -> {destination}",
            edge="after_agent",
            destination=destination,
            tool_call_count=len(getattr(last, "tool_calls", None) or []),
        )
        return destination

    # --- wiring -------------------------------------------------------------

    builder = StateGraph(AgentState)
    builder.add_node("guardrail", guardrail_node)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)
    builder.add_node("respond", respond_node)
    builder.add_node("escalate", escalate_node)
    builder.add_node("blocked", blocked_node)

    builder.add_edge(START, "guardrail")
    builder.add_conditional_edges(
        "guardrail", route_after_guardrail,
        {"agent": "agent", "escalate": "escalate", "blocked": "blocked"},
    )
    builder.add_conditional_edges(
        "agent", route_after_agent,
        {"tools": "tools", "escalate": "escalate", "respond": "respond"},
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("respond", END)
    builder.add_edge("escalate", END)
    builder.add_edge("blocked", END)

    compiled = builder.compile(checkpointer=checkpointer or MemorySaver())
    log.event("GRAPH_COMPILED", "agent graph compiled",
              nodes=["guardrail", "agent", "tools", "respond", "escalate", "blocked"])
    return compiled


_graph = None


def get_graph():
    """Process-wide compiled graph. MemorySaver lives here, so run single-worker."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
