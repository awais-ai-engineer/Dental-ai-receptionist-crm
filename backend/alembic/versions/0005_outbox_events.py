"""Durable transactional outbox events."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_outbox_events"
down_revision = "0004_knowledge_base"
branch_labels = None
depends_on = None


def upgrade():
    uid = postgresql.UUID(as_uuid=True)
    ts = sa.DateTime(timezone=True)
    op.create_table("outbox_events",
        sa.Column("id", uid, primary_key=True),
        sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", uid),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("next_attempt_at", ts),
        sa.Column("last_attempt_at", ts),
        sa.Column("delivered_at", ts),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", ts, nullable=False),
        sa.Column("updated_at", ts, nullable=False),
        sa.CheckConstraint("status IN ('pending','processing','delivered','failed')", name="status"),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count"))
    op.create_index("ix_outbox_events_clinic_id", "outbox_events", ["clinic_id"])
    op.create_index("ix_outbox_events_status_next_attempt", "outbox_events", ["status", "next_attempt_at"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_created_at", "outbox_events", ["created_at"])


def downgrade():
    op.drop_table("outbox_events")
