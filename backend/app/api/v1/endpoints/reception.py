from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DB
from app.models import Message
from app.schemas.conversation import MessageCreate, PublicConversationCreate, PublicConversationRead, PublicMessageRead
from app.services.conversations import add_message, create_public_conversation, get_public_conversation, request_handoff
from app.services.providers import ProviderError, get_embedding_client, get_llm_client
from app.services.rag import Answer, answer_question
from app.services.receptionist import ReceptionistResponse, orchestrate
from app.models import Conversation
from pydantic import BaseModel, Field

router = APIRouter(prefix="/reception/conversations", tags=["reception"])
AccessToken = Annotated[str, Header(alias="X-Conversation-Token", min_length=32, max_length=128)]


class ReceptionistMessage(BaseModel):
    message: str = Field(min_length=1, max_length=10000)


async def public_conversation(conversation_id: UUID, token: AccessToken, db: DB) -> Conversation:
    return await get_public_conversation(db, conversation_id, token)


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


@router.post("/{conversation_id}/ask", response_model=Answer)
async def ask(conversation_id: UUID, payload: MessageCreate, token: AccessToken, db: DB,
              embedding_client=Depends(get_embedding_client), llm_client=Depends(get_llm_client)):
    item = await get_public_conversation(db, conversation_id, token)
    await add_message(db, item, payload.content, "patient")
    try:
        result = await answer_question(db, item.clinic_id, payload.content, embedding_client, llm_client)
    except ProviderError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    if result.requires_escalation:
        await request_handoff(db, item)
    await add_message(db, item, result.answer, "ai")
    return result


@router.post("/{conversation_id}/message", response_model=ReceptionistResponse)
async def receptionist_message(payload: ReceptionistMessage, db: DB,
                               conversation: Annotated[Conversation, Depends(public_conversation)],
                               embedding_client=Depends(get_embedding_client), llm_client=Depends(get_llm_client)):
    await add_message(db, conversation, payload.message, "patient")
    try:
        result = await orchestrate(db, conversation, payload.message, llm_client, embedding_client)
    except ProviderError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    await add_message(db, conversation, result.answer, "ai")
    return result
