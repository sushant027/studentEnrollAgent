"""Guards on the system prompt's contract.

These do not test the model — only `scripts/demo.py` does that. They pin the instructions
that a live run proved to matter, so a future prompt edit cannot silently undo them.

Turn 1 regression: an earlier prompt listed "course catalogues" as an escalate-me topic, so
"what programs do you offer in computer science?" was read as a catalogue request and
escalated instead of calling get_program_info.
"""

from app.repository.enrollment_repository import list_program_names
from app.service.agent.prompts import build_agent_system_prompt

PROMPT = build_agent_system_prompt(list_program_names())
#: Whitespace-normalized, so an assertion does not break just because the prompt rewraps.
FLAT = " ".join(PROMPT.split())


def test_prompt_lists_the_real_programs_from_the_repository():
    """Injected from the data, so the prompt cannot drift from what the tools return."""
    for program in ("Computer Science", "Business Administration", "Nursing"):
        assert program in PROMPT


def test_prompt_routes_subject_area_questions_to_the_program_tool():
    assert 'get_program_info("Computer Science")' in FLAT
    assert "Do not escalate a question about a program in the list" in FLAT


def test_prompt_does_not_tell_the_model_to_escalate_catalogue_questions():
    """The exact wording that caused Turn 1 to escalate."""
    assert "course catalogue" not in FLAT.lower()


def test_prompt_still_forbids_answering_from_next_step():
    assert "next_step" in FLAT
    assert "NOT a list of documents" in FLAT
    for guess in ("transcripts", "references", "test scores", "essays"):
        assert guess in FLAT  # named explicitly as things never to guess at


def test_prompt_keeps_the_uncovered_topics_escalating():
    for topic in ("fee waivers", "scholarships", "financial aid", "transfer credits"):
        assert topic in FLAT


def test_prompt_allows_naming_programs_but_not_describing_them_unaided():
    assert "you must call a tool first" in FLAT


def test_prompt_forbids_relative_date_arithmetic():
    assert "never compute how many days remain" in FLAT
