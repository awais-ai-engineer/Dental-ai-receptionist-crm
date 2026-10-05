from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["low", "medium", "high", "critical"]
EscalationStatus = Literal["open", "acknowledged", "resolved"]
EscalationSource = Literal["ai_receptionist", "receptionist", "doctor", "system", "manual"]


class EscalationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID | None = None
    patient_id: UUID | None = None
    assigned_staff_id: UUID | None = None
    assigned_doctor_id: UUID | None = None
    severity: Severity
    reason: str = Field(min_length=1, max_length=2000)
    summary: str | None = Field(default=None, max_length=4000)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Reason cannot be blank")
        return value


class EscalationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: UUID | None = None
    assigned_staff_id: UUID | None = None
    assigned_doctor_id: UUID | None = None
    severity: Severity | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=2000)
    summary: str | None = Field(default=None, max_length=4000)


class EscalationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    clinic_id: UUID
    conversation_id: UUID | None
    patient_id: UUID | None
    assigned_staff_id: UUID | None
    assigned_doctor_id: UUID | None
    severity: Severity
    status: EscalationStatus
    reason: str
    summary: str | None
    source: EscalationSource
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
