from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DB, User, require_roles
from app.models import OutboxEvent, StaffUser
from app.schemas.outbox import OutboxEventRead, OutboxProcessResult, OutboxStatus
from app.services.outbox import get_webhook_client, process_outbox, retry_event

router = APIRouter(prefix="/outbox", tags=["outbox"])
Admin = Annotated[StaffUser, Depends(require_roles("admin"))]


@router.get("", response_model=list[OutboxEventRead])
async def list_events(db: DB, user: User, status: OutboxStatus | None = None, event_type: str | None = None,
                      limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    query = select(OutboxEvent).where(OutboxEvent.clinic_id == user.clinic_id)
    if status:
        query = query.where(OutboxEvent.status == status)
    if event_type:
        query = query.where(OutboxEvent.event_type == event_type)
    return (await db.scalars(query.order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(limit).offset(offset))).all()


@router.post("/process", response_model=OutboxProcessResult)
async def process(db: DB, user: Admin, limit: int = Query(20, ge=1, le=100), client=Depends(get_webhook_client)):
    try:
        events = await process_outbox(db, client, limit, user.clinic_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return OutboxProcessResult(processed=len(events), delivered=sum(e.status == "delivered" for e in events), failed=sum(e.status == "failed" for e in events))


@router.get("/{event_id}", response_model=OutboxEventRead)
async def read_event(event_id: UUID, db: DB, user: User):
    event = await db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id, OutboxEvent.clinic_id == user.clinic_id))
    if event is None:
        raise HTTPException(404, "Outbox event not found")
    return event


@router.post("/{event_id}/retry", response_model=OutboxEventRead)
async def retry(event_id: UUID, db: DB, user: Admin):
    event = await db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id, OutboxEvent.clinic_id == user.clinic_id))
    if event is None:
        raise HTTPException(404, "Outbox event not found")
    return await retry_event(db, event)
