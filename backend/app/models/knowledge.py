from datetime import datetime, timezone
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Identified, Timestamped, clinic_fk

STORED_EMBEDDING_DIMENSION = 1536


class KnowledgeDocument(Identified, Timestamped, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        ForeignKeyConstraint(["created_by", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        UniqueConstraint("id", "clinic_id"),
        CheckConstraint("source_type IN ('manual','faq','text','pdf')", name="source_type"),
        CheckConstraint("status IN ('pending','processing','ready','failed')", name="status"),
        Index("ix_knowledge_documents_clinic_status", "clinic_id", "status"),
    )

    clinic_id: Mapped[UUID] = clinic_fk()
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(20))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="document", passive_deletes=True)


class KnowledgeChunk(Identified, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(["document_id", "clinic_id"], ["knowledge_documents.id", "knowledge_documents.clinic_id"], ondelete="CASCADE"),
        UniqueConstraint("document_id", "chunk_index"),
        CheckConstraint("chunk_index >= 0", name="chunk_index"),
        CheckConstraint("length(btrim(content)) > 0", name="content"),
        Index("ix_knowledge_chunks_clinic_document", "clinic_id", "document_id"),
    )

    clinic_id: Mapped[UUID] = clinic_fk()
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(STORED_EMBEDDING_DIMENSION))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
