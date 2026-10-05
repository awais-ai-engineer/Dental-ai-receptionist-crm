from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DB, User, require_roles
from app.models import Conversation, Message, StaffUser
from app.schemas.conversation import Channel, ConversationCreate, ConversationRead, ConversationStatus, ConversationUpdate, MessageCreate, MessageRead
from app.services.conversations import add_message, close_conversation, create_conversation, get_conversation, request_handoff, update_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])
Manager = Annotated[StaffUser, Depends(require_roles("admin", "receptionist"))]


@router.post("", response_model=ConversationRead, status_code=201)
async def create(payload: ConversationCreate, db: DB, user: Manager):
    return await create_conversation(db, user.clinic_id, payload)


@router.get("", response_model=list[ConversationRead])
async def list_conversations(db: DB, user: User, status: ConversationStatus | None = None, channel: Channel | None = None, patient_id: UUID | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    query = select(Conversation).where(Conversation.clinic_id == user.clinic_id)
    if status:
        query = query.where(Conversation.status == status)
    if channel:
        query = query.where(Conversation.channel == channel)
    if patient_id:
        query = query.where(Conversation.patient_id == patient_id)
    return (await db.scalars(query.order_by(Conversation.started_at.desc(), Conversation.id.desc()).limit(limit).offset(offset))).all()


@router.get("/{conversation_id}", response_model=ConversationRead)
async def read(conversation_id: UUID, db: DB, user: User):
    return await get_conversation(db, user.clinic_id, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update(conversation_id: UUID, payload: ConversationUpdate, db: DB, user: Manager):
    item = await get_conversation(db, user.clinic_id, conversation_id)
    return await update_conversation(db, item, payload)


@router.post("/{conversation_id}/close", response_model=ConversationRead)
async def close(conversation_id: UUID, db: DB, user: Manager):
    item = await get_conversation(db, user.clinic_id, conversation_id)
    return await close_conversation(db, item)


@router.post("/{conversation_id}/handoff", response_model=ConversationRead)
async def handoff(conversation_id: UUID, db: DB, user: User):
    item = await get_conversation(db, user.clinic_id, conversation_id)
    return await request_handoff(db, item)


@router.get("/{conversation_id}/messages", response_model=list[MessageRead])
async def list_messages(conversation_id: UUID, db: DB, user: User, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    await get_conversation(db, user.clinic_id, conversation_id)
    return (await db.scalars(select(Message).where(Message.conversation_id == conversation_id, Message.clinic_id == user.clinic_id).order_by(Message.created_at, Message.id).limit(limit).offset(offset))).all()


@router.post("/{conversation_id}/messages", response_model=MessageRead, status_code=201)
async def create_message(conversation_id: UUID, payload: MessageCreate, db: DB, user: User):
    item = await get_conversation(db, user.clinic_id, conversation_id)
    return await add_message(db, item, payload.content, "staff", user.id)
