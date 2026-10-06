from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select

from app.api.deps import DB, User, require_roles
from app.models import Doctor, Patient, StaffUser
from app.schemas.core import PatientIn, PatientOut, PatientPatch
from app.services.outbox import queue_patient_created

router = APIRouter(prefix="/patients", tags=["patients"])
Manager = Annotated[StaffUser, Depends(require_roles("admin", "receptionist"))]


async def get_patient(db: DB, clinic_id: UUID, patient_id: UUID) -> Patient:
    patient = await db.scalar(select(Patient).where(Patient.id == patient_id, Patient.clinic_id == clinic_id))
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return patient


async def validate_preferred_doctor(db: DB, clinic_id: UUID, doctor_id: UUID | None):
    if doctor_id and not await db.scalar(select(Doctor.id).where(Doctor.id == doctor_id, Doctor.clinic_id == clinic_id)):
        raise HTTPException(400, "Preferred doctor not found")


@router.get("", response_model=list[PatientOut])
async def list_patients(db: DB, user: User, search: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    query = select(Patient).where(Patient.clinic_id == user.clinic_id)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Patient.first_name.ilike(term), Patient.last_name.ilike(term), Patient.email.ilike(term), Patient.phone.ilike(term)))
    return (await db.scalars(query.order_by(Patient.created_at.desc()).limit(limit).offset(offset))).all()


@router.get("/{patient_id}", response_model=PatientOut)
async def read_patient(patient_id: UUID, db: DB, user: User):
    return await get_patient(db, user.clinic_id, patient_id)


@router.post("", response_model=PatientOut, status_code=201)
async def create_patient(payload: PatientIn, db: DB, user: Manager):
    await validate_preferred_doctor(db, user.clinic_id, payload.preferred_doctor_id)
    patient = Patient(clinic_id=user.clinic_id, **payload.model_dump())
    db.add(patient)
    await db.flush()
    await queue_patient_created(db, patient)
    await db.commit()
    await db.refresh(patient)
    return patient


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient(patient_id: UUID, payload: PatientPatch, db: DB, user: Manager):
    patient = await get_patient(db, user.clinic_id, patient_id)
    changes = payload.model_dump(exclude_unset=True)
    if "preferred_doctor_id" in changes:
        await validate_preferred_doctor(db, user.clinic_id, changes["preferred_doctor_id"])
    for key, value in changes.items():
        setattr(patient, key, value)
    await db.commit()
    await db.refresh(patient)
    return patient
