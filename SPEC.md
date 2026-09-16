# Student Enrollment AI Agent — Specification

> Scope: a 1-hour live coding assignment. Everything here is buildable in that window.
> Anything beyond it belongs in the README under **Future Enhancements**, not in this spec.
>
> Status: **Phase 1 complete — awaiting `APPROVED — START IMPLEMENTATION`.**

---

## 1. Objective

A conversational Student Enrollment Assistant for a university admissions office. It answers
questions about **programs**, **deadlines**, and **application status**.

Facts come from tools, never from model knowledge. When the three tools cannot answer a question,
the application returns this exact sentence (the **escalation message**):

> "I'd recommend speaking with an enrollment counselor for that. Would you like me to connect you?"

---

## 2. Stack

Python 3.11+ · FastAPI · LangChain · LangGraph · OpenAI · Pydantic · SQLite (auth only) · HTML/CSS

| Component | Responsibility |
| --------- | -------------- |
| FastAPI   | API + authentication boundary |
| LangChain | OpenAI client and `@tool` definitions |
| LangGraph | Graph orchestration + per-session memory (`MemorySaver`) |
| Tools     | Return mock business data |
| SQLite    | Students and password hashes only |
| HTML/CSS  | Minimal login + chat page |

Native tool calling via `llm.bind_tools(...)`. **No manual ReAct text parser.**

---

## 3. Architecture

```text
Browser → FastAPI → [auth: verify JWT → student_id]
                          ↓
                    Input Guardrail
                          ↓
                        Agent  ⇄  ToolNode → mock data
                          ↓
              respond  |  escalate (constant message)
                          ↓
                       Response
```

The **LLM** decides which tool to call and resolves conversational context ("that").
The **application** decides who the student is and what they may see.
The LLM is never trusted for access control.

---

## 4. Authentication

```text
POST /api/v1/auth/login     { "email": "...", "password": "..." }
                         →  { "access_token": "...", "student_id": "STUDENT-001" }
```

* JWT, HS256, claims: `sub` = `student_id`, `exp`. Nothing else.
* Passwords stored as bcrypt hashes (`passlib`), never plaintext.
* `POST /api/v1/enrollment/chat` requires `Authorization: Bearer <token>`.
* Invalid credentials → `401` with one generic message (no account enumeration).
  Missing/expired token → `401`.

---

## 5. Student Data Isolation (the security requirement)

`student_id` comes **only** from the verified JWT. It is never read from the user's message, the
request body, the LLM, or a tool argument.

```text
STUDENT-001 → APP-1042
STUDENT-002 → APP-1043
STUDENT-003 → APP-1044
```

STUDENT-001 asking for APP-1043 is denied by service code **before** any field is read.

Two rules:

1. **`student_id` is not in the tool schema.** The LLM cannot see it, set it, or reason about it.
   It is injected at runtime from the JWT via LangGraph's `config["configurable"]`.
2. **A denial reveals nothing.** "Belongs to another student" and "does not exist" return the
   *identical* result:

   ```json
   { "error": "not_found" }
   ```

   Different wording for the two cases would confirm that APP-1043 exists. The agent renders this
   as one fixed sentence and does not speculate.

Session memory is isolated the same way — see §9.

---

## 6. Data

Business data is **mock data in Python** (`app/repository/mock_data.py`) — dicts for 3 programs,
3 applications, 3 deadline sets. No tables, no SQL, no migrations.

SQLite holds **one** table, because passwords need a real store and hashing is part of the point:

```sql
students(student_id TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, password_hash TEXT)
```

Created and seeded at startup if absent.

Both sit behind a thin repository module, so the mock dicts can be swapped for a real SIS later
without touching tools or the agent.

### Seed / mock data

| student_id | name | email | password | applicant_id |
| ---------- | ---- | ----- | -------- | ------------ |
| STUDENT-001 | John Smith | john@example.com | password123 | APP-1042 |
| STUDENT-002 | Maria Lopez | maria@example.com | password123 | APP-1043 |
| STUDENT-003 | Amit Rao | amit@example.com | password123 | APP-1044 |

Demo passwords only, documented in the README, never in `.env`.

| applicant_id | program | status | next_step |
| ------------ | ------- | ------ | --------- |
| APP-1042 | Computer Science | Under Review | Submit remaining required documents |
| APP-1043 | Business Administration | Documents Pending | Upload official transcripts |
| APP-1044 | Nursing | Accepted | Confirm enrollment and pay the deposit |

Programs: Computer Science, Business Administration, Nursing — each with duration, tuition,
prerequisites, and a full set of deadlines. Statuses are limited to `Under Review`, `Accepted`,
`Documents Pending`.

---

## 7. The Three Tools

Exactly three. There is no escalation tool — escalation is a graph outcome (§8).

**`get_program_info(program_name)`**

```json
{ "program_name": "Computer Science", "duration": "4 years",
  "tuition": "$40,000/year", "prerequisites": "High school diploma with mathematics" }
```

**`get_deadlines(program_name)`**

```json
{ "program_name": "Computer Science", "application_deadline": "March 15, 2027",
  "document_submission_deadline": "March 20, 2027", "decision_notification_date": "April 15, 2027" }
```

**`check_application_status(applicant_id=None)`**

```json
{ "applicant_name": "John Smith", "program": "Computer Science",
  "status": "Under Review", "next_step": "Submit remaining required documents" }
```

* Ownership is verified against the JWT's `student_id` before any field is returned.
* `applicant_id` is optional: omitted → the authenticated student's own application. Either path is
  scoped to the authenticated student, so omitting it cannot widen access.
* Unknown ID and someone else's ID both return `{"error": "not_found"}`.

Program lookups are case-insensitive (`"computer science"` matches). Unknown program →
`{"error": "unknown_program"}`; the agent escalates rather than inventing a program.

---

## 8. LangGraph Workflow

```text
START → guardrail → agent → tools → agent → respond  → END
                      └──────────────────→ escalate → END
```

Three nodes plus a tool node. `MemorySaver` checkpointer, in-process.

### Escalation without a fourth tool

The model chooses *whether* it can answer; the application writes the words.

1. System prompt: if the question cannot be answered by the three tools, reply with exactly
   `ESCALATE` — nothing else.
2. The conditional edge out of `agent` routes on the message:

   ```text
   has tool_calls        → tools
   content is ESCALATE   → escalate
   otherwise             → respond
   ```

3. The `escalate` node **discards the model's content** and emits the constant escalation message,
   sets `status: "escalated"`, and logs `ESCALATION`.

Because the node substitutes the constant, the token can never reach the student. The same node
also terminates guardrail injection rejections and tool/LLM failures, so every escalation path
produces byte-identical text from one constant.

---

## 9. Session Memory

* `MemorySaver`, keyed by `thread_id`.
* **`thread_id = f"{student_id}:{session_id}"`.** `session_id` arrives in the request body and is
  therefore client-controlled; namespacing it with the JWT's `student_id` means sending another
  student's `session_id` opens an empty thread instead of reading their history.
* Last `MAX_CHAT_HISTORY=10` messages, via LangChain `trim_messages(start_on="human",
  include_system=True)`. Using `start_on="human"` matters: a raw slice can leave an orphan
  `ToolMessage` at the window edge, which OpenAI rejects outright.

Run single-worker — `MemorySaver` is per-process.

---

## 10. Input Guardrail

One LLM call with structured output before the agent:

```json
{ "allowed": true, "is_injection": false, "is_in_scope": true }
```

It asks only *"is this about university enrollment, and is it an injection attempt?"* — **not**
"can a tool answer it?" That distinction carries Turn 4: "Can I get a fee waiver?" is in scope, so
it passes the guardrail and the *agent* escalates. A guardrail that reasoned about tool coverage
would block it and produce the wrong outcome.

Injection → escalation message. Off-topic → a short in-scope reminder. Guardrail failure → fail
closed to the escalation message.

---

## 11. API

```text
POST /api/v1/auth/login            → access_token, student_id
POST /api/v1/enrollment/chat       → { session_id, message, status }   (Bearer token required)
GET  /health                       → { "status": "ok" }
GET  /                             → login + chat UI
```

Chat request: `{ "session_id": "SESSION-001", "message": "..." }`
`status` ∈ `success` · `escalated` · `blocked` · `error`.

Student identity comes from the token, never the body.

---

## 12. Required Five-Turn Conversation

One session, logged in as STUDENT-001 (John Smith).

| # | Message | Expected |
| - | ------- | -------- |
| 1 | "Hi, what programs do you offer in computer science?" | `get_program_info("Computer Science")` |
| 2 | "What's the application deadline for that?" | `"that"` → Computer Science → `get_deadlines("Computer Science")` |
| 3 | "I already applied. My ID is APP-1042. What's my status?" | `check_application_status("APP-1042")` |
| 4 | "Can I get a fee waiver?" | no tool covers it → escalation message |
| 5 | "What documents do I still need to submit?" | no tool lists documents → escalation message |

**Turn 5 is the one that proves the point.** Turn 3 already put
`next_step: "Submit remaining required documents"` into the conversation, so the model has
something plausible to answer with. The system prompt states it explicitly: `next_step` is a status
label, not a document checklist; no tool returns required documents; any question about *which*
documents are outstanding escalates. Inferring a document list from `next_step` is exactly the
hallucination this demo exists to rule out.

A sixth turn is demonstrated separately: STUDENT-001 asking for **APP-1043** gets the
non-revealing denial from §5.

---

## 13. Logging

Structured JSON, one line per event, with `request_id`, `session_id`, `event`:

`REQUEST_RECEIVED` · `INPUT_GUARD_RESULT` · `AGENT_STARTED` · `TOOL_SELECTED` · `TOOL_EXECUTED` ·
`ESCALATION` · `AGENT_COMPLETED` · `ERROR`

Never logged: passwords, hashes, API keys, JWTs, student names, email addresses. Message bodies are
not logged at `INFO` — tool name, outcome, and IDs (`student_id`, `applicant_id`) are, because
access decisions need to be auditable.

---

## 14. Error Handling

| Case | Behaviour |
| ---- | --------- |
| Invalid request body | `422` |
| Bad credentials / bad token | `401`, generic message |
| Another student's or unknown application | `{"error": "not_found"}` from the tool; HTTP stays `200` |
| Unknown program | `{"error": "unknown_program"}` → agent escalates |
| Tool or LLM failure | `200`, escalation message, `ERROR` logged |
| Guardrail rejection | `200`, `status: "blocked"` |
| Unexpected | `500` with `request_id`, no stack trace to the client |

A tool failure never becomes an invented answer.

---

## 15. Configuration

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
```

Loaded through a Pydantic `Settings` object. `.env.example` is committed; `.env` is git-ignored.

---

## 16. Project Structure

```text
app/
├── controller/      auth, chat, health routes
├── dto/             request/response models
├── service/
│   ├── agent/       graph, nodes, system prompt
│   ├── tools/       the three tools
│   └── guardrails/  input guardrail
├── repository/      mock_data.py + students (SQLite)
├── constants/       escalation message, events
└── utilities/       logging, jwt, security
templates/  static/  tests/
.env.example  .gitignore  requirements.txt  README.md  SPEC.md
```

---

## 17. Tests

Seven, all deterministic, no API key required (the agent tests drive the graph with a fake chat
model):

1. The three tools return correct mock data.
2. Login works; wrong password fails; no plaintext password is stored.
3. **STUDENT-001 cannot read APP-1043** — identical payload to a nonexistent ID, and no trace of
   STUDENT-002's name, program, status, or next step.
4. **Session isolation** — two students using the same `session_id` string get separate threads.
5. **Prompt injection** is caught by the guardrail.
6. **Escalation** — when no tool applies, the exact constant message is returned and the `ESCALATE`
   token never leaks.
7. **Five-turn conversation** — the §12 script.

Test 7 also ships as `scripts/demo.py`, which runs the five turns against the real API and prints
each turn, the tool selected, and the response — the input/output log the assignment asks for.

---

## 18. Build Order

1. Mock data + SQLite students + auth (JWT, bcrypt)
2. The three tools, with the ownership check
3. LangGraph: guardrail → agent ⇄ tools → respond/escalate, `MemorySaver`
4. FastAPI routes + minimal chat UI
5. Logging
6. Tests + five-turn demo
7. README

---

## 19. Out of Scope

RAG, vector DBs, OCR, fine-tuning, multi-agent systems, real SIS/CRM integration, Kubernetes, cloud
deployment. Also deferred, and listed in the README under **Future Enhancements**: persistent
checkpointing (`SqliteSaver`) for multi-worker deploys, refresh tokens and httpOnly cookies, login
rate limiting, output-side guardrails, and a full audit trail.

---

## 20. Decisions (settled)

| Decision | Resolution |
| -------- | ---------- |
| Escalation | No fourth tool — graph outcome emitting a constant (§8) |
| `applicant_id` | Optional; resolved from the authenticated student |
| Checkpointer | `MemorySaver`, in-process |
| Business data | Mock Python dicts; SQLite for auth only |
| Tests | The seven in §17 |
| Model | `gpt-4o-mini` |
| UI token storage | In-memory JS variable |
