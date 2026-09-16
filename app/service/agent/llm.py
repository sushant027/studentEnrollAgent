"""OpenAI client construction. Kept separate so tests can inject fakes instead."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.dto.schemas import GuardrailVerdict
from app.utilities.logger import get_logger

log = get_logger(__name__)


class LLMNotConfigured(Exception):
    """Raised when OPENAI_API_KEY is missing."""


def build_chat_model() -> ChatOpenAI:
    settings = get_settings()
    if not settings.has_openai_key:
        raise LLMNotConfigured("OPENAI_API_KEY is not set")
    log.event(
        "LLM_CONFIGURED",
        "chat model configured",
        model=settings.openai_model,
        temperature=settings.openai_temperature,
        timeout=settings.openai_timeout,
    )
    return ChatOpenAI(
        model=settings.openai_model,
        temperature=settings.openai_temperature,
        timeout=settings.openai_timeout,
        api_key=settings.openai_api_key,
        max_retries=1,
    )


def build_guardrail_classifier():
    """A second, structured-output call used only by the input guardrail."""
    return build_chat_model().with_structured_output(GuardrailVerdict)
