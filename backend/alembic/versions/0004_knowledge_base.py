"""Clinic knowledge documents and pgvector chunks."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0004_knowledge_base"
down_revision = "0003_escalations"
branch_labels = None
depends_on = None


def upgrade():
    uid = postgresql.UUID(as_uuid=True)
    ts = sa.DateTime(timezone=True)
    op.create_table("knowledge_documents",
        sa.Column("id", uid, primary_key=True),
        sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("filename", sa.String(255)),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("created_by", uid),
        sa.Column("created_at", ts, nullable=False),
        sa.Column("updated_at", ts, nullable=False),
        sa.ForeignKeyConstraint(["created_by", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        sa.UniqueConstraint("id", "clinic_id"),
        sa.CheckConstraint("source_type IN ('manual','faq','text','pdf')", name="source_type"),
        sa.CheckConstraint("status IN ('pending','processing','ready','failed')", name="status"))
    op.create_index("ix_knowledge_documents_clinic_id", "knowledge_documents", ["clinic_id"])
    op.create_index("ix_knowledge_documents_clinic_status", "knowledge_documents", ["clinic_id", "status"])
    op.create_table("knowledge_chunks",
        sa.Column("id", uid, primary_key=True),
        sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("document_id", uid, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column("metadata", postgresql.JSONB, nullable=False),
        sa.Column("created_at", ts, nullable=False),
        sa.ForeignKeyConstraint(["document_id", "clinic_id"], ["knowledge_documents.id", "knowledge_documents.clinic_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "chunk_index"),
        sa.CheckConstraint("chunk_index >= 0", name="chunk_index"),
        sa.CheckConstraint("length(btrim(content)) > 0", name="content"))
    op.create_index("ix_knowledge_chunks_clinic_id", "knowledge_chunks", ["clinic_id"])
    op.create_index("ix_knowledge_chunks_clinic_document", "knowledge_chunks", ["clinic_id", "document_id"])


def downgrade():
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
