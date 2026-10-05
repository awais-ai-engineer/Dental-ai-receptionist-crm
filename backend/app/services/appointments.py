from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment
from app.schemas.core import AppointmentIn, Reschedule
from app.services.scheduling import ACTIVE_STATUSES, validate_slot


async def get_appointment(db: AsyncSession, clinic_id: UUID, appointment_id: UUID, patient_id: UUID | None = None) -> Appointment:
    query = select(Appointment).where(Appointment.id == appointment_id, Appointment.clinic_id == clinic_id)
    if patient_id is not None:
        query = query.where(Appointment.patient_id == patient_id)
    item = await db.scalar(query)
    if item is None:
        raise HTTPException(404, "Appointment not found")
    return item


async def create_appointment(db: AsyncSession, clinic_id: UUID, payload: AppointmentIn, *, created_by: UUID | None = None, status: str = "requested") -> Appointment:
    await validate_slot(db, clinic_id, payload.doctor_id, payload.patient_id, payload.scheduled_start, payload.scheduled_end)
    item = Appointment(clinic_id=clinic_id, created_by=created_by, status=status, **payload.model_dump())
    db.add(item)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Appointment conflicts with another booking") from None
    await db.refresh(item)
    return item


async def reschedule_appointment(db: AsyncSession, item: Appointment, payload: Reschedule) -> Appointment:
    if item.status not in ACTIVE_STATUSES:
        raise HTTPException(409, "Appointment cannot be rescheduled")
    await validate_slot(db, item.clinic_id, item.doctor_id, item.patient_id, payload.scheduled_start, payload.scheduled_end, item.id)
    item.scheduled_start = payload.scheduled_start
    item.scheduled_end = payload.scheduled_end
    item.status = "requested"
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Appointment conflicts with another booking") from None
    await db.refresh(item)
    return item


async def cancel_appointment(db: AsyncSession, item: Appointment) -> Appointment:
    if item.status not in ACTIVE_STATUSES:
        raise HTTPException(409, "Appointment cannot be cancelled")
    item.status = "cancelled"
    await db.commit()
    await db.refresh(item)
    return item
