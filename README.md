# Dental-ai-receptionist-crm
Production-style AI receptionist and CRM for dental clinics with appointment scheduling, RAG-powered patient support, PostgreSQL, FastAPI, n8n automation, and human escalation

## Backend status

The current backend pass implements authentication, clinic-scoped doctors and patients, weekly doctor availability, and appointment scheduling. AI, RAG, conversations, automations, analytics, and escalation are planned for later passes.

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
