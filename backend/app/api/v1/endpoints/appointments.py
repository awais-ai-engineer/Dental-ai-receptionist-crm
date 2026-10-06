from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DB, User, require_roles
from app.models import Appointment, StaffUser
from app.schemas.core import AppointmentIn, AppointmentOut, AppointmentPatch, Reschedule
from app.services.appointments import cancel_appointment, create_appointment as create_appointment_service, get_appointment, reschedule_appointment, transition_appointment

router = APIRouter(prefix="/appointments", tags=["appointments"])
Manager = Annotated[StaffUser, Depends(require_roles("admin", "receptionist"))]


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(db: DB, user: User, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return (await db.scalars(select(Appointment).where(Appointment.clinic_id == user.clinic_id).order_by(Appointment.scheduled_start.desc()).limit(limit).offset(offset))).all()


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def read_appointment(appointment_id: UUID, db: DB, user: User):
    return await get_appointment(db, user.clinic_id, appointment_id)


@router.post("", response_model=AppointmentOut, status_code=201)
async def create_appointment(payload: AppointmentIn, db: DB, user: Manager):
    return await create_appointment_service(db, user.clinic_id, payload, created_by=user.id)


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
    return await transition_appointment(db, item, allowed, target)


@router.post("/{appointment_id}/approve", response_model=AppointmentOut)
async def approve(appointment_id: UUID, db: DB, user: Manager):
    return await transition(appointment_id, db, user, ("requested", "pending"), "approved")


@router.post("/{appointment_id}/confirm", response_model=AppointmentOut)
async def confirm(appointment_id: UUID, db: DB, user: Manager):
    return await transition(appointment_id, db, user, ("approved",), "confirmed")


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel(appointment_id: UUID, db: DB, user: Manager):
    return await cancel_appointment(db, await get_appointment(db, user.clinic_id, appointment_id))


@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
async def reschedule(appointment_id: UUID, payload: Reschedule, db: DB, user: Manager):
    return await reschedule_appointment(db, await get_appointment(db, user.clinic_id, appointment_id), payload)
