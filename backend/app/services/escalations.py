from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Doctor, Escalation, Patient, StaffUser
from app.schemas.escalation import EscalationCreate, EscalationUpdate
from app.services.conversations import get_conversation, validate_links


def recipient_roles(event: str, severity: str | None = None) -> tuple[str, ...]:
    if event == "appointment.requested":
        return ("receptionist",)
    if event != "escalation.created" or severity is None:
        raise ValueError("Unsupported notification event")
    if severity in ("low", "medium"):
        return ("receptionist",)
    if severity in ("high", "critical"):
        return ("receptionist", "admin")
    raise ValueError("Unsupported escalation severity")


def visible_to(user: StaffUser):
    if user.role != "doctor":
        return True
    own_doctors = select(Doctor.id).where(Doctor.clinic_id == user.clinic_id, Doctor.staff_user_id == user.id)
    return or_(Escalation.assigned_staff_id == user.id, Escalation.assigned_doctor_id.in_(own_doctors))


async def get_escalation(db: AsyncSession, user: StaffUser, escalation_id: UUID) -> Escalation:
    query = select(Escalation).where(Escalation.id == escalation_id, Escalation.clinic_id == user.clinic_id)
    visibility = visible_to(user)
    if visibility is not True:
        query = query.where(visibility)
    item = await db.scalar(query)
    if item is None:
        raise HTTPException(404, "Escalation not found")
    return item


async def validate_doctor(db: AsyncSession, clinic_id: UUID, doctor_id: UUID | None) -> None:
    if doctor_id is not None and not await db.scalar(select(Doctor.id).where(Doctor.id == doctor_id, Doctor.clinic_id == clinic_id, Doctor.is_active)):
        raise HTTPException(404, "Doctor not found")


async def create_escalation(db: AsyncSession, user: StaffUser, payload: EscalationCreate) -> Escalation:
    if user.role != "admin" and payload.assigned_doctor_id is not None:
        raise HTTPException(403, "Only admins can assign a doctor")
    if user.role == "doctor" and payload.assigned_staff_id is not None:
        raise HTTPException(403, "Doctors cannot assign staff")
    conversation: Conversation | None = None
    if payload.conversation_id is not None:
        conversation = await get_conversation(db, user.clinic_id, payload.conversation_id)
        if conversation.status == "closed":
            raise HTTPException(409, "Conversation is closed")
        if conversation.patient_id is not None and payload.patient_id not in (None, conversation.patient_id):
            raise HTTPException(409, "Patient does not match conversation")
    patient_id = payload.patient_id or (conversation.patient_id if conversation else None)
    await validate_links(db, user.clinic_id, patient_id, payload.assigned_staff_id)
    await validate_doctor(db, user.clinic_id, payload.assigned_doctor_id)
    assigned_staff_id = payload.assigned_staff_id or (conversation.assigned_staff_id if conversation else None)
    assigned_doctor_id = payload.assigned_doctor_id
    if user.role == "doctor":
        own_doctor = await db.scalar(select(Doctor).where(Doctor.clinic_id == user.clinic_id, Doctor.staff_user_id == user.id, Doctor.is_active))
        assigned_doctor_id = own_doctor.id if own_doctor is not None else None
        assigned_staff_id = user.id
    source = {"admin": "manual", "receptionist": "receptionist", "doctor": "doctor"}[user.role]
    item = Escalation(clinic_id=user.clinic_id, conversation_id=payload.conversation_id, patient_id=patient_id,
        assigned_staff_id=assigned_staff_id, assigned_doctor_id=assigned_doctor_id,
        severity=payload.severity, reason=payload.reason, summary=payload.summary, source=source, status="open")
    db.add(item)
    if conversation is not None:
        conversation.status = "escalated"
        if assigned_staff_id is not None:
            conversation.assigned_staff_id = assigned_staff_id
    await db.flush()
    from app.services.outbox import queue_escalation_event
    await queue_escalation_event(db, item, "escalation.created")
    await db.commit()
    await db.refresh(item)
    return item


async def create_public_escalation(db: AsyncSession, conversation: Conversation, severity: str, reason: str, summary: str | None) -> Escalation:
    """Create a clinic-scoped AI escalation without granting staff assignment powers."""
    if conversation.status == "closed":
        raise HTTPException(409, "Conversation is closed")
    await validate_links(db, conversation.clinic_id, conversation.patient_id)
    item = Escalation(clinic_id=conversation.clinic_id, conversation_id=conversation.id,
                      patient_id=conversation.patient_id, severity=severity, reason=reason,
                      summary=summary, source="ai_receptionist", status="open")
    conversation.status = "escalated"
    db.add(item)
    await db.flush()
    from app.services.outbox import queue_escalation_event
    await queue_escalation_event(db, item, "escalation.created")
    await db.commit()
    await db.refresh(item)
    return item


async def update_escalation(db: AsyncSession, user: StaffUser, item: Escalation, payload: EscalationUpdate) -> Escalation:
    if item.status == "resolved":
        raise HTTPException(409, "Resolved escalation cannot be changed")
    changes = payload.model_dump(exclude_unset=True)
    if user.role == "doctor":
        raise HTTPException(403, "Doctors cannot change escalation details")
    if user.role != "admin" and ("severity" in changes or "assigned_doctor_id" in changes):
        raise HTTPException(403, "Only admins can change severity or doctor assignment")
    if "severity" in changes and changes["severity"] is None:
        raise HTTPException(422, "Severity cannot be null")
    if "reason" in changes and (changes["reason"] is None or not changes["reason"].strip()):
        raise HTTPException(422, "Reason cannot be blank")
    if "patient_id" in changes:
        await validate_links(db, user.clinic_id, patient_id=changes["patient_id"])
        if item.conversation_id:
            conversation = await get_conversation(db, user.clinic_id, item.conversation_id)
            if conversation.patient_id is not None and changes["patient_id"] not in (None, conversation.patient_id):
                raise HTTPException(409, "Patient does not match conversation")
    if "assigned_staff_id" in changes:
        await validate_links(db, user.clinic_id, staff_id=changes["assigned_staff_id"])
    if "assigned_doctor_id" in changes:
        await validate_doctor(db, user.clinic_id, changes["assigned_doctor_id"])
    for key, value in changes.items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


async def acknowledge_escalation(db: AsyncSession, user: StaffUser, item: Escalation) -> Escalation:
    if item.status != "open":
        raise HTTPException(409, "Escalation is not open")
    item.status = "acknowledged"
    item.acknowledged_at = datetime.now(timezone.utc)
    if item.assigned_staff_id is None:
        item.assigned_staff_id = user.id
        if item.conversation_id is not None:
            conversation = await get_conversation(db, item.clinic_id, item.conversation_id)
            if conversation.assigned_staff_id is None:
                conversation.assigned_staff_id = user.id
    from app.services.outbox import queue_escalation_event
    await queue_escalation_event(db, item, "escalation.acknowledged")
    await db.commit()
    await db.refresh(item)
    return item


async def resolve_escalation(db: AsyncSession, user: StaffUser, item: Escalation) -> Escalation:
    if item.status != "acknowledged":
        raise HTTPException(409, "Escalation must be acknowledged first")
    if user.role == "receptionist" and item.severity in ("high", "critical"):
        raise HTTPException(403, "High severity escalations require an admin or assigned doctor")
    item.status = "resolved"
    item.resolved_at = datetime.now(timezone.utc)
    from app.services.outbox import queue_escalation_event
    await queue_escalation_event(db, item, "escalation.resolved")
    await db.commit()
    await db.refresh(item)
    return item


async def notification_recipients(db: AsyncSession, item: Escalation) -> list[StaffUser]:
    roles = recipient_roles("escalation.created", item.severity)
    users = (await db.scalars(select(StaffUser).where(StaffUser.clinic_id == item.clinic_id, StaffUser.role.in_(roles), StaffUser.is_active).order_by(StaffUser.email))).all()
    if item.severity == "critical" and item.assigned_doctor_id is not None:
        doctor = await db.scalar(select(Doctor).where(Doctor.id == item.assigned_doctor_id, Doctor.clinic_id == item.clinic_id))
        if doctor is not None and doctor.staff_user_id is not None:
            doctor_user = await db.scalar(select(StaffUser).where(StaffUser.id == doctor.staff_user_id, StaffUser.clinic_id == item.clinic_id, StaffUser.is_active))
            if doctor_user is not None:
                users.append(doctor_user)
    return list({user.email.casefold(): user for user in users}.values())


async def escalation_created_payload(db: AsyncSession, item: Escalation) -> dict:
    patient = await db.scalar(select(Patient).where(Patient.id == item.patient_id, Patient.clinic_id == item.clinic_id)) if item.patient_id else None
    recipients = await notification_recipients(db, item)
    return {"event": "escalation.created", "event_id": str(item.id), "clinic_id": str(item.clinic_id),
        "timestamp": item.created_at.isoformat(), "data": {"escalation_id": str(item.id), "severity": item.severity,
        "reason": item.reason, "summary": item.summary, "conversation_id": str(item.conversation_id) if item.conversation_id else None,
        "assigned_doctor_id": str(item.assigned_doctor_id) if item.assigned_doctor_id else None,
        "patient": {"id": str(patient.id), "name": f"{patient.first_name} {patient.last_name}", "email": patient.email, "phone": patient.phone} if patient else None,
        "recipients": [{"staff_user_id": str(user.id), "role": user.role, "email": user.email} for user in recipients]}}
