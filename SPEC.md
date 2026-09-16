# Student Enrollment AI Agent — Specification

> Status: **Phase 1 complete — awaiting `APPROVED — START IMPLEMENTATION`.**
>
> Sections 1–18 are the agreed specification. Paragraphs marked **Clarification**
> resolve ambiguity in the original draft without changing its intent.
> Section 19 records the six decisions, now settled. Section 20 fixes the test scope,
> Section 21 keeps the review notes.

---

## 1. Objective

Build a conversational Student Enrollment Assistant for a university admissions office.

The assistant should answer:

* Program information
* Application deadlines
* Application status

The assistant must use tools for factual information and must not hallucinate information.

If a question cannot be answered using the available tools, the assistant must respond with
exactly this sentence (the **escalation message**):

> "I'd recommend speaking with an enrollment counselor for that. Would you like me to connect you?"

**Clarification.** The escalation message is a constant defined in `app/constants/`. It is emitted
verbatim by application code, not paraphrased by the LLM (see §7 and Decision D1).

---

## 2. Technology Stack

* Python 3.11+
* FastAPI
* SQLite
* HTML/CSS
* LangChain
* LangGraph
* OpenAI
* Pydantic (+ `pydantic-settings`)
* `.env` configuration

### Responsibilities

| Component | Responsibility                                  |
| --------- | ----------------------------------------------- |
| FastAPI   | API and authentication boundary                 |
| SQLite    | Student, application, program and deadline data |
| LangChain | OpenAI integration and tool definitions         |
| LangGraph | Agent orchestration and session state           |
| Tools     | Access business data                            |
| HTML/CSS  | Simple chat UI                                  |

Use native structured LLM tool calling (`bind_tools`). Do not implement a manual text-based
ReAct parser.

---

## 3. Architecture

```text
Browser
   |
   v
FastAPI
   |
   +---- Login ----> SQLite
   |
   v
Authenticated Student
   |
   v
Input Guardrail
   |
   v
LangGraph Agent
   |
   +---- Tool required ----> Tool ----> SQLite
   |                            |
   |                            v
   |                          Agent
   |
   +---- No applicable tool --> Escalation
   |
   v
Response
```

The LLM decides **what action/tool is required**.

The application code decides **whether the student is authorized**.

The LLM must never make authorization decisions.

---

## 4. Authentication & Student Isolation

```text
POST /api/v1/auth/login
```

Request:

```json
{ "email": "john@example.com", "password": "password123" }
```

Response:

```json
{ "access_token": "...", "token_type": "bearer", "student_id": "STUDENT-001" }
```

Authentication uses a simple JWT (HS256). Passwords are stored as hashes (bcrypt via `passlib`),
never plaintext.

**Clarification — token handling.**

* JWT claims: `sub` = `student_id`, `exp`, `iat`, `jti`. No PII (no name, no email) in the token.
* The chat endpoint requires `Authorization: Bearer <token>`.
* `student_id` is read from the verified token on every request. A `student_id` present in a
  request body, chat message, or tool argument is never trusted.
* Expired/invalid token → `401`. No refresh token; the demo UI asks the student to log in again.

### Student Data Isolation

A student must only be able to access their own application information.

```text
STUDENT-001 → APP-1042
STUDENT-002 → APP-1043
```

If STUDENT-001 asks for APP-1043:

```text
Authenticated student STUDENT-001
Requested application APP-1043 → belongs to STUDENT-002
        |
        v
DENY
```

Do not reveal the other student's name, program, status, next step, or the **existence** of the
application.

**Clarification — non-revealing denial (important).** "Application belongs to someone else" and
"application does not exist" must be **indistinguishable** to the caller. Both return the identical
tool result:

```json
{ "error": "not_found", "message": "No application matching that ID is available on your account." }
```

Any difference in wording, latency-visible behaviour, or logging surfaced to the user would leak
the existence of another student's application. The agent renders this result as a fixed sentence
and must not speculate about why.

Authorization happens in the service layer, before any protected row is returned to the tool.

---

## 5. Database

SQLite, created and seeded at startup if absent.

### students

```text
id                INTEGER PK
student_id        TEXT UNIQUE NOT NULL     -- STUDENT-001
name              TEXT NOT NULL
email             TEXT UNIQUE NOT NULL     -- COLLATE NOCASE
password_hash     TEXT NOT NULL
```

### applications

```text
id                INTEGER PK
applicant_id      TEXT UNIQUE NOT NULL     -- APP-1042
student_id        TEXT NOT NULL REFERENCES students(student_id)
program_name      TEXT NOT NULL
status            TEXT NOT NULL            -- CHECK in ('Under Review','Accepted','Documents Pending')
next_step         TEXT NOT NULL
```

### programs

```text
id                INTEGER PK
program_name      TEXT UNIQUE NOT NULL     -- COLLATE NOCASE
duration          TEXT NOT NULL
tuition           TEXT NOT NULL
prerequisites     TEXT NOT NULL
```

### deadlines

```text
id                INTEGER PK
program_name      TEXT UNIQUE NOT NULL REFERENCES programs(program_name)   -- COLLATE NOCASE
application_deadline           TEXT NOT NULL   -- ISO 8601 (YYYY-MM-DD)
document_submission_deadline   TEXT NOT NULL   -- ISO 8601
decision_notification_date     TEXT NOT NULL   -- ISO 8601
```

**Clarification — dates.** Dates are stored ISO 8601 and formatted for display
(`"March 15, 2027"`) in the service layer, so they remain sortable and comparable.

### Seed data (fixed, so the five-turn test is reproducible)

Students (demo passwords only; documented in the README, never in `.env`):

| student_id  | name        | email               | password    |
| ----------- | ----------- | ------------------- | ----------- |
| STUDENT-001 | John Smith  | john@example.com    | password123 |
| STUDENT-002 | Maria Lopez | maria@example.com   | password123 |
| STUDENT-003 | Amit Rao    | amit@example.com    | password123 |

Applications:

| applicant_id | student_id  | program_name            | status            | next_step                                |
| ------------ | ----------- | ----------------------- | ----------------- | ---------------------------------------- |
| APP-1042     | STUDENT-001 | Computer Science        | Under Review      | Submit remaining required documents      |
| APP-1043     | STUDENT-002 | Business Administration | Documents Pending | Upload official transcripts              |
| APP-1044     | STUDENT-003 | Nursing                 | Accepted          | Confirm enrollment and pay the deposit   |

Programs: Computer Science, Business Administration, Nursing — each with duration, tuition,
prerequisites, and a full row in `deadlines`.

A repository layer isolates all SQL, so SQLite can later be replaced by a real SIS/CRM.

---

## 6. Required Tools

Exactly three tools. There is no escalation tool — escalation is handled by the graph (§7).

### get_program_info

Input: `{ "program_name": "Computer Science" }`

Output:

```json
{
  "program_name": "Computer Science",
  "duration": "4 years",
  "tuition": "$40,000/year",
  "prerequisites": "High school diploma with mathematics"
}
```

**Clarification — matching.** Lookup is case-insensitive and whitespace-normalized, with a small
explicit alias map (`"CS"`, `"comp sci"` → `Computer Science`). No fuzzy guessing beyond the map.
Unknown program → `{"error": "unknown_program", "available_programs": [...]}`; the agent may list
the available programs because that list comes from the tool, not from the model.

### check_application_status

Input: `{ "applicant_id": "APP-1042" }` — `applicant_id` is **optional** (D2). When the student does
not state an ID ("what's my status?"), the model omits it and the service resolves the authenticated
student's own application. Omitting it is not a way to widen access: the lookup is scoped to the
authenticated `student_id` either way.

The service verifies the application belongs to the authenticated student **before** returning any
field.

Output:

```json
{
  "applicant_name": "John Smith",
  "program": "Computer Science",
  "status": "Under Review",
  "next_step": "Submit remaining required documents"
}
```

Allowed statuses: `Under Review`, `Accepted`, `Documents Pending`.

**Clarification — identity injection.** `student_id` is **not** a parameter in the tool schema the
LLM sees. It is injected at runtime from the verified JWT via the LangGraph
`config["configurable"]` / `InjectedToolArg` mechanism. The model therefore cannot supply, alter,
or reason about whose data is fetched.

Failure modes, all returning the identical non-revealing payload from §4: unknown `applicant_id`,
`applicant_id` owned by another student.

### get_deadlines

Input: `{ "program_name": "Computer Science" }`

Output:

```json
{
  "program_name": "Computer Science",
  "application_deadline": "March 15, 2027",
  "document_submission_deadline": "March 20, 2027",
  "decision_notification_date": "April 15, 2027"
}
```

Same matching and unknown-program rules as `get_program_info`.

**Clarification.** The agent states dates as returned. It must not compute "days remaining" or any
other relative time claim — there is no clock tool.

---

## 7. LangGraph Workflow

```text
START
  |
  v
Input Guardrail
  |
  +---- blocked ----> Rejection/Escalation ----> END
  |
  v
Agent
  |
  +---- Tool Call --------------> ToolNode ----> Agent
  |
  +---- No applicable tool -----> Escalate ----> END
  |
  +---- Grounded answer --------> Response ----> END
```

The agent may perform multiple tool calls per turn (including parallel tool calls).

**Clarification — loop bound.** The agent↔tool cycle is capped (`recursion_limit`, max 5 tool
rounds per turn). On exceeding it, the turn ends in the escalate node with an `ESCALATION` log event.

### Escalation is an application-level outcome (D1)

There is **no** `escalate_to_counselor` tool. The LLM never authors the escalation text and never
calls anything to escalate. The graph resolves it:

1. The system prompt instructs: when the question cannot be answered from the three business tools,
   reply with the single token `ESCALATE` and nothing else — no apology, no explanation, no
   alternative suggestion.
2. The conditional edge out of `agent` routes on the message itself:

```text
final AIMessage has tool_calls        -> tools
final AIMessage content == ESCALATE   -> escalate      (token is a constant, matched after strip/upper)
otherwise                             -> respond
```

3. The `escalate` node discards the model's content entirely and emits
   `constants.ESCALATION_MESSAGE` verbatim, sets `status: "escalated"`, and logs `ESCALATION`.

The token is a routing signal, never shown to the student — the node replaces it, so a leaked
sentinel is impossible. The same node is the terminus for guardrail injection rejections, the
recursion cap, and unrecoverable tool/LLM failures, so every escalation path produces byte-identical
text from one constant.

LangGraph maintains conversation state per session via a checkpointer (see §9).

---

## 8. Input Guardrail

Runs before the agent. Two checks:

1. Prompt injection
2. Relevance to the enrollment assistant

Output:

```json
{ "allowed": true, "is_injection": false, "is_in_scope": true }
```

Implementation: a cheap deterministic pre-filter (empty/oversized input, obvious
instruction-override patterns) followed by a single structured-output LLM classification into the
Pydantic model above.

**Clarification — scope is broad, not tool-shaped.** The guardrail only asks "is this about
university enrollment?" It must **not** check whether a tool exists. "Can I get a fee waiver?" and
"What documents do I still need?" are in scope and must pass the guardrail; the *agent* then
escalates because no tool applies:

```text
ALLOW → Agent → No applicable tool → Escalate
```

Follow-ups that depend on context ("What's the application deadline for that?") are in scope. The
guardrail sees the recent conversation so pronouns do not cause false rejections.

**Clarification — failure behaviour.** If the guardrail LLM call fails or returns unparseable
output, the turn fails closed: the student receives the escalation message, and `ERROR` +
`INPUT_GUARD_RESULT` are logged. A guardrail rejection returns a polite in-scope reminder for
off-topic input, and the escalation message for detected injection — never an echo of the
offending text.

---

## 9. Conversation Memory

The latest **10 messages per session** are retained, configurable:

```env
MAX_CHAT_HISTORY=10
```

**Clarification — what counts and how trimming works (important).** Trimming operates on complete
turns, not raw list slicing:

* The system prompt is always retained and is not counted.
* The window counts human + final AI messages. Tool-call/tool-result pairs are kept intact with
  their parent AI message.
* A trimmed history never begins with an orphan `ToolMessage` and never contains an AI message
  whose `tool_calls` lack matching results — OpenAI rejects both.
* Implemented with LangChain `trim_messages` (`start_on="human"`, `include_system=True`).

**Clarification — session isolation (important).** `session_id` arrives in the request body and is
therefore attacker-controlled. The checkpointer key is **not** `session_id` alone. It is
`thread_id = f"{student_id}:{session_id}"`, derived from the verified JWT, so supplying another
student's `session_id` creates a new empty thread instead of reading their history.

**Clarification — checkpointer (D3).** `MemorySaver`, in-process. History resets on restart and does
not survive multiple workers; acceptable for the demo, and the app runs single-worker. Swapping in
`SqliteSaver` is a one-line change, listed in the README as a production enhancement.

---

## 10. Chat API

```text
POST /api/v1/enrollment/chat        (requires Bearer token)
```

Request:

```json
{ "session_id": "SESSION-001", "message": "What's the application deadline for that?" }
```

Student identity comes from the authenticated request, never from the LLM or the request body.

Response:

```json
{
  "session_id": "SESSION-001",
  "message": "The application deadline for Computer Science is March 15, 2027.",
  "status": "success"
}
```

`status` ∈ `success`, `escalated`, `blocked`, `error`.

Also provided:

```text
GET  /health                        -> { "status": "ok" }
GET  /                              -> login + chat UI
```

---

## 11. Required Five-Turn Test

All five turns run in one session as STUDENT-001 (John Smith).

**Turn 1** — `Hi, what programs do you offer in computer science?`
→ `get_program_info("Computer Science")`

**Turn 2** — `What's the application deadline for that?`
→ `"that"` resolves to Computer Science → `get_deadlines("Computer Science")`

**Turn 3** — `I already applied. My ID is APP-1042. What's my status?`
→ `check_application_status("APP-1042")`

**Turn 4** — `Can I get a fee waiver?`
→ no available tool → escalation. No invented answer.

**Turn 5** — `What documents do I still need to submit?`
→ no available tool → escalation.

**Clarification — Turn 5 is the hard one.** Turn 3 already put
`next_step: "Submit remaining required documents"` into the conversation state. The model will be
tempted to answer from it. The system prompt states explicitly: `next_step` is a status label, not
a document checklist; there is no tool that lists required documents; any question about *which*
documents are outstanding escalates. This is covered by a dedicated regression test.

An additional isolation turn is demonstrated: STUDENT-001 asking for `APP-1043` receives the
non-revealing denial of §4.

---

## 12. Logging

Structured JSON logging with `request_id`, `session_id`, `event`.

Events: `REQUEST_RECEIVED`, `INPUT_GUARD_RESULT`, `AGENT_STARTED`, `TOOL_SELECTED`,
`TOOL_EXECUTED`, `ESCALATION`, `AGENT_COMPLETED`, `ERROR`.

`request_id` is created by middleware and propagated through the agent and tools via a
`contextvar`.

**Clarification — what is never logged.** Passwords, password hashes, API keys, JWTs, email
addresses, student names. Message bodies and tool result payloads are not logged at `INFO`; only
metadata (message length, tool name, argument *keys*, success/failure, duration). Full payload
logging is available at `DEBUG` and only when `APP_ENV=development`. `student_id` and
`applicant_id` are logged as identifiers — they are needed to audit access decisions.

---

## 13. Configuration

All configuration comes from `.env`, loaded through a Pydantic `Settings` object that fails fast on
missing required values.

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OPENAI_TEMPERATURE=0
OPENAI_TIMEOUT=30

MAX_CHAT_HISTORY=10

JWT_SECRET=
JWT_EXPIRY_MINUTES=30

LOG_LEVEL=INFO
APP_ENV=development

DATABASE_PATH=enrollment.db
```

`.env.example` is committed. `.env` is git-ignored and never committed.

---

## 14. Project Structure

```text
student-enrollment-agent/
│
├── app/
│   ├── controller/          # FastAPI routers: auth, chat, health
│   ├── dto/                 # Pydantic request/response models
│   ├── service/
│   │   ├── agent/           # LangGraph graph, nodes, system prompt
│   │   ├── tools/           # the three business tools
│   │   └── guardrails/      # input guardrail
│   ├── repository/          # all SQL; schema + seed
│   ├── model/               # domain models
│   ├── constants/           # escalation message, statuses, events
│   └── utilities/           # logging, jwt, security, formatting
│
├── templates/               # login + chat page
├── static/                  # css, js
├── tests/
│
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── SPEC.md
```

Keep the implementation simple. No unnecessary infrastructure.

---

## 15. Error Handling

| Case                          | Behaviour                                                              |
| ----------------------------- | ---------------------------------------------------------------------- |
| Invalid request body          | `422` / `400`, structured error DTO                                    |
| Invalid credentials           | `401`, generic "Invalid email or password" (no account enumeration)     |
| Missing/expired token         | `401`                                                                  |
| Unauthorized application access | Tool returns the non-revealing `not_found` payload; HTTP stays `200`  |
| Unknown program               | Tool returns `unknown_program` + available program list                |
| Unknown applicant             | Identical to unauthorized access                                       |
| Tool failure                  | Structured error to the agent; agent escalates, never fabricates       |
| LLM failure / timeout         | `200` with `status: "error"` and a safe message; `ERROR` logged        |
| Guardrail rejection           | `200` with `status: "blocked"`                                         |
| Unexpected error              | `500` with `request_id`, no stack trace to the client                  |

Every error response carries the `request_id` so logs can be correlated.

Tool failures must never result in fabricated answers.

---

## 16. Security Principle

```text
LLM
 ├── Understand user request
 ├── Resolve conversation context
 └── Select appropriate tool

Application
 ├── Authentication
 ├── Authorization
 ├── Student identity
 ├── Session isolation
 └── PII protection

Tools
 └── Retrieve factual business information

LangGraph
 └── Orchestrate workflow and state
```

The LLM must never be trusted for access control.

---

## 17. Out of Scope

Not implemented: RAG, vector database, OCR, fine-tuning, multi-agent systems, real SIS/CRM
integration, Kubernetes, complex cloud deployment. These are listed in the README as future
production enhancements, alongside: persistent multi-worker session store, refresh tokens and
httpOnly cookie storage, login rate limiting, per-tenant audit trail, and output-side guardrails.

---

## 18. Development Process

**Phase 1** — finalize this `SPEC.md`, raise issues. **STOP and wait for approval.**

**Phase 2** — after `APPROVED — START IMPLEMENTATION`, build in this order:

1. SQLite schema and seed data
2. Authentication
3. Repository layer
4. Tools
5. OpenAI/LangChain integration
6. LangGraph agent
7. Session memory
8. Input guardrail
9. FastAPI APIs
10. HTML/CSS UI
11. Logging
12. Tests
13. Five-turn demonstration
14. README

No functionality outside this specification without discussing it first.

---

## 19. Decisions (settled)

| # | Decision | Resolution |
| - | -------- | ---------- |
| **D1** | Escalation mechanism | **No fourth tool.** Escalation is an application-level outcome: `Agent → no applicable business tool → escalate node → constant message`. Mechanism in §7. |
| **D2** | `applicant_id` optional | **Yes.** Omitted → service resolves the authenticated student's own application. §6. |
| **D3** | Checkpointer | **`MemorySaver`** (in-process) for the demo. §9. |
| **D4** | Tests | **Critical tests only** — see §20. |
| **D5** | Model | **`gpt-4o-mini`**, overridable via `OPENAI_MODEL`. §13. |
| **D6** | UI token storage | **In-memory JS variable.** §4. |

---

## 20. Test Scope (D4 — critical only)

Deterministic tests, no `OPENAI_API_KEY` required, no network:

1. **Authorization denial** — STUDENT-001 requesting APP-1043 and requesting a nonexistent
   APP-9999 return byte-identical payloads, and neither contains STUDENT-002's name, program,
   status, or next step.
2. **Session isolation** — two students using the same `session_id` string get separate threads;
   neither sees the other's messages.
3. **History trimming** — a trimmed window never starts with an orphan `ToolMessage` and never
   retains an AI message whose `tool_calls` lost their results; the system prompt survives.
4. **Escalation routing** — the `escalate` node emits `ESCALATION_MESSAGE` verbatim and never leaks
   the `ESCALATE` token, driven through the graph with a fake chat model.
5. **Auth** — login succeeds, wrong password gives the same generic error as unknown email, no
   plaintext password is stored, and the chat endpoint rejects a missing/expired token.

Plus one live demonstration, not part of the deterministic suite:

6. **`scripts/demo.py`** — runs the §11 five turns against the real API in one session and prints
   each turn, the tool selected, and the final message, then the isolation turn (STUDENT-001 asking
   for APP-1043). This is the five-turn demonstration required by §18 step 13.

---

## 21. Notes recorded during review (no decision needed)

* **Turn 3 / seed alignment** — the expected Turn 3 output names John Smith, so the demo login must
  be STUDENT-001 / `john@example.com`, who owns APP-1042. Fixed in §5.
* **Existence leakage** — the single most likely way to fail §4 is returning a different message for
  "not found" vs "not yours". Specified as one shared payload and covered by a test.
* **`session_id` trust** — client-supplied session identifiers are a cross-student history leak
  unless namespaced by the authenticated student. Specified in §9.
* **History trimming** — naive `messages[-10:]` breaks the OpenAI API by orphaning tool results.
  Specified in §9.
* **Guardrail over-blocking** — a guardrail that reasons about tool availability would block Turn 4
  instead of escalating it, producing the wrong `status`. Specified in §8.
* **PII to OpenAI** — `check_application_status` results include the applicant's name, which is sent
  to OpenAI as tool output. Inherent to the design; called out in the README.
