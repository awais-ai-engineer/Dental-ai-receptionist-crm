from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Channel = Literal["website_chat", "phone", "sms", "whatsapp", "manual"]
ConversationStatus = Literal["active", "waiting_for_staff", "escalated", "closed"]


class ConversationCreate(BaseModel):
    channel: Channel
    patient_id: UUID | None = None
    assigned_staff_id: UUID | None = None
    subject: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    patient_id: UUID | None = None
    assigned_staff_id: UUID | None = None
    subject: str | None = Field(default=None, max_length=200)
    status: Literal["active", "waiting_for_staff", "escalated"] | None = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    clinic_id: UUID
    patient_id: UUID | None
    assigned_staff_id: UUID | None
    channel: Channel
    status: ConversationStatus
    subject: str | None
    started_at: datetime
    ended_at: datetime | None
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message content cannot be blank")
        return value


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    sender_type: Literal["patient", "ai", "staff", "system"]
    sender_staff_id: UUID | None
    content: str
    created_at: datetime


class PublicMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    sender_type: Literal["patient", "ai", "staff"]
    content: str
    created_at: datetime


class PublicConversationCreate(BaseModel):
    clinic_slug: str = Field(min_length=1, max_length=220)


class PublicConversationRead(BaseModel):
    conversation_id: UUID
    access_token: str
