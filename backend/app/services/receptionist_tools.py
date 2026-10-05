"""Allowlisted public receptionist tools. The model never supplies trusted context."""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Clinic, Conversation, Doctor
from app.schemas.core import AppointmentIn, Reschedule
from app.services.conversations import request_handoff
from app.services.appointments import cancel_appointment, create_appointment, get_appointment, reschedule_appointment
from app.services.rag import answer_question, is_emergency
from app.services.scheduling import available_slots
from app.services.escalations import create_public_escalation

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReceptionistToolContext:
    conversation_id: UUID
    clinic_id: UUID
    patient_id: UUID | None
    mode: str = "public"

    @classmethod
    def from_conversation(cls, conversation: Conversation):
        return cls(conversation.id, conversation.clinic_id, conversation.patient_id)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeInput(StrictInput):
    question: str = Field(min_length=1, max_length=10000)


class ListDoctorsInput(StrictInput):
    specialty: str | None = Field(default=None, max_length=200)


class SlotsInput(StrictInput):
    doctor_id: UUID | None = None
    preferred_date: date
    duration_minutes: int = Field(default=30, ge=5, le=240)


class CreateAppointmentInput(StrictInput):
    doctor_id: UUID
    start_time: datetime
    duration_minutes: int = Field(default=30, ge=5, le=240)
    reason: str | None = Field(default=None, max_length=2000)


class RescheduleInput(StrictInput):
    appointment_id: UUID
    new_start_time: datetime


class CancelInput(StrictInput):
    appointment_id: UUID
    reason: str | None = Field(default=None, max_length=2000)


class HandoffInput(StrictInput):
    pass


class EscalationInput(StrictInput):
    severity: str = Field(pattern="^(low|medium|high|critical)$")
    reason: str = Field(min_length=1, max_length=2000)
    summary: str | None = Field(default=None, max_length=4000)


class ToolResult(BaseModel):
    success: bool
    tool: str
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None


TOOL_REGISTRY: dict[str, tuple[type[StrictInput], str]] = {
    "search_clinic_knowledge": (KnowledgeInput, "Answer a clinic FAQ from ready knowledge documents."),
    "list_doctors": (ListDoctorsInput, "List active clinic doctors, optionally by specialty."),
    "search_available_slots": (SlotsInput, "Find real available slots for a doctor and date."),
    "create_appointment_request": (CreateAppointmentInput, "Submit a requested appointment for the linked patient at an available slot."),
    "reschedule_appointment": (RescheduleInput, "Move the linked patient's own appointment to a valid slot."),
    "cancel_appointment": (CancelInput, "Cancel the linked patient's own appointment."),
    "request_human_handoff": (HandoffInput, "Ask clinic staff to take over this conversation."),
    "create_escalation": (EscalationInput, "Create a safety escalation for this conversation."),
}


def tool_spec() -> list[dict]:
    return [{"name": name, "description": description, "input_schema": schema.model_json_schema()} for name, (schema, description) in TOOL_REGISTRY.items()]


def _has_time_detail(text: str) -> bool:
    return bool(re.search(r"\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|afternoon|evening)\b", text, re.IGNORECASE))


async def _own_appointment(db: AsyncSession, ctx: ReceptionistToolContext, appointment_id: UUID) -> Appointment:
    if ctx.patient_id is None:
        raise HTTPException(403, "A linked patient is required")
    return await get_appointment(db, ctx.clinic_id, appointment_id, ctx.patient_id)


async def execute_tool(name: str, arguments: dict, *, db: AsyncSession, ctx: ReceptionistToolContext,
                       conversation: Conversation, patient_message: str, embedding_client, llm_client) -> ToolResult:
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return ToolResult(success=False, tool=name, error_code="unknown_tool", message="Requested tool is unavailable")
    try:
        payload = entry[0].model_validate(arguments)
    except ValidationError:
        return ToolResult(success=False, tool=name, error_code="invalid_arguments", message="Tool arguments are invalid")
    try:
        data = await _run(name, payload, db, ctx, conversation, patient_message, embedding_client, llm_client)
        log.info("receptionist_tool name=%s conversation_id=%s clinic_id=%s success=true", name, ctx.conversation_id, ctx.clinic_id)
        return ToolResult(success=True, tool=name, data=data)
    except ValidationError:
        return ToolResult(success=False, tool=name, error_code="invalid_arguments", message="Tool arguments are invalid")
    except HTTPException as exc:
        log.info("receptionist_tool name=%s conversation_id=%s clinic_id=%s success=false", name, ctx.conversation_id, ctx.clinic_id)
        code = {403: "forbidden", 404: "not_found", 409: "conflict"}.get(exc.status_code, "invalid_request")
        return ToolResult(success=False, tool=name, error_code=code, message=str(exc.detail))


async def _run(name: str, p: StrictInput, db: AsyncSession, ctx: ReceptionistToolContext,
               conversation: Conversation, patient_message: str, embedding_client, llm_client) -> dict:
    lowered = patient_message.lower()
    if name == "search_clinic_knowledge":
        result = await answer_question(db, ctx.clinic_id, p.question, embedding_client, llm_client)
        return result.model_dump(mode="json")
    if name == "list_doctors":
        query = select(Doctor).where(Doctor.clinic_id == ctx.clinic_id, Doctor.is_active)
        if p.specialty:
            query = query.where(Doctor.specialization.ilike(f"%{p.specialty}%"))
        doctors = (await db.scalars(query.order_by(Doctor.full_name).limit(100))).all()
        return {"doctors": [{"id": str(d.id), "full_name": d.full_name, "specialization": d.specialization, "consultation_duration_minutes": d.consultation_duration_minutes} for d in doctors]}
    if name == "search_available_slots":
        query = select(Doctor).where(Doctor.clinic_id == ctx.clinic_id, Doctor.is_active)
        if p.doctor_id:
            query = query.where(Doctor.id == p.doctor_id)
        doctors = (await db.scalars(query.order_by(Doctor.full_name).limit(50))).all()
        items = []
        for doctor in doctors:
            slots = await available_slots(db, ctx.clinic_id, doctor, p.preferred_date, p.duration_minutes)
            items.append({"doctor_id": str(doctor.id), "doctor_name": doctor.full_name, "slots": [slot.isoformat() for slot in slots]})
        return {"date": p.preferred_date.isoformat(), "duration_minutes": p.duration_minutes, "doctors": items}
    if name in ("create_appointment_request", "reschedule_appointment", "cancel_appointment") and ctx.patient_id is None:
        raise HTTPException(403, "Please contact clinic staff to link your patient record before changing appointments")
    if name == "create_appointment_request":
        if not any(word in lowered for word in ("book", "schedule", "appointment request")) or not _has_time_detail(patient_message):
            raise HTTPException(409, "Please clearly ask to book an appointment and provide a preferred date or time")
        start = p.start_time
        end = start + timedelta(minutes=p.duration_minutes)
        doctor = await db.scalar(select(Doctor).where(Doctor.id == p.doctor_id, Doctor.clinic_id == ctx.clinic_id, Doctor.is_active))
        if doctor is None:
            raise HTTPException(404, "Doctor not found")
        clinic = await db.get(Clinic, ctx.clinic_id)
        slots = await available_slots(db, ctx.clinic_id, doctor, start.astimezone(ZoneInfo(clinic.timezone)).date(), p.duration_minutes)
        if start.astimezone(timezone.utc) not in slots:
            raise HTTPException(409, "Requested slot is unavailable")
        appointment_payload = AppointmentIn(patient_id=ctx.patient_id, doctor_id=doctor.id, scheduled_start=start,
                                             scheduled_end=end, source="ai_receptionist", reason=p.reason)
        item = await create_appointment(db, ctx.clinic_id, appointment_payload)
        return {"appointment_id": str(item.id), "status": item.status, "doctor_id": str(item.doctor_id), "scheduled_start": item.scheduled_start.isoformat(), "scheduled_end": item.scheduled_end.isoformat()}
    if name == "reschedule_appointment":
        if not any(word in lowered for word in ("reschedule", "move my appointment", "change my appointment")) or not _has_time_detail(patient_message):
            raise HTTPException(409, "Please clearly ask to reschedule and provide a preferred date or time")
        item = await _own_appointment(db, ctx, p.appointment_id)
        duration = item.scheduled_end - item.scheduled_start
        end = p.new_start_time + duration
        item = await reschedule_appointment(db, item, Reschedule(scheduled_start=p.new_start_time, scheduled_end=end))
        return {"appointment_id": str(item.id), "status": item.status, "scheduled_start": item.scheduled_start.isoformat()}
    if name == "cancel_appointment":
        if "cancel" not in lowered or "appointment" not in lowered:
            raise HTTPException(409, "Please clearly ask to cancel your appointment")
        item = await _own_appointment(db, ctx, p.appointment_id)
        item = await cancel_appointment(db, item)
        return {"appointment_id": str(item.id), "status": item.status}
    if name == "request_human_handoff":
        if not any(word in lowered for word in ("human", "staff", "person", "receptionist", "help")) and not is_emergency(patient_message):
            raise HTTPException(409, "Please ask to speak with clinic staff")
        item = await request_handoff(db, conversation)
        return {"conversation_id": str(item.id), "status": item.status}
    if name == "create_escalation":
        if not is_emergency(patient_message) and not any(word in lowered for word in ("urgent", "emergency", "escalate")):
            raise HTTPException(409, "Escalation requires an explicit urgent request")
        severity = "critical" if is_emergency(patient_message) else ("high" if "urgent" in lowered else "low")
        item = await create_public_escalation(db, conversation, severity, p.reason, p.summary)
        return {"escalation_id": str(item.id), "severity": item.severity, "status": item.status}
    raise RuntimeError("Registry handler missing")
