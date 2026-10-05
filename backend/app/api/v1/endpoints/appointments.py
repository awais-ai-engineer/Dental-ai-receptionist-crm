from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, User, require_roles
from app.models import Appointment, StaffUser
from app.schemas.core import AppointmentIn, AppointmentOut, AppointmentPatch, Reschedule
from app.services.scheduling import validate_slot

router = APIRouter(prefix="/appointments", tags=["appointments"])
Manager = Annotated[StaffUser, Depends(require_roles("admin", "receptionist"))]


async def get_appointment(db: DB, clinic_id: UUID, appointment_id: UUID) -> Appointment:
    appointment = await db.scalar(select(Appointment).where(Appointment.id == appointment_id, Appointment.clinic_id == clinic_id))
    if appointment is None:
        raise HTTPException(404, "Appointment not found")
    return appointment


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(db: DB, user: User, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return (await db.scalars(select(Appointment).where(Appointment.clinic_id == user.clinic_id).order_by(Appointment.scheduled_start.desc()).limit(limit).offset(offset))).all()


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def read_appointment(appointment_id: UUID, db: DB, user: User):
    return await get_appointment(db, user.clinic_id, appointment_id)


@router.post("", response_model=AppointmentOut, status_code=201)
async def create_appointment(payload: AppointmentIn, db: DB, user: Manager):
    await validate_slot(db, user.clinic_id, payload.doctor_id, payload.patient_id, payload.scheduled_start, payload.scheduled_end)
    item = Appointment(clinic_id=user.clinic_id, created_by=user.id, **payload.model_dump())
    db.add(item)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Appointment conflicts with another booking") from None
    await db.refresh(item)
    return item


@router.patch("/{appointment_id}", response_model=AppointmentOut)
async def update_appointment(appointment_id: UUID, payload: AppointmentPatch, db: DB, user: Manager):
    item = await get_appointment(db, user.clinic_id, appointment_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


async def transition(appointment_id: UUID, db: DB, user: StaffUser, allowed: tuple[str, ...], target: str) -> Appointment:
    item = await get_appointment(db, user.clinic_id, appointment_id)
    if item.status not in allowed:
        raise HTTPException(409, "Invalid appointment status transition")
    item.status = target
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/{appointment_id}/approve", response_model=AppointmentOut)
async def approve(appointment_id: UUID, db: DB, user: Manager):
    return await transition(appointment_id, db, user, ("requested", "pending"), "approved")


@router.post("/{appointment_id}/confirm", response_model=AppointmentOut)
async def confirm(appointment_id: UUID, db: DB, user: Manager):
    return await transition(appointment_id, db, user, ("approved",), "confirmed")


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel(appointment_id: UUID, db: DB, user: Manager):
    return await transition(appointment_id, db, user, ("requested", "pending", "approved", "confirmed"), "cancelled")


@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
async def reschedule(appointment_id: UUID, payload: Reschedule, db: DB, user: Manager):
    item = await get_appointment(db, user.clinic_id, appointment_id)
    if item.status not in ("requested", "pending", "approved", "confirmed"):
        raise HTTPException(409, "Appointment cannot be rescheduled")
    await validate_slot(db, user.clinic_id, item.doctor_id, item.patient_id, payload.scheduled_start, payload.scheduled_end, item.id)
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
