from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Identified, Timestamped, clinic_fk


class Escalation(Identified, Timestamped, Base):
    __tablename__ = "escalations"
    __table_args__ = (
        ForeignKeyConstraint(["conversation_id", "clinic_id"], ["conversations.id", "conversations.clinic_id"]),
        ForeignKeyConstraint(["patient_id", "clinic_id"], ["patients.id", "patients.clinic_id"]),
        ForeignKeyConstraint(["assigned_staff_id", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        ForeignKeyConstraint(["assigned_doctor_id", "clinic_id"], ["doctors.id", "doctors.clinic_id"]),
        CheckConstraint("severity IN ('low','medium','high','critical')", name="severity"),
        CheckConstraint("status IN ('open','acknowledged','resolved')", name="status"),
        CheckConstraint("source IN ('ai_receptionist','receptionist','doctor','system','manual')", name="source"),
        CheckConstraint("(status = 'open' AND acknowledged_at IS NULL AND resolved_at IS NULL) OR (status = 'acknowledged' AND acknowledged_at IS NOT NULL AND resolved_at IS NULL) OR (status = 'resolved' AND acknowledged_at IS NOT NULL AND resolved_at IS NOT NULL)", name="lifecycle"),
        Index("ix_escalations_clinic_status", "clinic_id", "status"),
        Index("ix_escalations_clinic_severity", "clinic_id", "severity"),
        Index("ix_escalations_clinic_created", "clinic_id", "created_at"),
    )

    clinic_id: Mapped[UUID] = clinic_fk()
    conversation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    patient_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    assigned_staff_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    assigned_doctor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    severity: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16), default="open")
    reason: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(24))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation = relationship("Conversation", foreign_keys=[conversation_id, clinic_id], viewonly=True)
    patient = relationship("Patient", foreign_keys=[patient_id, clinic_id], viewonly=True)
    assigned_staff = relationship("StaffUser", foreign_keys=[assigned_staff_id, clinic_id], viewonly=True)
    assigned_doctor = relationship("Doctor", foreign_keys=[assigned_doctor_id, clinic_id], viewonly=True)
