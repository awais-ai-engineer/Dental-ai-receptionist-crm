from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentSource = Literal["manual", "faq", "text", "pdf"]
DocumentStatus = Literal["pending", "processing", "ready", "failed"]


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    source_type: Literal["manual", "faq", "text"] = "manual"
    content: str = Field(min_length=1, max_length=200000)

    @field_validator("title", "content")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank")
        return value


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    clinic_id: UUID
    title: str
    filename: str | None
    source_type: DocumentSource
    mime_type: str | None
    status: DocumentStatus
    error_message: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    metadata: dict = Field(validation_alias="metadata_json")
    created_at: datetime
