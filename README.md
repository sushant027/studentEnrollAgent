# Student Enrollment Assistant

A conversational agent for a university admissions office. It answers questions about
programs, deadlines and application status — using tools for every fact, and escalating to a
human when the tools cannot answer instead of inventing something.

Built with FastAPI, LangChain, LangGraph and OpenAI. Full specification in [`SPEC.md`](SPEC.md).

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# add your OPENAI_API_KEY and set JWT_SECRET to a long random string

uvicorn app.main:app --reload --workers 1     # single worker: memory is in-process
```

Open <http://localhost:8000> and sign in as `john@example.com` / `password123`.

Run the required five-turn demonstration:

```bash
python scripts/demo.py           # needs OPENAI_API_KEY
DEMO_LOG_LEVEL=INFO python scripts/demo.py   # same, with the full structured log
```

Run the tests — **no API key or network needed**:

```bash
pytest -q                        # 58 tests
```

---

## The five-turn conversation

| Turn | Message | What happens |
| ---- | ------- | ------------ |
| 1 | "Hi, what programs do you offer in computer science?" | `get_program_info("Computer Science")` |
| 2 | "What's the application deadline for that?" | `"that"` resolved from context → `get_deadlines("Computer Science")` |
| 3 | "I already applied. My ID is APP-1042. What's my status?" | `check_application_status("APP-1042")`, after an ownership check |
| 4 | "Can I get a fee waiver?" | In scope, but no tool covers it → **escalation** |
| 5 | "What documents do I still need to submit?" | No tool lists documents → **escalation** |

Turn 5 is the interesting one. By then `next_step: "Submit remaining required documents"` is
already in the conversation from Turn 3, so the model has something plausible to answer with.
It must not: `next_step` is a status label, not a checklist, and guessing at "transcripts and
test scores" would be exactly the hallucination this design rules out.

`scripts/demo.py` also runs a sixth turn where STUDENT-001 asks about **APP-1043**, which
belongs to STUDENT-002, and gets nothing back.

---

## Architecture

```text
Browser → FastAPI → verify JWT → student_id
                          ↓
                    Input Guardrail          (injection? in scope?)
                          ↓
                        Agent  ⇄  ToolNode → mock data
                          ↓
              respond  |  escalate  |  blocked
```

* **The LLM** decides which tool to call and resolves context ("that" → Computer Science).
* **The application** decides who the student is and what they may see.
* The LLM is never trusted for access control.

### The three tools

| Tool | Input | Returns |
| ---- | ----- | ------- |
| `get_program_info` | `program_name` | duration, tuition, prerequisites |
| `get_deadlines` | `program_name` | application, document and decision dates |
| `check_application_status` | `applicant_id` (optional) | applicant name, program, status, next step |

There is no fourth "escalate" tool — see below.

---

## How four decisions were made

### Escalation is a graph outcome, not a tool

The model replies with the bare token `ESCALATE` when the three tools cannot answer. The
conditional edge routes that to the `escalate` node, which **discards the model's content**
and emits the constant message:

```python
has tool_calls        → tools
content is ESCALATE   → escalate       # node substitutes the constant
otherwise             → respond
```

The model decides *whether* to escalate; the application writes the words. Because the node
replaces the text rather than passing it through, the token cannot reach the student even if
the model wraps it in chatter, and every escalation path — no applicable tool, injection
attempt, tool failure, LLM failure — produces byte-identical wording from one constant. The
token is also stripped from history so the next turn never sees it.

### `student_id` is invisible to the model

`check_application_status` takes a hidden `config: RunnableConfig` parameter. LangChain strips
it from the JSON schema sent to OpenAI, so the model cannot see, set, or reason about whose
data is fetched; LangGraph injects it at call time from the verified JWT.

```python
assert set(check_application_status.args) == {"applicant_id"}   # tested
```

If a prompt injection convinces the model to pass `student_id: "STUDENT-002"` as an extra
argument, it is ignored and the authorization check still uses the token's identity.

### A denial reveals nothing

"Belongs to another student" and "does not exist" return the **same** payload,
`{"error": "not_found"}`. A distinguishable error would confirm that APP-1043 exists and so
leak the existence of another student's application. Tested by asserting the two payloads are
byte-identical, and that none of STUDENT-002's name, program, status or next step appears
anywhere in the response.

### Sessions are namespaced by student

`session_id` arrives in the request body and is therefore client-controlled. The LangGraph
thread key is `f"{student_id}:{session_id}"`, so sending another student's `session_id` opens
an empty thread instead of reading their history.

History is capped at `MAX_CHAT_HISTORY` (10) via
`trim_messages(start_on="human", include_system=True)`. `start_on="human"` matters: a plain
`messages[-10:]` slice can leave an orphan `ToolMessage` at the window edge, which the OpenAI
API rejects outright.

---

## Logging

Every line is one JSON object with `request_id`, `session_id`, `event` and `student_id`, so a
whole conversation can be reconstructed from the log:

```bash
uvicorn app.main:app 2>&1 | jq -c 'select(.request_id=="5a2f9e626ab4")'
uvicorn app.main:app 2>&1 | jq -c 'select(.event=="TOOL_EXECUTED")'
uvicorn app.main:app 2>&1 | jq -c 'select(.level=="ERROR")'
```

Correlation IDs travel in context variables, so tools and graph nodes log the same IDs as the
HTTP layer without being passed them.

A single turn produces roughly this trail — enough to see exactly where a bug is:

```text
REQUEST_RECEIVED → GRAPH_NODE_ENTER(guardrail) → INPUT_GUARD_RESULT → GRAPH_ROUTE(→agent)
→ AGENT_STARTED → HISTORY_TRIMMED → LLM_CALL_STARTED → LLM_CALL_COMPLETED(duration_ms)
→ TOOL_SELECTED → AUTHZ_GRANTED|AUTHZ_DENIED → TOOL_EXECUTED(duration_ms)
→ GRAPH_ROUTE(→respond|escalate) → AGENT_COMPLETED → RESPONSE_SENT
```

Set `LOG_LEVEL=DEBUG` for repository lookups and per-request HTTP lines.

**Never logged:** passwords, hashes, JWTs, API keys, student names, email addresses. Emails
are masked (`j***@example.com`) where a login needs to be traceable. `student_id` and
`applicant_id` *are* logged — access decisions have to be auditable. A redaction list in
`utilities/logger.py` drops forbidden keys even if a caller passes them by mistake.

---

## Tests

```bash
pytest -q        # 58 tests, no API key, no network
```

The agent tests drive the real graph with a scripted fake chat model, so routing, trimming,
tool execution and the authorization boundary are exercised for real — only the model is
faked.

| Area | Covers |
| ---- | ------ |
| `test_tools.py` | all three tools, case-insensitive lookup, unknown programs, `student_id` absent from the tool schema |
| `test_auth.py` | login, bcrypt hashing, no account enumeration, no PII in the token, protected endpoint |
| `test_isolation.py` | STUDENT-001 cannot read APP-1043, identical not-found payloads, injected `student_id` ignored, session isolation |
| `test_guardrail_and_escalation.py` | injection caught, in-scope questions pass, fail-closed on guardrail error, escalation constant, token never leaks |
| `test_five_turn_conversation.py` | the five turns, Turn 5 not inferring documents from `next_step`, trim window never orphaning tool results |

---

## Project layout

```text
app/
├── controller/      routes + the auth dependency
├── dto/             request/response schemas
├── service/
│   ├── agent/       graph, prompts, llm
│   ├── tools/       the three tools
│   ├── guardrails/  input guardrail
│   ├── auth_service.py
│   ├── application_service.py   ← the authorization boundary
│   └── chat_service.py          ← thread namespacing
├── repository/      mock_data.py + students (SQLite)
├── constants/       escalation message, events
└── utilities/       logging, jwt, bcrypt
templates/  static/  tests/  scripts/demo.py
```

Business data is mock Python dicts, as the assignment specifies. SQLite holds one table —
`students` — because password hashing needs a real store. Both sit behind a repository module,
so a real SIS can replace the dicts without touching the tools or the agent.

## Demo data

| Student | Email | Application | Program | Status |
| ------- | ----- | ----------- | ------- | ------ |
| STUDENT-001 John Smith | john@example.com | APP-1042 | Computer Science | Under Review |
| STUDENT-002 Maria Lopez | maria@example.com | APP-1043 | Business Administration | Documents Pending |
| STUDENT-003 Amit Rao | amit@example.com | APP-1044 | Nursing | Accepted |

Password for all three: `password123` (demo only).

---

## Future enhancements

Deliberately out of scope for a one-hour build:

* **Persistent sessions** — `MemorySaver` is in-process, so history resets on restart and the
  app must run single-worker. `SqliteSaver` or `PostgresSaver` is a one-line swap.
* **Token handling** — refresh tokens and httpOnly cookies instead of a JWT in a JS variable;
  login rate limiting and lockout.
* **Real SIS/CRM** — replace `mock_data.py` behind the existing repository interface.
* **Output guardrail** — a second check that every fact in a reply traces to a tool result,
  closing the gap that the system prompt currently handles alone.
* **Observability** — LangSmith tracing, per-turn token and cost accounting, an audit log of
  every authorization decision.
* RAG over a program catalogue, streaming responses, i18n.
