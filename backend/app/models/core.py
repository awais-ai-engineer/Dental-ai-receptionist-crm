from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Identified, Timestamped, clinic_fk


class Clinic(Identified, Timestamped, Base):
    __tablename__ = "clinics"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(220), unique=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(320))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StaffUser(Identified, Timestamped, Base):
    __tablename__ = "staff_users"
    __table_args__ = (UniqueConstraint("email"), CheckConstraint("role IN ('admin','receptionist','doctor')", name="role"), UniqueConstraint("id", "clinic_id"))
    clinic_id: Mapped[UUID] = clinic_fk()
    email: Mapped[str] = mapped_column(String(320), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Doctor(Identified, Timestamped, Base):
    __tablename__ = "doctors"
    __table_args__ = (ForeignKeyConstraint(["staff_user_id", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]), UniqueConstraint("id", "clinic_id"), CheckConstraint("consultation_duration_minutes > 0", name="duration"))
    clinic_id: Mapped[UUID] = clinic_fk()
    staff_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    full_name: Mapped[str] = mapped_column(String(200))
    specialization: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    bio: Mapped[str | None] = mapped_column(Text)
    consultation_duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    availability: Mapped[list["DoctorAvailability"]] = relationship(back_populates="doctor", cascade="all, delete-orphan")


class DoctorAvailability(Identified, Timestamped, Base):
    __tablename__ = "doctor_availability"
    __table_args__ = (CheckConstraint("day_of_week BETWEEN 0 AND 6", name="weekday"), CheckConstraint("start_time < end_time", name="time_order"), UniqueConstraint("doctor_id", "day_of_week", "start_time", "end_time"))
    doctor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    doctor: Mapped[Doctor] = relationship(back_populates="availability")


class Patient(Identified, Timestamped, Base):
    __tablename__ = "patients"
    __table_args__ = (ForeignKeyConstraint(["preferred_doctor_id", "clinic_id"], ["doctors.id", "doctors.clinic_id"]), UniqueConstraint("id", "clinic_id"), CheckConstraint("status IN ('lead','active','inactive','follow_up','urgent')", name="status"))
    clinic_id: Mapped[UUID] = clinic_fk()
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(40))
    preferred_doctor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="lead")
    notes: Mapped[str | None] = mapped_column(Text)
    emergency_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Appointment(Identified, Timestamped, Base):
    __tablename__ = "appointments"
    __table_args__ = (ForeignKeyConstraint(["patient_id", "clinic_id"], ["patients.id", "patients.clinic_id"]), ForeignKeyConstraint(["doctor_id", "clinic_id"], ["doctors.id", "doctors.clinic_id"]), ForeignKeyConstraint(["created_by", "clinic_id"], ["staff_users.id", "staff_users.clinic_id"]), CheckConstraint("scheduled_start < scheduled_end", name="time_order"), CheckConstraint("status IN ('requested','pending','approved','confirmed','completed','cancelled','no_show','rescheduled')", name="status"), Index("ix_appointments_doctor_start", "doctor_id", "scheduled_start"))
    clinic_id: Mapped[UUID] = clinic_fk()
    patient_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    doctor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    appointment_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="requested")
    source: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
