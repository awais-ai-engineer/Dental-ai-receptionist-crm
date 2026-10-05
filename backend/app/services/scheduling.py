from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Clinic, Doctor, DoctorAvailability, Patient

ACTIVE_STATUSES = ("requested", "pending", "approved", "confirmed")


async def validate_slot(db: AsyncSession, clinic_id: UUID, doctor_id: UUID, patient_id: UUID, start: datetime, end: datetime, exclude_id: UUID | None = None) -> None:
    doctor = await db.scalar(select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == clinic_id, Doctor.is_active))
    patient = await db.scalar(select(Patient).where(Patient.id == patient_id, Patient.clinic_id == clinic_id))
    if doctor is None or patient is None:
        raise HTTPException(404, "Doctor or patient not found")
    clinic = await db.get(Clinic, clinic_id)
    try:
        zone = ZoneInfo(clinic.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(400, "Clinic timezone is invalid") from None
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    if local_start.date() != local_end.date():
        raise HTTPException(400, "Appointment must fit within one local day")
    windows = (await db.scalars(select(DoctorAvailability).where(DoctorAvailability.doctor_id == doctor_id, DoctorAvailability.day_of_week == local_start.weekday(), DoctorAvailability.is_available))).all()
    if not any(window.start_time <= local_start.time().replace(tzinfo=None) and local_end.time().replace(tzinfo=None) <= window.end_time for window in windows):
        raise HTTPException(409, "Doctor is unavailable at that time")
    query = select(Appointment.id).where(Appointment.clinic_id == clinic_id, Appointment.doctor_id == doctor_id, Appointment.status.in_(ACTIVE_STATUSES), Appointment.scheduled_start < end, Appointment.scheduled_end > start)
    if exclude_id:
        query = query.where(Appointment.id != exclude_id)
    if await db.scalar(query):
        raise HTTPException(409, "Appointment overlaps an existing booking")


async def available_slots(db: AsyncSession, clinic_id: UUID, doctor: Doctor, day: date, duration_minutes: int) -> list[datetime]:
    clinic = await db.get(Clinic, clinic_id)
    try:
        zone = ZoneInfo(clinic.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(400, "Clinic timezone is invalid") from None
    windows = (await db.scalars(select(DoctorAvailability).where(DoctorAvailability.doctor_id == doctor.id, DoctorAvailability.day_of_week == day.weekday(), DoctorAvailability.is_available))).all()
    results: list[datetime] = []
    duration = timedelta(minutes=duration_minutes)
    for window in windows:
        current = datetime.combine(day, window.start_time, zone)
        end = datetime.combine(day, window.end_time, zone)
        while current + duration <= end:
            utc_start = current.astimezone(timezone.utc)
            if utc_start > datetime.now(timezone.utc):
                query = select(Appointment.id).where(Appointment.clinic_id == clinic_id, Appointment.doctor_id == doctor.id, Appointment.status.in_(ACTIVE_STATUSES), Appointment.scheduled_start < utc_start + duration, Appointment.scheduled_end > utc_start)
                if not await db.scalar(query):
                    results.append(utc_start)
            current += duration
    return sorted(set(results))
