"""Conversation and message persistence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_conversations"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade():
    uid = postgresql.UUID(as_uuid=True)
    ts = sa.DateTime(timezone=True)
    op.create_table("conversations",
        sa.Column("id", uid, primary_key=True),
        sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("patient_id", uid),
        sa.Column("assigned_staff_id", uid),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("subject", sa.String(200)),
        sa.Column("public_access_token_hash", sa.String(64), unique=True),
        sa.Column("started_at", ts, nullable=False),
        sa.Column("ended_at", ts),
        sa.Column("last_message_at", ts),
        sa.Column("created_at", ts, nullable=False),
        sa.Column("updated_at", ts, nullable=False),
        sa.ForeignKeyConstraint(["patient_id", "clinic_id"], ["patients.id", "patients.clinic_id"]),
        sa.ForeignKeyConstraint(["assigned_staff_id", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        sa.UniqueConstraint("id", "clinic_id"),
        sa.CheckConstraint("channel IN ('website_chat','phone','sms','whatsapp','manual')", name="channel"),
        sa.CheckConstraint("status IN ('active','waiting_for_staff','escalated','closed')", name="status"))
    op.create_index("ix_conversations_clinic_id", "conversations", ["clinic_id"])
    op.create_index("ix_conversations_patient_id", "conversations", ["patient_id"])
    op.create_index("ix_conversations_clinic_status", "conversations", ["clinic_id", "status"])
    op.create_index("ix_conversations_clinic_last_message", "conversations", ["clinic_id", "last_message_at"])
    op.create_table("messages",
        sa.Column("id", uid, primary_key=True),
        sa.Column("conversation_id", uid, nullable=False),
        sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("sender_type", sa.String(20), nullable=False),
        sa.Column("sender_staff_id", uid),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", ts, nullable=False),
        sa.ForeignKeyConstraint(["conversation_id", "clinic_id"], ["conversations.id", "conversations.clinic_id"]),
        sa.ForeignKeyConstraint(["sender_staff_id", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        sa.CheckConstraint("sender_type IN ('patient','ai','staff','system')", name="sender_type"),
        sa.CheckConstraint("(sender_type = 'staff') = (sender_staff_id IS NOT NULL)", name="staff_sender"))
    op.create_index("ix_messages_clinic_id", "messages", ["clinic_id"])
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at", "id"])


def downgrade():
    op.drop_table("messages")
    op.drop_table("conversations")
