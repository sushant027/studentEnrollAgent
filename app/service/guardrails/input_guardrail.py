"""Input guardrail (SPEC section 10).

Asks two questions only: is this an injection attempt, and is it about enrollment?

It deliberately does NOT ask "can a tool answer this?". That distinction carries Turn 4:
"Can I get a fee waiver?" is in scope, passes the guardrail, and is escalated by the *agent*.
A guardrail that reasoned about tool coverage would block it and produce the wrong outcome.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.constants.constants import Events
from app.dto.schemas import GuardrailResult
from app.service.agent.prompts import GUARDRAIL_SYSTEM_PROMPT
from app.utilities.logger import get_logger

log = get_logger(__name__)

MAX_MESSAGE_CHARS = 2000

#: Cheap deterministic pre-filter. Catches the blatant cases without an LLM round trip;
#: the classifier handles everything subtler.
_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "ignore your instructions",
    "disregard previous",
    "disregard your instructions",
    "system prompt",
    "you are now",
    "act as if you",
    "pretend you are",
    "reveal your instructions",
    "print your instructions",
    "developer mode",
)


class InputGuardrail:
    """Wraps a structured-output classifier. Inject a fake one in tests."""

    def __init__(self, classifier=None) -> None:
        self._classifier = classifier

    def _get_classifier(self):
        if self._classifier is None:
            from app.service.agent.llm import build_guardrail_classifier

            self._classifier = build_guardrail_classifier()
        return self._classifier

    def check(self, message: str, history: list | None = None) -> GuardrailResult:
        text = (message or "").strip()

        if not text:
            result = GuardrailResult(allowed=False, is_injection=False, is_in_scope=False,
                                     reason="empty_message")
            log.warn(Events.INPUT_GUARD_RESULT, "guardrail blocked", **result.model_dump())
            return result

        if len(text) > MAX_MESSAGE_CHARS:
            result = GuardrailResult(allowed=False, is_injection=False, is_in_scope=False,
                                     reason="message_too_long")
            log.warn(Events.INPUT_GUARD_RESULT, "guardrail blocked",
                     message_length=len(text), **result.model_dump())
            return result

        lowered = text.lower()
        for marker in _INJECTION_MARKERS:
            if marker in lowered:
                result = GuardrailResult(allowed=False, is_injection=True, is_in_scope=True,
                                         reason="static_injection_marker")
                log.warn(Events.INPUT_GUARD_RESULT, "guardrail blocked by static filter",
                         matched_marker=marker, **result.model_dump())
                return result

        # Give the classifier the last few turns so context-dependent follow-ups
        # ("what about that one?") are not mistaken for off-topic fragments.
        context = []
        for msg in (history or [])[-4:]:
            role = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if role in ("human", "ai") and isinstance(content, str) and content:
                context.append(f"{'Student' if role == 'human' else 'Assistant'}: {content}")

        prompt = (
            ("Recent conversation:\n" + "\n".join(context) + "\n\n" if context else "")
            + f"LAST user message to classify:\n{text}"
        )

        try:
            with log.timed(Events.LLM_CALL_COMPLETED, "guardrail classification",
                           llm_purpose="guardrail", message_length=len(text)):
                verdict = self._get_classifier().invoke(
                    [SystemMessage(content=GUARDRAIL_SYSTEM_PROMPT), HumanMessage(content=prompt)]
                )
        except Exception as exc:
            # Fail closed: a guardrail we cannot run must not become an open door.
            log.error(Events.ERROR, "guardrail classification failed; failing closed",
                      exc_info=True, error_type=type(exc).__name__, stage="guardrail")
            return GuardrailResult(allowed=False, is_injection=False, is_in_scope=True,
                                   reason="guardrail_error", failed_open=False)

        result = GuardrailResult(
            allowed=not verdict.is_injection and verdict.is_in_scope,
            is_injection=verdict.is_injection,
            is_in_scope=verdict.is_in_scope,
            reason=verdict.reason or ("ok" if not verdict.is_injection else "injection"),
        )
        log.event(Events.INPUT_GUARD_RESULT, "guardrail verdict", **result.model_dump())
        return result
