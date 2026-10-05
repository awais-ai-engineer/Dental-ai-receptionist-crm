from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Identified, Timestamped, clinic_fk


class Conversation(Identified, Timestamped, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(["patient_id", "clinic_id"], ["patients.id", "patients.clinic_id"]),
        ForeignKeyConstraint(["assigned_staff_id", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        UniqueConstraint("id", "clinic_id"),
        CheckConstraint("channel IN ('website_chat','phone','sms','whatsapp','manual')", name="channel"),
        CheckConstraint("status IN ('active','waiting_for_staff','escalated','closed')", name="status"),
        Index("ix_conversations_clinic_status", "clinic_id", "status"),
        Index("ix_conversations_clinic_last_message", "clinic_id", "last_message_at"),
    )

    clinic_id: Mapped[UUID] = clinic_fk()
    patient_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    assigned_staff_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(24), default="active")
    subject: Mapped[str | None] = mapped_column(String(200))
    public_access_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clinic = relationship("Clinic", foreign_keys=[clinic_id], viewonly=True)
    patient = relationship("Patient", foreign_keys=[patient_id, clinic_id], viewonly=True)
    assigned_staff = relationship("StaffUser", foreign_keys=[assigned_staff_id, clinic_id], viewonly=True)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Identified, Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(["conversation_id", "clinic_id"], ["conversations.id", "conversations.clinic_id"]),
        ForeignKeyConstraint(["sender_staff_id", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        CheckConstraint("sender_type IN ('patient','ai','staff','system')", name="sender_type"),
        CheckConstraint("(sender_type = 'staff') = (sender_staff_id IS NOT NULL)", name="staff_sender"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at", "id"),
    )

    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    clinic_id: Mapped[UUID] = clinic_fk()
    sender_type: Mapped[str] = mapped_column(String(20))
    sender_staff_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    sender_staff = relationship("StaffUser", foreign_keys=[sender_staff_id, clinic_id], viewonly=True)
