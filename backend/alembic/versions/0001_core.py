"""Core clinic, staff, doctor, patient and appointment schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    uid = postgresql.UUID(as_uuid=True)
    ts = sa.DateTime(timezone=True)
    op.create_table("clinics",
        sa.Column("id", uid, primary_key=True), sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(220), nullable=False, unique=True), sa.Column("phone", sa.String(40)),
        sa.Column("email", sa.String(320)), sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False), sa.Column("created_at", ts, nullable=False),
        sa.Column("updated_at", ts, nullable=False))
    op.create_table("staff_users",
        sa.Column("id", uid, primary_key=True), sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False), sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False), sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False), sa.Column("created_at", ts, nullable=False),
        sa.Column("updated_at", ts, nullable=False), sa.UniqueConstraint("email"),
        sa.UniqueConstraint("id", "clinic_id"), sa.CheckConstraint("role IN ('admin','receptionist','doctor')", name="role"))
    op.create_index("ix_staff_users_email", "staff_users", ["email"])
    op.create_index("ix_staff_users_clinic_id", "staff_users", ["clinic_id"])
    op.create_table("doctors",
        sa.Column("id", uid, primary_key=True), sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("staff_user_id", uid), sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("specialization", sa.String(200)), sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(40)), sa.Column("bio", sa.Text),
        sa.Column("consultation_duration_minutes", sa.Integer, nullable=False), sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", ts, nullable=False), sa.Column("updated_at", ts, nullable=False),
        sa.ForeignKeyConstraint(["staff_user_id", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        sa.UniqueConstraint("id", "clinic_id"), sa.CheckConstraint("consultation_duration_minutes > 0", name="duration"))
    op.create_index("ix_doctors_clinic_id", "doctors", ["clinic_id"])
    op.create_table("doctor_availability",
        sa.Column("id", uid, primary_key=True), sa.Column("doctor_id", uid, sa.ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day_of_week", sa.Integer, nullable=False), sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False), sa.Column("is_available", sa.Boolean, nullable=False),
        sa.Column("created_at", ts, nullable=False), sa.Column("updated_at", ts, nullable=False),
        sa.UniqueConstraint("doctor_id", "day_of_week", "start_time", "end_time"),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="weekday"),
        sa.CheckConstraint("start_time < end_time", name="time_order"))
    op.create_index("ix_doctor_availability_doctor_id", "doctor_availability", ["doctor_id"])
    op.create_table("patients",
        sa.Column("id", uid, primary_key=True), sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False), sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(320)), sa.Column("phone", sa.String(40)), sa.Column("date_of_birth", sa.Date),
        sa.Column("gender", sa.String(40)), sa.Column("preferred_doctor_id", uid), sa.Column("source", sa.String(80)),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("notes", sa.Text),
        sa.Column("emergency_flag", sa.Boolean, nullable=False), sa.Column("last_contacted_at", ts),
        sa.Column("created_at", ts, nullable=False), sa.Column("updated_at", ts, nullable=False),
        sa.ForeignKeyConstraint(["preferred_doctor_id", "clinic_id"], ["doctors.id", "doctors.clinic_id"]),
        sa.UniqueConstraint("id", "clinic_id"),
        sa.CheckConstraint("status IN ('lead','active','inactive','follow_up','urgent')", name="status"))
    for field in ("clinic_id", "email", "phone"):
        op.create_index(f"ix_patients_{field}", "patients", [field])
    op.create_table("appointments",
        sa.Column("id", uid, primary_key=True), sa.Column("clinic_id", uid, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("patient_id", uid, nullable=False), sa.Column("doctor_id", uid, nullable=False),
        sa.Column("scheduled_start", ts, nullable=False), sa.Column("scheduled_end", ts, nullable=False),
        sa.Column("reason", sa.Text), sa.Column("appointment_type", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("source", sa.String(80)),
        sa.Column("notes", sa.Text), sa.Column("created_by", uid),
        sa.Column("created_at", ts, nullable=False), sa.Column("updated_at", ts, nullable=False),
        sa.ForeignKeyConstraint(["patient_id", "clinic_id"], ["patients.id", "patients.clinic_id"]),
        sa.ForeignKeyConstraint(["doctor_id", "clinic_id"], ["doctors.id", "doctors.clinic_id"]),
        sa.ForeignKeyConstraint(["created_by", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]),
        sa.CheckConstraint("scheduled_start < scheduled_end", name="time_order"),
        sa.CheckConstraint("status IN ('requested','pending','approved','confirmed','completed','cancelled','no_show','rescheduled')", name="status"))
    op.create_index("ix_appointments_clinic_id", "appointments", ["clinic_id"])
    op.create_index("ix_appointments_doctor_start", "appointments", ["doctor_id", "scheduled_start"])
    op.execute("""ALTER TABLE appointments ADD CONSTRAINT appointments_no_doctor_overlap
        EXCLUDE USING gist (doctor_id WITH =, tstzrange(scheduled_start, scheduled_end, '[)') WITH &&)
        WHERE (status IN ('requested','pending','approved','confirmed'))""")


def downgrade():
    for table in ("appointments", "patients", "doctor_availability", "doctors", "staff_users", "clinics"):
        op.drop_table(table)
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS vector")
