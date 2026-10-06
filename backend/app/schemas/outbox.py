from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

OutboxStatus = Literal["pending", "processing", "delivered", "failed"]


class OutboxEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    clinic_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID | None
    payload: dict
    status: OutboxStatus
    attempt_count: int
    next_attempt_at: datetime | None
    last_attempt_at: datetime | None
    delivered_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class OutboxProcessResult(BaseModel):
    processed: int
    delivered: int
    failed: int
