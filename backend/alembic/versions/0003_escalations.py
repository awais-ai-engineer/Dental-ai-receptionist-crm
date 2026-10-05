"""Persistent emergency escalations and handoff assignments."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_escalations"
down_revision = "0002_conversations"
branch_labels = None
depends_on = None


def upgrade():
    uid = postgresql.UUID(as_uuid=True)
    ts = sa.DateTime(timezone=True)
    op.create_table("escalations",
        sa.Column("id", uid, primary_key=True),
        sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("conversation_id", uid),
        sa.Column("patient_id", uid),
        sa.Column("assigned_staff_id", uid),
        sa.Column("assigned_doctor_id", uid),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("acknowledged_at", ts),
        sa.Column("resolved_at", ts),
        sa.Column("created_at", ts, nullable=False),
        sa.Column("updated_at", ts, nullable=False),
        sa.ForeignKeyConstraint(["conversation_id", "clinic_id"], ["conversations.id", "conversations.clinic_id"]),
        sa.ForeignKeyConstraint(["patient_id", "clinic_id"], ["patients.id", "patients.clinic_id"]),
        sa.ForeignKeyConstraint(["assigned_staff_id", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        sa.ForeignKeyConstraint(["assigned_doctor_id", "clinic_id"], ["doctors.id", "doctors.clinic_id"]),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="severity"),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved')", name="status"),
        sa.CheckConstraint("source IN ('ai_receptionist','receptionist','doctor','system','manual')", name="source"),
        sa.CheckConstraint("(status = 'open' AND acknowledged_at IS NULL AND resolved_at IS NULL) OR (status = 'acknowledged' AND acknowledged_at IS NOT NULL AND resolved_at IS NULL) OR (status = 'resolved' AND acknowledged_at IS NOT NULL AND resolved_at IS NOT NULL)", name="lifecycle"))
    for field in ("clinic_id", "conversation_id", "patient_id", "assigned_staff_id"):
        op.create_index(f"ix_escalations_{field}", "escalations", [field])
    op.create_index("ix_escalations_clinic_status", "escalations", ["clinic_id", "status"])
    op.create_index("ix_escalations_clinic_severity", "escalations", ["clinic_id", "severity"])
    op.create_index("ix_escalations_clinic_created", "escalations", ["clinic_id", "created_at"])


def downgrade():
    op.drop_table("escalations")
