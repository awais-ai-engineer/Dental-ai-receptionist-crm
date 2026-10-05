from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DB, User
from app.models import Escalation
from app.schemas.escalation import EscalationCreate, EscalationRead, EscalationStatus, EscalationUpdate, Severity
from app.services.escalations import acknowledge_escalation, create_escalation, get_escalation, resolve_escalation, update_escalation, visible_to

router = APIRouter(prefix="/escalations", tags=["escalations"])


@router.post("", response_model=EscalationRead, status_code=201)
async def create(payload: EscalationCreate, db: DB, user: User):
    return await create_escalation(db, user, payload)


@router.get("", response_model=list[EscalationRead])
async def list_escalations(db: DB, user: User, status: EscalationStatus | None = None, severity: Severity | None = None,
                           patient_id: UUID | None = None, conversation_id: UUID | None = None, assigned_staff_id: UUID | None = None,
                           limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    query = select(Escalation).where(Escalation.clinic_id == user.clinic_id)
    visibility = visible_to(user)
    if visibility is not True:
        query = query.where(visibility)
    for column, value in ((Escalation.status, status), (Escalation.severity, severity), (Escalation.patient_id, patient_id),
                          (Escalation.conversation_id, conversation_id), (Escalation.assigned_staff_id, assigned_staff_id)):
        if value is not None:
            query = query.where(column == value)
    return (await db.scalars(query.order_by(Escalation.created_at.desc(), Escalation.id.desc()).limit(limit).offset(offset))).all()


@router.get("/{escalation_id}", response_model=EscalationRead)
async def read(escalation_id: UUID, db: DB, user: User):
    return await get_escalation(db, user, escalation_id)


@router.patch("/{escalation_id}", response_model=EscalationRead)
async def update(escalation_id: UUID, payload: EscalationUpdate, db: DB, user: User):
    item = await get_escalation(db, user, escalation_id)
    return await update_escalation(db, user, item, payload)


@router.post("/{escalation_id}/acknowledge", response_model=EscalationRead)
async def acknowledge(escalation_id: UUID, db: DB, user: User):
    item = await get_escalation(db, user, escalation_id)
    return await acknowledge_escalation(db, user, item)


@router.post("/{escalation_id}/resolve", response_model=EscalationRead)
async def resolve(escalation_id: UUID, db: DB, user: User):
    item = await get_escalation(db, user, escalation_id)
    return await resolve_escalation(db, user, item)
