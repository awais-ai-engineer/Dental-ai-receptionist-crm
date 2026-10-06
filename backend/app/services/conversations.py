import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Clinic, Conversation, Message, Patient, StaffUser
from app.schemas.conversation import ConversationCreate, ConversationUpdate


async def get_conversation(db: AsyncSession, clinic_id: UUID, conversation_id: UUID) -> Conversation:
    item = await db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.clinic_id == clinic_id))
    if item is None:
        raise HTTPException(404, "Conversation not found")
    return item


async def validate_links(db: AsyncSession, clinic_id: UUID, patient_id: UUID | None = None, staff_id: UUID | None = None) -> None:
    if patient_id is not None and not await db.scalar(select(Patient.id).where(Patient.id == patient_id, Patient.clinic_id == clinic_id)):
        raise HTTPException(404, "Patient not found")
    if staff_id is not None and not await db.scalar(select(StaffUser.id).where(StaffUser.id == staff_id, StaffUser.clinic_id == clinic_id, StaffUser.is_active)):
        raise HTTPException(404, "Staff user not found")


async def create_conversation(db: AsyncSession, clinic_id: UUID, payload: ConversationCreate) -> Conversation:
    await validate_links(db, clinic_id, payload.patient_id, payload.assigned_staff_id)
    item = Conversation(clinic_id=clinic_id, started_at=datetime.now(timezone.utc), **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def assign_conversation(db: AsyncSession, conversation: Conversation, staff_id: UUID | None) -> None:
    await validate_links(db, conversation.clinic_id, staff_id=staff_id)
    conversation.assigned_staff_id = staff_id


async def request_handoff(db: AsyncSession, conversation: Conversation) -> Conversation:
    if conversation.status == "closed":
        raise HTTPException(409, "Conversation is closed")
    if conversation.status == "escalated":
        return conversation
    if conversation.status == "waiting_for_staff":
        return conversation
    conversation.status = "waiting_for_staff"
    from app.services.outbox import queue_handoff_event
    await queue_handoff_event(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def update_conversation(db: AsyncSession, conversation: Conversation, payload: ConversationUpdate) -> Conversation:
    if conversation.status == "closed":
        raise HTTPException(409, "Closed conversations cannot be changed")
    changes = payload.model_dump(exclude_unset=True)
    if "patient_id" in changes:
        await validate_links(db, conversation.clinic_id, patient_id=changes["patient_id"])
    if "assigned_staff_id" in changes:
        await assign_conversation(db, conversation, changes.pop("assigned_staff_id"))
    for key, value in changes.items():
        if key == "status" and value is None:
            raise HTTPException(422, "Status cannot be null")
        setattr(conversation, key, value)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def close_conversation(db: AsyncSession, conversation: Conversation) -> Conversation:
    if conversation.status == "closed":
        raise HTTPException(409, "Conversation is already closed")
    conversation.status = "closed"
    conversation.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def add_message(db: AsyncSession, conversation: Conversation, content: str, sender_type: str, sender_staff_id: UUID | None = None) -> Message:
    if conversation.status == "closed":
        raise HTTPException(409, "Conversation is closed")
    now = datetime.now(timezone.utc)
    item = Message(conversation_id=conversation.id, clinic_id=conversation.clinic_id, sender_type=sender_type, sender_staff_id=sender_staff_id, content=content, created_at=now)
    conversation.last_message_at = now
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def create_public_conversation(db: AsyncSession, clinic_slug: str) -> tuple[Conversation, str]:
    clinic = await db.scalar(select(Clinic).where(Clinic.slug == clinic_slug, Clinic.is_active))
    if clinic is None:
        raise HTTPException(404, "Clinic not found")
    token = secrets.token_urlsafe(32)
    item = Conversation(clinic_id=clinic.id, channel="website_chat", status="active", started_at=datetime.now(timezone.utc), public_access_token_hash=hashlib.sha256(token.encode()).hexdigest())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item, token


async def get_public_conversation(db: AsyncSession, conversation_id: UUID, access_token: str) -> Conversation:
    item = await db.get(Conversation, conversation_id)
    if item is None or item.channel != "website_chat" or item.public_access_token_hash is None or not hmac.compare_digest(item.public_access_token_hash, hashlib.sha256(access_token.encode()).hexdigest()):
        raise HTTPException(404, "Conversation not found")
    clinic = await db.get(Clinic, item.clinic_id)
    if clinic is None or not clinic.is_active:
        raise HTTPException(404, "Conversation not found")
    return item
