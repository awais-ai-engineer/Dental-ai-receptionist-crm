from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DB, User, require_roles
from app.models import Doctor, DoctorAvailability, StaffUser
from app.schemas.core import AvailabilityIn, AvailabilityOut, DoctorIn, DoctorOut, DoctorPatch
from app.services.scheduling import available_slots

router = APIRouter(prefix="/doctors", tags=["doctors"])
Manager = Annotated[StaffUser, Depends(require_roles("admin", "receptionist"))]


async def get_doctor(db: DB, clinic_id: UUID, doctor_id: UUID) -> Doctor:
    doctor = await db.scalar(select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == clinic_id))
    if doctor is None:
        raise HTTPException(404, "Doctor not found")
    return doctor


@router.get("", response_model=list[DoctorOut])
async def list_doctors(db: DB, user: User, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return (await db.scalars(select(Doctor).where(Doctor.clinic_id == user.clinic_id).order_by(Doctor.full_name).limit(limit).offset(offset))).all()


@router.get("/{doctor_id}", response_model=DoctorOut)
async def read_doctor(doctor_id: UUID, db: DB, user: User):
    return await get_doctor(db, user.clinic_id, doctor_id)


@router.post("", response_model=DoctorOut, status_code=201)
async def create_doctor(payload: DoctorIn, db: DB, user: Manager):
    if payload.staff_user_id:
        staff = await db.get(StaffUser, payload.staff_user_id)
        if staff is None or staff.clinic_id != user.clinic_id or staff.role != "doctor":
            raise HTTPException(400, "Invalid doctor staff account")
    doctor = Doctor(clinic_id=user.clinic_id, **payload.model_dump())
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return doctor


@router.patch("/{doctor_id}", response_model=DoctorOut)
async def update_doctor(doctor_id: UUID, payload: DoctorPatch, db: DB, user: Manager):
    doctor = await get_doctor(db, user.clinic_id, doctor_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(doctor, key, value)
    await db.commit()
    await db.refresh(doctor)
    return doctor


@router.delete("/{doctor_id}", status_code=204)
async def deactivate_doctor(doctor_id: UUID, db: DB, user: Manager):
    doctor = await get_doctor(db, user.clinic_id, doctor_id)
    doctor.is_active = False
    await db.commit()


@router.get("/{doctor_id}/availability", response_model=list[AvailabilityOut])
async def list_availability(doctor_id: UUID, db: DB, user: User):
    await get_doctor(db, user.clinic_id, doctor_id)
    return (await db.scalars(select(DoctorAvailability).where(DoctorAvailability.doctor_id == doctor_id).order_by(DoctorAvailability.day_of_week, DoctorAvailability.start_time))).all()


@router.post("/{doctor_id}/availability", response_model=AvailabilityOut, status_code=201)
async def add_availability(doctor_id: UUID, payload: AvailabilityIn, db: DB, user: Manager):
    await get_doctor(db, user.clinic_id, doctor_id)
    windows = (await db.scalars(select(DoctorAvailability).where(DoctorAvailability.doctor_id == doctor_id, DoctorAvailability.day_of_week == payload.day_of_week))).all()
    if any(payload.start_time < item.end_time and payload.end_time > item.start_time for item in windows):
        raise HTTPException(409, "Availability windows overlap")
    item = DoctorAvailability(doctor_id=doctor_id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/{doctor_id}/available-slots", response_model=list[datetime])
async def slots(doctor_id: UUID, date: date, db: DB, user: User, duration_minutes: int = Query(30, ge=5, le=240)):
    doctor = await get_doctor(db, user.clinic_id, doctor_id)
    if not doctor.is_active:
        return []
    return await available_slots(db, user.clinic_id, doctor, date, duration_minutes)
