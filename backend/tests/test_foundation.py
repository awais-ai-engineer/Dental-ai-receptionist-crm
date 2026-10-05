from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.main import app
from app.schemas.core import AppointmentIn, AvailabilityIn


def test_root_and_health():
    with TestClient(app) as client:
        assert client.get("/").json() == {"name": "Aves AI Receptionist API", "status": "running"}
        assert client.get("/api/v1/health").json() == {"status": "ok", "service": "aves-ai-receptionist-api"}


def test_protected_endpoint_requires_auth():
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401


def test_password_hash():
    hashed = hash_password("long-test-password")
    assert hashed != "long-test-password"
    assert verify_password("long-test-password", hashed)
    assert not verify_password("wrong", hashed)


def test_rejects_naive_or_reversed_appointment_times():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(ValidationError):
        AppointmentIn(patient_id=uuid4(), doctor_id=uuid4(), scheduled_start=start.replace(tzinfo=None), scheduled_end=start + timedelta(minutes=30))
    with pytest.raises(ValidationError):
        AppointmentIn(patient_id=uuid4(), doctor_id=uuid4(), scheduled_start=start, scheduled_end=start)


def test_rejects_invalid_availability():
    with pytest.raises(ValidationError):
        AvailabilityIn(day_of_week=0, start_time="17:00", end_time="09:00")


def test_database_health_hides_connection_failure():
    class BrokenSession:
        async def execute(self, query):
            raise RuntimeError("postgresql+asyncpg://secret-user:secret-password@host/db")

    async def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health/db")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
    finally:
        app.dependency_overrides.pop(get_db, None)
