import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


TEST_URL = os.getenv("TEST_DATABASE_URL")
if TEST_URL:
    url = make_url(TEST_URL)
    if url.drivername != "postgresql+asyncpg" or not url.database or not url.database.endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must use postgresql+asyncpg and a database ending in _test")
    if os.getenv("DATABASE_URL") == TEST_URL:
        raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ["JWT_SECRET_KEY"] = "integration-test-secret-only-please-change"


@pytest.fixture(scope="session")
def migrated_database():
    if not TEST_URL:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    yield


@pytest.fixture
async def api_client(migrated_database):
    from app.db.session import session_factory
    from app.main import app

    engine = create_async_engine(TEST_URL)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE escalations, messages, conversations, appointments, doctor_availability, patients, doctors, staff_users, clinics CASCADE"))
    await engine.dispose()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    engine = create_async_engine(TEST_URL)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE escalations, messages, conversations, appointments, doctor_availability, patients, doctors, staff_users, clinics CASCADE"))
    await engine.dispose()
    await session_factory().kw["bind"].dispose()
    session_factory.cache_clear()


@pytest.fixture
async def db_session(migrated_database):
    from app.db.session import session_factory

    async with session_factory()() as session:
        yield session
