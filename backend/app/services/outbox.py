import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Appointment, Clinic, Doctor, Escalation, OutboxEvent, Patient, StaffUser
from app.services.escalations import escalation_created_payload

log = logging.getLogger(__name__)
BACKOFF_SECONDS = (30, 60, 120, 300, 900)


class WebhookResponse(Protocol):
    status_code: int


class WebhookClient(Protocol):
    async def post(self, url: str, *, content: bytes, headers: dict[str, str], timeout: float) -> WebhookResponse: ...


class HttpxWebhookClient:
    async def post(self, url: str, *, content: bytes, headers: dict[str, str], timeout: float):
        async with httpx.AsyncClient() as client:
            return await client.post(url, content=content, headers=headers, timeout=timeout)


def get_webhook_client() -> WebhookClient:
    return HttpxWebhookClient()


def queue_event(db: AsyncSession, clinic_id: UUID, event_type: str, aggregate_type: str,
                aggregate_id: UUID | None, payload: dict) -> OutboxEvent:
    event = OutboxEvent(clinic_id=clinic_id, event_type=event_type, aggregate_type=aggregate_type,
                        aggregate_id=aggregate_id, payload=payload, status="pending", attempt_count=0,
                        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db.add(event)
    return event


def patient_data(patient: Patient) -> dict:
    return {"patient_id": str(patient.id), "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
            "patient_email": patient.email, "patient_phone": patient.phone}


async def queue_patient_created(db: AsyncSession, patient: Patient) -> OutboxEvent:
    return queue_event(db, patient.clinic_id, "patient.created", "patient", patient.id, patient_data(patient))


async def appointment_data(db: AsyncSession, item: Appointment) -> dict:
    patient = await db.scalar(select(Patient).where(Patient.id == item.patient_id, Patient.clinic_id == item.clinic_id))
    doctor = await db.scalar(select(Doctor).where(Doctor.id == item.doctor_id, Doctor.clinic_id == item.clinic_id))
    return {"appointment_id": str(item.id), **patient_data(patient), "doctor_id": str(doctor.id), "doctor_name": doctor.full_name,
            "start_time": item.scheduled_start.isoformat(), "end_time": item.scheduled_end.isoformat(), "status": item.status}


async def queue_appointment_event(db: AsyncSession, item: Appointment, event_type: str, **extra) -> OutboxEvent:
    data = await appointment_data(db, item)
    if event_type == "appointment.requested":
        data["recipients"] = await receptionist_recipients(db, item.clinic_id)
    data.update(extra)
    return queue_event(db, item.clinic_id, event_type, "appointment", item.id, data)


async def queue_handoff_event(db: AsyncSession, conversation, source: str = "patient") -> OutboxEvent:
    data = {"conversation_id": str(conversation.id), "patient_id": str(conversation.patient_id) if conversation.patient_id else None,
            "source": source, "status": conversation.status, "recipients": await receptionist_recipients(db, conversation.clinic_id)}
    return queue_event(db, conversation.clinic_id, "conversation.handoff_requested", "conversation", conversation.id, data)


async def receptionist_recipients(db: AsyncSession, clinic_id: UUID) -> list[dict]:
    users = (await db.scalars(select(StaffUser).where(StaffUser.clinic_id == clinic_id, StaffUser.role == "receptionist", StaffUser.is_active).order_by(StaffUser.email))).all()
    return [{"staff_user_id": str(user.id), "role": user.role, "email": user.email} for user in users]


async def queue_escalation_event(db: AsyncSession, item: Escalation, event_type: str) -> OutboxEvent:
    if event_type == "escalation.created":
        data = (await escalation_created_payload(db, item))["data"]
    else:
        data = {"escalation_id": str(item.id), "severity": item.severity, "status": item.status,
                "conversation_id": str(item.conversation_id) if item.conversation_id else None}
    return queue_event(db, item.clinic_id, event_type, "escalation", item.id, data)


def event_envelope(event: OutboxEvent) -> dict:
    return {"event": event.event_type, "event_id": str(event.id), "clinic_id": str(event.clinic_id),
            "timestamp": event.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "data": event.payload}


def serialize_envelope(event: OutboxEvent) -> bytes:
    return json.dumps(event_envelope(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_webhook(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=BACKOFF_SECONDS[min(max(attempt, 1), len(BACKOFF_SECONDS)) - 1])


def safe_error(exc: Exception | None = None, status_code: int | None = None) -> str:
    if status_code is not None:
        return f"Webhook returned HTTP {status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "Webhook timed out"
    return "Webhook request failed"


async def process_outbox(db: AsyncSession, client: WebhookClient, limit: int = 20, clinic_id: UUID | None = None) -> list[OutboxEvent]:
    settings = get_settings()
    if not settings.n8n_webhook_enabled:
        return []
    if not settings.n8n_webhook_url or not settings.n8n_webhook_secret:
        raise RuntimeError("n8n webhook is enabled but not configured")
    now = datetime.now(timezone.utc)
    query = select(OutboxEvent).where(
        OutboxEvent.status.in_(("pending", "failed")), OutboxEvent.attempt_count < settings.outbox_max_attempts,
        or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now))
    if clinic_id is not None:
        query = query.where(OutboxEvent.clinic_id == clinic_id)
    events = (await db.scalars(query.order_by(OutboxEvent.created_at, OutboxEvent.id).limit(limit).with_for_update(skip_locked=True))).all()
    for event in events:
        event.status = "processing"
        event.attempt_count += 1
        event.last_attempt_at = now
        await db.flush()
        body = serialize_envelope(event)
        timestamp = now.isoformat().replace("+00:00", "Z")
        headers = {"Content-Type": "application/json", "X-Aves-Event-ID": str(event.id), "X-Aves-Timestamp": timestamp,
                   "X-Aves-Signature": sign_webhook(settings.n8n_webhook_secret, timestamp, body)}
        try:
            response = await client.post(settings.n8n_webhook_url, content=body, headers=headers, timeout=settings.n8n_webhook_timeout_seconds)
            if not 200 <= response.status_code < 300:
                raise WebhookStatusError(response.status_code)
        except Exception as exc:
            status_code = exc.status_code if isinstance(exc, WebhookStatusError) else None
            event.status = "failed"
            event.last_error = safe_error(exc, status_code)[:500]
            event.next_attempt_at = now + retry_delay(event.attempt_count) if event.attempt_count < settings.outbox_max_attempts else None
            log.warning("outbox_delivery event_id=%s event_type=%s clinic_id=%s attempt=%s success=false", event.id, event.event_type, event.clinic_id, event.attempt_count)
        else:
            event.status = "delivered"
            event.delivered_at = now
            event.next_attempt_at = None
            event.last_error = None
            log.info("outbox_delivery event_id=%s event_type=%s clinic_id=%s attempt=%s success=true", event.id, event.event_type, event.clinic_id, event.attempt_count)
    await db.commit()
    return events


class WebhookStatusError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code


async def retry_event(db: AsyncSession, event: OutboxEvent) -> OutboxEvent:
    if event.status == "delivered":
        from fastapi import HTTPException
        raise HTTPException(409, "Delivered events cannot be retried")
    event.status = "pending"
    event.attempt_count = 0
    event.next_attempt_at = None
    event.last_error = None
    await db.commit()
    await db.refresh(event)
    return event
