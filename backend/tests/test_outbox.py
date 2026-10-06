import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import session_factory
from app.main import app
from app.models import Appointment, Clinic, OutboxEvent, StaffUser
from app.services.outbox import process_outbox, queue_event, serialize_envelope, sign_webhook
from app.services.providers import get_embedding_client, get_llm_client

pytestmark = pytest.mark.integration
PREFIX = "/api/v1"


class FakeWebhook:
    def __init__(self, status=204, error=None, gate=None):
        self.status = status
        self.error = error
        self.gate = gate
        self.calls = []

    async def post(self, url, *, content, headers, timeout):
        self.calls.append((url, content, headers, timeout))
        if self.gate:
            await self.gate.wait()
        if self.error:
            raise self.error
        return SimpleNamespace(status_code=self.status)


class FakeEmbeddings:
    async def embed_texts(self, texts):
        return [[1.0] + [0.0] * 1535 for _ in texts]


class QueueLLM:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    async def complete(self, messages):
        return json.dumps(self.decisions.pop(0))


async def register(client, name, email):
    response = await client.post(f"{PREFIX}/auth/register", json={"clinic_name": name, "full_name": "Admin", "email": email, "password": "strong-password-123"})
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = (await client.get(f"{PREFIX}/auth/me", headers=headers)).json()
    return headers, me


async def scheduling_records(client, headers, day):
    patient = (await client.post(f"{PREFIX}/patients", headers=headers, json={"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com", "phone": "+15551230000"})).json()
    doctor = (await client.post(f"{PREFIX}/doctors", headers=headers, json={"full_name": "Dr Sara", "consultation_duration_minutes": 30})).json()
    response = await client.post(f"{PREFIX}/doctors/{doctor['id']}/availability", headers=headers, json={"day_of_week": day.weekday(), "start_time": "09:00", "end_time": "17:00"})
    assert response.status_code == 201
    return patient, doctor


def appointment_payload(patient, doctor, start):
    return {"patient_id": patient["id"], "doctor_id": doctor["id"], "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(minutes=30)).isoformat()}


async def event_types(db):
    return (await db.scalars(select(OutboxEvent.event_type).order_by(OutboxEvent.created_at, OutboxEvent.id))).all()


async def test_patient_and_staff_appointment_events_are_atomic_and_explicit(api_client, db_session):
    headers, admin = await register(api_client, "Clinic A", "events@example.com")
    receptionist = StaffUser(clinic_id=UUID(admin["clinic_id"]), email="frontdesk-events@example.com", full_name="Front Desk", hashed_password=hash_password("strong-password-123"), role="receptionist")
    db_session.add(receptionist)
    await db_session.commit()
    day = (datetime.now(timezone.utc) + timedelta(days=12)).date()
    patient, doctor = await scheduling_records(api_client, headers, day)
    start = datetime.combine(day, datetime.min.time(), timezone.utc).replace(hour=10)
    created = await api_client.post(f"{PREFIX}/appointments", headers=headers, json=appointment_payload(patient, doctor, start))
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]
    await api_client.post(f"{PREFIX}/appointments/{appointment_id}/approve", headers=headers)
    await api_client.post(f"{PREFIX}/appointments/{appointment_id}/confirm", headers=headers)
    await api_client.post(f"{PREFIX}/appointments/{appointment_id}/reschedule", headers=headers, json={"scheduled_start": start.replace(hour=11).isoformat(), "scheduled_end": start.replace(hour=11, minute=30).isoformat()})
    await api_client.post(f"{PREFIX}/appointments/{appointment_id}/cancel", headers=headers)
    assert await event_types(db_session) == ["patient.created", "appointment.requested", "appointment.approved", "appointment.confirmed", "appointment.rescheduled", "appointment.cancelled"]
    requested = await db_session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "appointment.requested"))
    assert requested.aggregate_id == UUID(appointment_id)
    assert requested.payload["patient_email"] == "jane@example.com" and requested.payload["doctor_name"] == "Dr Sara"
    assert requested.payload["recipients"] == [{"staff_user_id": str(receptionist.id), "role": "receptionist", "email": receptionist.email}]
    assert "password" not in json.dumps(requested.payload).lower()
    failed = await api_client.post(f"{PREFIX}/appointments", headers=headers, json=appointment_payload(patient, doctor, start.replace(hour=8)))
    assert failed.status_code == 409
    assert await db_session.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.event_type == "appointment.requested")) == 1


async def test_ai_appointment_uses_same_outbox_event(api_client, db_session):
    headers, admin = await register(api_client, "Clinic A", "ai-events@example.com")
    clinic_id = UUID(admin["clinic_id"])
    day = (datetime.now(timezone.utc) + timedelta(days=13)).date()
    patient, doctor = await scheduling_records(api_client, headers, day)
    clinic = await db_session.get(Clinic, clinic_id)
    started = (await api_client.post(f"{PREFIX}/reception/conversations", json={"clinic_slug": clinic.slug})).json()
    await api_client.patch(f"{PREFIX}/conversations/{started['conversation_id']}", headers=headers, json={"patient_id": patient["id"]})
    start = datetime.combine(day, datetime.min.time(), timezone.utc).replace(hour=15)
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddings()
    app.dependency_overrides[get_llm_client] = lambda: QueueLLM([{"tool": "create_appointment_request", "arguments": {"doctor_id": doctor["id"], "start_time": start.isoformat(), "duration_minutes": 30}}])
    try:
        response = await api_client.post(f"{PREFIX}/reception/conversations/{started['conversation_id']}/message", headers={"X-Conversation-Token": started["access_token"]}, json={"message": "Please book the 3 PM appointment."})
        assert response.status_code == 200, response.text
    finally:
        app.dependency_overrides.clear()
    events = (await db_session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "appointment.requested"))).all()
    assert len(events) == 1
    appointment = await db_session.get(Appointment, events[0].aggregate_id)
    assert appointment.status == "requested" and appointment.source == "ai_receptionist"


async def test_handoff_and_escalation_lifecycle_events(api_client, db_session):
    headers, _ = await register(api_client, "Clinic A", "escalation-events@example.com")
    patient = (await api_client.post(f"{PREFIX}/patients", headers=headers, json={"first_name": "Jane", "last_name": "Doe"})).json()
    conversation = (await api_client.post(f"{PREFIX}/conversations", headers=headers, json={"channel": "manual", "patient_id": patient["id"]})).json()
    assert (await api_client.post(f"{PREFIX}/conversations/{conversation['id']}/handoff", headers=headers)).status_code == 200
    escalation = (await api_client.post(f"{PREFIX}/escalations", headers=headers, json={"conversation_id": conversation["id"], "severity": "high", "reason": "Urgent staff review"})).json()
    await api_client.post(f"{PREFIX}/escalations/{escalation['id']}/acknowledge", headers=headers)
    await api_client.post(f"{PREFIX}/escalations/{escalation['id']}/resolve", headers=headers)
    types = await event_types(db_session)
    assert types == ["patient.created", "conversation.handoff_requested", "escalation.created", "escalation.acknowledged", "escalation.resolved"]
    created = await db_session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "escalation.created"))
    assert {recipient["role"] for recipient in created.payload["recipients"]} == {"admin"}


async def test_signing_delivery_retries_cap_and_disabled_mode(api_client, db_session, monkeypatch):
    headers, admin = await register(api_client, "Clinic A", "delivery@example.com")
    clinic_id = UUID(admin["clinic_id"])
    event = queue_event(db_session, clinic_id, "patient.created", "patient", None, {"patient_id": "safe"})
    await db_session.commit()
    await db_session.refresh(event)
    body = serialize_envelope(event)
    timestamp = "2026-10-06T12:00:00Z"
    expected = hmac.new(b"test-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert sign_webhook("test-secret", timestamp, body) == expected
    assert b"test-secret" not in body
    with monkeypatch.context() as patch:
        patch.setenv("N8N_WEBHOOK_ENABLED", "false")
        get_settings.cache_clear()
        assert await process_outbox(db_session, FakeWebhook()) == []
        assert (await db_session.get(OutboxEvent, event.id)).status == "pending"
    with monkeypatch.context() as patch:
        patch.setenv("N8N_WEBHOOK_ENABLED", "true")
        patch.setenv("N8N_WEBHOOK_URL", "https://n8n.example.test/aves-backend-events")
        patch.setenv("N8N_WEBHOOK_SECRET", "test-secret")
        patch.setenv("OUTBOX_MAX_ATTEMPTS", "2")
        get_settings.cache_clear()
        timeout_client = FakeWebhook(error=httpx.ReadTimeout("timeout"))
        await process_outbox(db_session, timeout_client)
        await db_session.refresh(event)
        first_id = event.id
        assert event.status == "failed" and event.attempt_count == 1 and event.last_error == "Webhook timed out"
        assert 25 <= (event.next_attempt_at - event.last_attempt_at).total_seconds() <= 35
        event.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.commit()
        server_error = FakeWebhook(status=500)
        await process_outbox(db_session, server_error)
        await db_session.refresh(event)
        assert event.id == first_id and event.status == "failed" and event.attempt_count == 2
        assert event.next_attempt_at is None and event.last_error == "Webhook returned HTTP 500"
        assert await process_outbox(db_session, server_error) == []
    get_settings.cache_clear()


async def test_success_monitoring_tenant_isolation_and_manual_retry(api_client, db_session, monkeypatch):
    a, admin_a = await register(api_client, "Clinic A", "monitor-a@example.com")
    b, admin_b = await register(api_client, "Clinic B", "monitor-b@example.com")
    event_a = queue_event(db_session, UUID(admin_a["clinic_id"]), "patient.created", "patient", None, {"patient_id": "a"})
    event_b = queue_event(db_session, UUID(admin_b["clinic_id"]), "patient.created", "patient", None, {"patient_id": "b"})
    await db_session.commit()
    with monkeypatch.context() as patch:
        patch.setenv("N8N_WEBHOOK_ENABLED", "true")
        patch.setenv("N8N_WEBHOOK_URL", "https://n8n.example.test/aves-backend-events")
        patch.setenv("N8N_WEBHOOK_SECRET", "test-secret")
        get_settings.cache_clear()
        client = FakeWebhook(status=202)
        delivered = await process_outbox(db_session, client, clinic_id=UUID(admin_a["clinic_id"]))
        assert [e.id for e in delivered] == [event_a.id] and delivered[0].status == "delivered"
        assert client.calls[0][2]["X-Aves-Event-ID"] == str(event_a.id)
    get_settings.cache_clear()
    listed = (await api_client.get(f"{PREFIX}/outbox", headers=a)).json()
    assert {item["id"] for item in listed} == {str(event_a.id)}
    assert (await api_client.get(f"{PREFIX}/outbox/{event_b.id}", headers=a)).status_code == 404
    assert (await api_client.post(f"{PREFIX}/outbox/{event_a.id}/retry", headers=a)).status_code == 409
    event_b.status, event_b.last_error = "failed", "Webhook timed out"
    await db_session.commit()
    receptionist = StaffUser(clinic_id=UUID(admin_b["clinic_id"]), email="receptionist@example.com", full_name="Receptionist", hashed_password=hash_password("strong-password-123"), role="receptionist")
    db_session.add(receptionist)
    await db_session.commit()
    receptionist_headers = {"Authorization": f"Bearer {create_access_token(receptionist.id)}"}
    assert (await api_client.post(f"{PREFIX}/outbox/{event_b.id}/retry", headers=receptionist_headers)).status_code == 403
    retried = await api_client.post(f"{PREFIX}/outbox/{event_b.id}/retry", headers=b)
    assert retried.status_code == 200 and retried.json()["id"] == str(event_b.id) and retried.json()["status"] == "pending"


async def test_concurrent_workers_claim_event_once(api_client, db_session, monkeypatch):
    headers, admin = await register(api_client, "Clinic A", "concurrency@example.com")
    event = queue_event(db_session, UUID(admin["clinic_id"]), "patient.created", "patient", None, {"patient_id": "one"})
    await db_session.commit()
    with monkeypatch.context() as patch:
        patch.setenv("N8N_WEBHOOK_ENABLED", "true")
        patch.setenv("N8N_WEBHOOK_URL", "https://n8n.example.test/aves-backend-events")
        patch.setenv("N8N_WEBHOOK_SECRET", "test-secret")
        get_settings.cache_clear()
        first = FakeWebhook(status=204)
        second = FakeWebhook(status=204)
        factory = session_factory()
        async with factory() as session_one, factory() as session_two:
            results = await asyncio.gather(process_outbox(session_one, first, limit=1), process_outbox(session_two, second, limit=1))
        assert sorted(len(result) for result in results) == [0, 1]
        assert len(first.calls) + len(second.calls) == 1
    get_settings.cache_clear()
