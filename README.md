# Dental-ai-receptionist-crm
Production-style AI receptionist and CRM for dental clinics with appointment scheduling, RAG-powered patient support, PostgreSQL, FastAPI, n8n automation, and human escalation

## Backend status

The backend implements authentication, clinic-scoped doctors and patients, weekly doctor availability, appointment scheduling, persistent conversations and messages, and staff-managed escalation records. AI, RAG, automations, and analytics are planned for later passes.

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

Staff use bearer authentication for `POST/GET /api/v1/conversations`, `GET/PATCH /api/v1/conversations/{id}`, `POST /api/v1/conversations/{id}/close`, and `GET/POST /api/v1/conversations/{id}/messages`. The list accepts `status`, `channel`, `patient_id`, `limit`, and `offset`. Staff messages are recorded as staff messages; this phase does not generate AI replies.

An anonymous website visitor starts a chat with `POST /api/v1/reception/conversations` and JSON `{"clinic_slug":"your-clinic-slug"}`. The response contains a conversation ID and a random access token. Send that token in `X-Conversation-Token` when calling `GET/POST /api/v1/reception/conversations/{id}/messages`. Store the token privately in the visitor session; it is shown only once, and the database stores its hash. Public callers cannot access staff conversation routes or other conversations without the matching token.

## Escalations and handoff

Staff can manage clinic-scoped escalations through `POST/GET /api/v1/escalations`, `GET/PATCH /api/v1/escalations/{id}`, and `POST /api/v1/escalations/{id}/acknowledge` or `/resolve`. Resolution requires acknowledgement first. Receptionists can resolve low and medium severity cases; admins and assigned doctors can resolve high and critical cases. Creating an escalation from a conversation marks that conversation as escalated in the same transaction. Staff can request handoff with `POST /api/v1/conversations/{id}/handoff`.

A website visitor can request human handoff with `POST /api/v1/reception/conversations/{id}/handoff` and their `X-Conversation-Token`. This only marks the conversation as waiting for staff; public callers cannot choose an assignee or access escalation records. Recipient calculation uses active clinic staff records: low/medium goes to receptionists, high adds admins, and critical adds the assigned doctor's linked staff account when present. An internal `escalation.created` payload builder prepares data for future automation; this phase sends no notifications.

Before production, add rate limiting to public conversation creation, public message reads and posts, and public handoff. Public conversation tokens currently have no expiry; add expiration and rotation as a separate security hardening change.

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
