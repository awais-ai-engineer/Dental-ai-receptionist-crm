import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import asyncpg
import pytest
from sqlalchemy import select, text

from app.models import Clinic, StaffUser

pytestmark = pytest.mark.integration
PREFIX = "/api/v1"


async def register(client, name="Clinic A", email="a@example.com"):
    response = await client.post(f"{PREFIX}/auth/register", json={"clinic_name": name, "full_name": "Clinic Admin", "email": email, "password": "strong-password-123"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def future_day():
    day = datetime.now(timezone.utc) + timedelta(days=14)
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


async def doctor_and_patient(client, headers, day=None):
    doctor = await client.post(f"{PREFIX}/doctors", headers=headers, json={"full_name": "Dr Smith", "specialization": "General Dentistry"})
    assert doctor.status_code == 201, doctor.text
    patient = await client.post(f"{PREFIX}/patients", headers=headers, json={"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com", "phone": "+15551234567"})
    assert patient.status_code == 201, patient.text
    ids = doctor.json()["id"], patient.json()["id"]
    if day is not None:
        availability = await client.post(f"{PREFIX}/doctors/{ids[0]}/availability", headers=headers, json={"day_of_week": day.weekday(), "start_time": "09:00", "end_time": "17:00"})
        assert availability.status_code == 201, availability.text
    return ids


def appointment_payload(doctor_id, patient_id, day, start_hour=10, start_minute=0, duration=60):
    start = day.replace(hour=start_hour, minute=start_minute)
    return {"doctor_id": doctor_id, "patient_id": patient_id, "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(minutes=duration)).isoformat()}


async def test_authentication_flow(api_client, db_session):
    client = api_client
    headers = await register(client)
    user = await db_session.scalar(select(StaffUser).where(StaffUser.email == "a@example.com"))
    clinic = await db_session.get(Clinic, user.clinic_id)
    assert clinic.name == "Clinic A"
    assert user.hashed_password != "strong-password-123"
    assert user.hashed_password.startswith("$argon2")
    duplicate = await client.post(f"{PREFIX}/auth/register", json={"clinic_name": "Duplicate", "full_name": "Admin", "email": "a@example.com", "password": "strong-password-123"})
    assert duplicate.status_code == 409
    login = await client.post(f"{PREFIX}/auth/login", json={"email": "a@example.com", "password": "strong-password-123"})
    assert login.status_code == 200
    assert (await client.post(f"{PREFIX}/auth/login", json={"email": "a@example.com", "password": "bad"})).status_code == 401
    me = await client.get(f"{PREFIX}/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["clinic_id"] == str(clinic.id)
    assert "hashed_password" not in me.json()
    for token in ("malformed", jwt.encode({"sub": str(user.id), "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, "integration-test-secret-only-please-change", algorithm="HS256")):
        assert (await client.get(f"{PREFIX}/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401
    assert (await client.get(f"{PREFIX}/health/db")).json() == {"status": "ok"}


async def test_doctors_patients_and_tenant_isolation(api_client):
    client = api_client
    a = await register(client)
    b = await register(client, "Clinic B", "b@example.com")
    doctor_a, patient_a = await doctor_and_patient(client, a)
    doctor_b, patient_b = await doctor_and_patient(client, b)
    for headers, own_doctor, own_patient, foreign_doctor, foreign_patient in ((a, doctor_a, patient_a, doctor_b, patient_b), (b, doctor_b, patient_b, doctor_a, patient_a)):
        doctors = (await client.get(f"{PREFIX}/doctors", headers=headers)).json()
        patients = (await client.get(f"{PREFIX}/patients", headers=headers)).json()
        assert [item["id"] for item in doctors] == [own_doctor]
        assert [item["id"] for item in patients] == [own_patient]
        for path in (f"doctors/{foreign_doctor}", f"patients/{foreign_patient}"):
            assert (await client.get(f"{PREFIX}/{path}", headers=headers)).status_code == 404
            assert (await client.patch(f"{PREFIX}/{path}", headers=headers, json={"full_name": "Intruder"} if path.startswith("doctors") else {"first_name": "Intruder"})).status_code == 404
        assert (await client.delete(f"{PREFIX}/doctors/{foreign_doctor}", headers=headers)).status_code == 404
    assert (await client.patch(f"{PREFIX}/doctors/{doctor_a}", headers=a, json={"specialization": "Orthodontics"})).json()["specialization"] == "Orthodontics"
    assert (await client.patch(f"{PREFIX}/patients/{patient_a}", headers=a, json={"first_name": "Janet"})).json()["first_name"] == "Janet"
    for search in ("Janet", "jane@example.com", "+15551234567"):
        assert len((await client.get(f"{PREFIX}/patients", headers=a, params={"search": search})).json()) == 1
    assert len((await client.get(f"{PREFIX}/patients", headers=a, params={"limit": 1, "offset": 1})).json()) == 0
    assert (await client.delete(f"{PREFIX}/doctors/{doctor_a}", headers=a)).status_code == 204
    assert (await client.get(f"{PREFIX}/doctors/{doctor_a}", headers=a)).json()["is_active"] is False


async def test_availability_and_appointments(api_client):
    client = api_client
    headers = await register(client)
    day = future_day()
    doctor, patient = await doctor_and_patient(client, headers, day)
    url = f"{PREFIX}/doctors/{doctor}/availability"
    assert len((await client.get(url, headers=headers)).json()) == 1
    assert (await client.post(url, headers=headers, json={"day_of_week": day.weekday(), "start_time": "10:00", "end_time": "12:00"})).status_code == 409
    assert (await client.post(url, headers=headers, json={"day_of_week": day.weekday(), "start_time": "18:00", "end_time": "09:00"})).status_code == 422
    payload = appointment_payload(doctor, patient, day)
    for change, expected in (({"doctor_id": str(uuid4())}, 404), ({"patient_id": str(uuid4())}, 404), ({"scheduled_end": payload["scheduled_start"]}, 422), ({"scheduled_start": day.replace(hour=8).isoformat(), "scheduled_end": day.replace(hour=9).isoformat()}, 409)):
        assert (await client.post(f"{PREFIX}/appointments", headers=headers, json={**payload, **change})).status_code == expected
    created = await client.post(f"{PREFIX}/appointments", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]
    assert (await client.get(f"{PREFIX}/appointments/{appointment_id}", headers=headers)).status_code == 200
    assert len((await client.get(f"{PREFIX}/appointments", headers=headers)).json()) == 1
    slots = (await client.get(f"{PREFIX}/doctors/{doctor}/available-slots", headers=headers, params={"date": day.date().isoformat(), "duration_minutes": 30})).json()
    assert day.replace(hour=10).isoformat().replace("+00:00", "Z") not in slots
    assert (await client.get(f"{PREFIX}/doctors/{doctor}/available-slots", headers=headers, params={"date": day.date().isoformat(), "duration_minutes": 0})).status_code == 422
    assert (await client.post(f"{PREFIX}/appointments/{appointment_id}/approve", headers=headers)).json()["status"] == "approved"
    assert (await client.post(f"{PREFIX}/appointments/{appointment_id}/confirm", headers=headers)).json()["status"] == "confirmed"
    assert (await client.post(f"{PREFIX}/appointments/{appointment_id}/reschedule", headers=headers, json={"scheduled_start": day.replace(hour=11).isoformat(), "scheduled_end": day.replace(hour=12).isoformat()})).json()["status"] == "requested"
    assert (await client.post(f"{PREFIX}/appointments/{appointment_id}/cancel", headers=headers)).json()["status"] == "cancelled"
    assert (await client.post(f"{PREFIX}/appointments", headers=headers, json=appointment_payload(doctor, patient, day, 11))).status_code == 201


async def test_overlap_patterns_and_concurrent_booking(api_client, db_session):
    client = api_client
    headers = await register(client)
    day = future_day()
    doctor, patient = await doctor_and_patient(client, headers, day)
    base = f"{PREFIX}/appointments"
    assert (await client.post(base, headers=headers, json=appointment_payload(doctor, patient, day))).status_code == 201
    for hour, minute, duration in ((10, 0, 60), (10, 15, 30), (9, 30, 60), (10, 30, 60)):
        assert (await client.post(base, headers=headers, json=appointment_payload(doctor, patient, day, hour, minute, duration))).status_code == 409
    for hour in (9, 11):
        assert (await client.post(base, headers=headers, json=appointment_payload(doctor, patient, day, hour))).status_code == 201
    concurrent_payload = appointment_payload(doctor, patient, day, 13)
    responses = await asyncio.gather(*(client.post(base, headers=headers, json=concurrent_payload) for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert all("IntegrityError" not in response.text and "asyncpg" not in response.text for response in responses)
    constraint = await db_session.execute(text("SELECT conname FROM pg_constraint WHERE conname = 'appointments_no_doctor_overlap'"))
    assert constraint.scalar_one() == "appointments_no_doctor_overlap"


async def test_cross_clinic_appointment_isolation(api_client):
    client = api_client
    a = await register(client)
    b = await register(client, "Clinic B", "b@example.com")
    day = future_day()
    doctor_a, patient_a = await doctor_and_patient(client, a, day)
    doctor_b, patient_b = await doctor_and_patient(client, b, day)
    appointment_a = (await client.post(f"{PREFIX}/appointments", headers=a, json=appointment_payload(doctor_a, patient_a, day))).json()["id"]
    appointment_b = (await client.post(f"{PREFIX}/appointments", headers=b, json=appointment_payload(doctor_b, patient_b, day))).json()["id"]
    for headers, own, foreign in ((a, appointment_a, appointment_b), (b, appointment_b, appointment_a)):
        assert [item["id"] for item in (await client.get(f"{PREFIX}/appointments", headers=headers)).json()] == [own]
        assert (await client.get(f"{PREFIX}/appointments/{foreign}", headers=headers)).status_code == 404
        assert (await client.patch(f"{PREFIX}/appointments/{foreign}", headers=headers, json={"notes": "Intruder"})).status_code == 404
        assert (await client.post(f"{PREFIX}/appointments/{foreign}/cancel", headers=headers)).status_code == 404
    assert (await client.post(f"{PREFIX}/appointments", headers=a, json=appointment_payload(doctor_b, patient_a, day))).status_code == 404
    assert (await client.post(f"{PREFIX}/appointments", headers=a, json=appointment_payload(doctor_a, patient_b, day))).status_code == 404


async def test_available_slots_reflect_status_and_schedule(api_client):
    client = api_client
    headers = await register(client)
    day = future_day()
    doctor, patient = await doctor_and_patient(client, headers)
    url = f"{PREFIX}/doctors/{doctor}/available-slots"
    params = {"date": day.date().isoformat(), "duration_minutes": 30}
    assert (await client.get(url, headers=headers, params=params)).json() == []
    added = await client.post(f"{PREFIX}/doctors/{doctor}/availability", headers=headers, json={"day_of_week": day.weekday(), "start_time": "09:00", "end_time": "17:00"})
    assert added.status_code == 201
    initial = (await client.get(url, headers=headers, params=params)).json()
    assert len(initial) == 16
    appointment = await client.post(f"{PREFIX}/appointments", headers=headers, json=appointment_payload(doctor, patient, day, 10, 0, 30))
    assert appointment.status_code == 201
    booked = (await client.get(url, headers=headers, params=params)).json()
    assert len(booked) == 15
    assert day.replace(hour=9, minute=30).isoformat().replace("+00:00", "Z") in booked
    assert day.replace(hour=10, minute=30).isoformat().replace("+00:00", "Z") in booked
    assert (await client.post(f"{PREFIX}/appointments/{appointment.json()['id']}/cancel", headers=headers)).status_code == 200
    assert len((await client.get(url, headers=headers, params=params)).json()) == 16
    assert (await client.delete(f"{PREFIX}/doctors/{doctor}", headers=headers)).status_code == 204
    assert (await client.get(url, headers=headers, params=params)).json() == []


async def test_database_exclusion_blocks_concurrent_inserts(api_client):
    client = api_client
    headers = await register(client)
    day = future_day()
    doctor, patient = await doctor_and_patient(client, headers, day)
    clinic_id = (await client.get(f"{PREFIX}/auth/me", headers=headers)).json()["clinic_id"]
    dsn = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    first, second = await asyncio.gather(asyncpg.connect(dsn), asyncpg.connect(dsn))
    insert = """INSERT INTO appointments
        (id, clinic_id, doctor_id, patient_id, scheduled_start, scheduled_end, status, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, 'requested', now(), now())"""
    from uuid import UUID

    values = (UUID(clinic_id), UUID(doctor), UUID(patient), day.replace(hour=14), day.replace(hour=15))
    transaction_a = first.transaction()
    transaction_b = second.transaction()
    try:
        await transaction_a.start()
        await first.execute(insert, uuid4(), *values)
        await transaction_b.start()
        conflicting_insert = asyncio.create_task(second.execute(insert, uuid4(), *values))
        await asyncio.sleep(0.1)
        assert not conflicting_insert.done()
        await transaction_a.commit()
        with pytest.raises(asyncpg.exceptions.ExclusionViolationError):
            await conflicting_insert
        await transaction_b.rollback()
    finally:
        await asyncio.gather(first.close(), second.close())
