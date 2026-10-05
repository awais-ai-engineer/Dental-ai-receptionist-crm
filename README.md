# Dental-ai-receptionist-crm
Production-style AI receptionist and CRM for dental clinics with appointment scheduling, RAG-powered patient support, PostgreSQL, FastAPI, n8n automation, and human escalation

## Backend status

The backend implements authentication, clinic-scoped doctors and patients, weekly doctor availability, appointment scheduling, conversations, escalations, and a PostgreSQL/pgvector knowledge store with grounded AI answers. Automations and analytics are planned for later passes.

## Local setup (PowerShell)

Install Python 3.12 and Docker Desktop. The development Compose file runs PostgreSQL 16 with pgvector:

```powershell
docker compose up -d db
```

The container exposes port 5432 and uses the development-only database `aves`, user `aves`, and password `aves_dev_password`. If 5432 is occupied, set `$env:AVES_DB_PORT="5433"` before `docker compose up -d db` and use port 5433 in your URLs. You can instead use your own PostgreSQL server with the `vector` and `btree_gist` extensions available.

Set up Python:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item .env.example .env
```

Edit `.env`: set `DATABASE_URL` to your PostgreSQL URL, set a unique random `JWT_SECRET_KEY` of at least 32 characters, and change other settings as needed. Keep `.env` private. Then run:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

The API documentation is at `http://localhost:8000/docs`. In another terminal, run tests with `python -m pytest` from `backend/`.

The application does not create tables at startup; Alembic owns schema changes. `GET /api/v1/health` checks the API and `GET /api/v1/health/db` checks database connectivity.

## Conversations

Staff use bearer authentication for `POST/GET /api/v1/conversations`, `GET/PATCH /api/v1/conversations/{id}`, `POST /api/v1/conversations/{id}/close`, and `GET/POST /api/v1/conversations/{id}/messages`. The list accepts `status`, `channel`, `patient_id`, `limit`, and `offset`. Staff messages are recorded as staff messages. The separate `/ask` route generates grounded replies.

An anonymous website visitor starts a chat with `POST /api/v1/reception/conversations` and JSON `{"clinic_slug":"your-clinic-slug"}`. The response contains a conversation ID and a random access token. Send that token in `X-Conversation-Token` when calling `GET/POST /api/v1/reception/conversations/{id}/messages`. Store the token privately in the visitor session; it is shown only once, and the database stores its hash. Public callers cannot access staff conversation routes or other conversations without the matching token.

## Escalations and handoff

Staff can manage clinic-scoped escalations through `POST/GET /api/v1/escalations`, `GET/PATCH /api/v1/escalations/{id}`, and `POST /api/v1/escalations/{id}/acknowledge` or `/resolve`. Resolution requires acknowledgement first. Receptionists can resolve low and medium severity cases; admins and assigned doctors can resolve high and critical cases. Creating an escalation from a conversation marks that conversation as escalated in the same transaction. Staff can request handoff with `POST /api/v1/conversations/{id}/handoff`.

A website visitor can request human handoff with `POST /api/v1/reception/conversations/{id}/handoff` and their `X-Conversation-Token`. This only marks the conversation as waiting for staff; public callers cannot choose an assignee or access escalation records. Recipient calculation uses active clinic staff records: low/medium goes to receptionists, high adds admins, and critical adds the assigned doctor's linked staff account when present. An internal `escalation.created` payload builder prepares data for future automation; this phase sends no notifications.

Before production, add rate limiting to public conversation creation, public message reads and posts, and public handoff. Public conversation tokens currently have no expiry; add expiration and rotation as a separate security hardening change.

## Knowledge base and vectors

Authenticated staff use `POST/GET /api/v1/knowledge/documents`, `GET/PATCH/DELETE /api/v1/knowledge/documents/{id}`, and `GET /api/v1/knowledge/documents/{id}/chunks`. A create request accepts `title`, `source_type` (`manual`, `faq`, or `text`), and `content`. Text is normalized, split into ordered overlapping chunks, and stored in PostgreSQL. Documents remain `pending` until processing supplies real vectors; the API does not invent embeddings or mark pending documents searchable. Deleting a document cascades to its chunks.

The storage and search services use pgvector with clinic filtering and exact cosine distance. No approximate index is installed for the small demo dataset. `EMBEDDING_DIMENSION` defaults to 1536, matching migration `0004_knowledge_base`. Changing it requires a new schema migration. Unit and PostgreSQL tests inject deterministic vectors without paid API calls. `KNOWLEDGE_CHUNK_SIZE` and `KNOWLEDGE_CHUNK_OVERLAP` control chunking.

## Embeddings and grounded answers

Set `EMBEDDING_PROVIDER=openrouter`, `EMBEDDING_MODEL` to an OpenRouter embedding model that supports 1536 dimensions, and `EMBEDDING_API_KEY` to its key. If `EMBEDDING_API_KEY` is empty, the adapter uses `LLM_API_KEY`. Set `LLM_PROVIDER=openrouter`, `LLM_MODEL` to a chat model, and `LLM_API_KEY` to an OpenRouter key. Keep keys in `.env`. No network call is made at startup. Missing settings return HTTP 503. Provider errors use safe messages without response bodies or credentials.

An admin or receptionist can process one document with `POST /api/v1/knowledge/documents/{id}/process`, or all pending and failed documents with `POST /api/v1/knowledge/documents/process-pending`. Processing moves through `processing` to `ready`, or `failed` with an error message. A failed document can be retried. A ready document is returned without another embedding call. After seeding the demo documents, call `process-pending` with the staff bearer token to make them searchable.

Staff can ask `POST /api/v1/knowledge/query` with `{"question":"What are your opening hours?"}`. A website visitor can ask `POST /api/v1/reception/conversations/{id}/ask` with `{"content":"What are your opening hours?"}` and their `X-Conversation-Token`. The public route persists the patient message first; on a successful answer it persists an AI reply and returns sources with actual document and chunk IDs. Provider failure leaves the patient message for staff review and does not create an AI reply. Explicit emergency phrases request handoff and return an urgent contact message without diagnosis. This phrase rule is narrow and is not a clinical triage classifier.

Retrieval only uses ready documents from the current clinic. `RAG_TOP_K` defaults to 5 and `RAG_MAX_DISTANCE` to 0.45 cosine distance. When nothing passes the threshold, the service returns a fixed staff referral without calling the chat provider. Answers receive a grounding prompt, but model output is probabilistic; a human should review any public deployment, especially pricing or medical questions. This endpoint does not create bookings or make clinical decisions.

## Controlled AI receptionist tools

`POST /api/v1/reception/conversations/{id}/message` accepts `{"message":"..."}` with the conversation's `X-Conversation-Token`. It stores the patient message once, runs a bounded tool-selection flow, stores one final AI response on success, and returns the response plus safe action metadata. The existing `/ask` route remains the knowledge-only RAG endpoint.

The model receives schemas for eight allowlisted tools: clinic knowledge search, active doctor listing, available-slot search, appointment request creation, rescheduling, cancellation, human handoff, and escalation. Tool decisions are strict JSON validated with Pydantic. Unknown names, extra fields such as `clinic_id`, malformed arguments, and more than three tool steps are rejected or stopped. No SQL, dynamic imports, `eval`, or direct model database access is available.

Trusted `clinic_id`, `conversation_id`, and linked `patient_id` values come from the token-validated conversation. Appointment changes require that linked patient and query by both clinic and patient. Booking and rescheduling reuse the appointment service and scheduling validation, including availability and overlap checks. AI-created bookings use `requested`; patient-facing wording says clinic confirmation is still required. Vague reschedule requests and booking requests without a preferred date or time do not mutate data. Public patient creation is intentionally absent; staff must link a verified patient record before appointment changes.

Handoff reuses the conversation service and never accepts a staff assignee. Escalations reuse the escalation service entry point for public AI requests and cannot accept patient, clinic, staff, source, or assignment fields from the model. A narrow explicit-phrase emergency rule can raise severity, but it does not diagnose. Tool logs contain the tool name, conversation ID, clinic ID, and outcome without full message content or credentials.

To optionally load fictional Aves Dental Clinic hours, doctors, pricing, and policies, first register that clinic and find its slug in the database. Then run from `backend/`:

```powershell
python -m app.demo.aves_knowledge --clinic-slug your-aves-clinic-slug
```

The seed is idempotent and creates pending documents only for a clinic named `Aves Dental Clinic`. It does not run at startup. Demo prices are fictional estimates, not clinical advice.

## PostgreSQL integration tests

Create a separate test database once:

```powershell
docker compose exec db psql -U aves -d postgres -c 'CREATE DATABASE aves_test'
```

From `backend/`, set the test URL and run all tests:

```powershell
$env:DEBUG="false"
$env:TEST_DATABASE_URL="postgresql+asyncpg://aves:aves_dev_password@localhost:5432/aves_test"
python -m pytest -q
```

The integration fixture applies Alembic to `aves_test` and clears its CRM tables between tests. It refuses a URL whose database name does not end in `_test`. Without `TEST_DATABASE_URL`, integration tests are skipped. If your Windows shell has `DEBUG=release`, set `$env:DEBUG="false"` before starting the API or running Alembic; `DEBUG` accepts a boolean value.
