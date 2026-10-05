from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import select

from app.api.deps import DB
from app.models import Message
from app.schemas.conversation import MessageCreate, PublicConversationCreate, PublicConversationRead, PublicMessageRead
from app.services.conversations import add_message, create_public_conversation, get_public_conversation, request_handoff

router = APIRouter(prefix="/reception/conversations", tags=["reception"])
AccessToken = Annotated[str, Header(alias="X-Conversation-Token", min_length=32, max_length=128)]


@router.post("", response_model=PublicConversationRead, status_code=201)
async def start(payload: PublicConversationCreate, db: DB):
    item, token = await create_public_conversation(db, payload.clinic_slug)
    return PublicConversationRead(conversation_id=item.id, access_token=token)


@router.get("/{conversation_id}/messages", response_model=list[PublicMessageRead])
async def list_public_messages(conversation_id: UUID, token: AccessToken, db: DB, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    item = await get_public_conversation(db, conversation_id, token)
    return (await db.scalars(select(Message).where(Message.conversation_id == item.id, Message.clinic_id == item.clinic_id, Message.sender_type != "system").order_by(Message.created_at, Message.id).limit(limit).offset(offset))).all()


@router.post("/{conversation_id}/messages", response_model=PublicMessageRead, status_code=201)
async def create_public_message(conversation_id: UUID, payload: MessageCreate, token: AccessToken, db: DB):
    item = await get_public_conversation(db, conversation_id, token)
    return await add_message(db, item, payload.content, "patient")


@router.post("/{conversation_id}/handoff", status_code=204)
async def request_public_handoff(conversation_id: UUID, token: AccessToken, db: DB):
    item = await get_public_conversation(db, conversation_id, token)
    await request_handoff(db, item)
