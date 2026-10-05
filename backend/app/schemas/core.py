from datetime import date, datetime, time, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Register(BaseModel):
    clinic_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class Login(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StaffOut(Out):
    id: UUID
    clinic_id: UUID
    email: EmailStr
    full_name: str
    role: str


class DoctorIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    specialization: str | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=40)
    bio: str | None = None
    consultation_duration_minutes: int = Field(default=30, gt=0, le=240)
    staff_user_id: UUID | None = None


class DoctorPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    specialization: str | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=40)
    bio: str | None = None
    consultation_duration_minutes: int | None = Field(default=None, gt=0, le=240)
    is_active: bool | None = None


class DoctorOut(Out):
    id: UUID
    clinic_id: UUID
    full_name: str
    specialization: str | None
    email: str | None
    phone: str | None
    bio: str | None
    consultation_duration_minutes: int
    is_active: bool


class AvailabilityIn(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    is_available: bool = True

    @model_validator(mode="after")
    def valid_hours(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self


class AvailabilityOut(Out):
    id: UUID
    doctor_id: UUID
    day_of_week: int
    start_time: time
    end_time: time
    is_available: bool


PatientStatus = Literal["lead", "active", "inactive", "follow_up", "urgent"]


class PatientIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=40)
    date_of_birth: date | None = None
    gender: str | None = None
    preferred_doctor_id: UUID | None = None
    source: str | None = None
    status: PatientStatus = "lead"
    notes: str | None = None
    emergency_flag: bool = False


class PatientPatch(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=40)
    date_of_birth: date | None = None
    gender: str | None = None
    preferred_doctor_id: UUID | None = None
    source: str | None = None
    status: PatientStatus | None = None
    notes: str | None = None
    emergency_flag: bool | None = None


class PatientOut(Out):
    id: UUID
    clinic_id: UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    date_of_birth: date | None
    gender: str | None
    preferred_doctor_id: UUID | None
    source: str | None
    status: str
    notes: str | None
    emergency_flag: bool


AppointmentStatus = Literal["requested", "pending", "approved", "confirmed", "completed", "cancelled", "no_show", "rescheduled"]


class AppointmentIn(BaseModel):
    patient_id: UUID
    doctor_id: UUID
    scheduled_start: datetime
    scheduled_end: datetime
    reason: str | None = None
    appointment_type: str | None = None
    source: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def valid_times(self):
        if self.scheduled_start.tzinfo is None or self.scheduled_end.tzinfo is None:
            raise ValueError("Appointment times must include a timezone")
        if self.scheduled_start <= datetime.now(timezone.utc) or self.scheduled_start >= self.scheduled_end:
            raise ValueError("Appointment must be in the future and end after start")
        if (self.scheduled_end - self.scheduled_start).total_seconds() > 4 * 3600:
            raise ValueError("Appointment may not exceed four hours")
        return self


class AppointmentPatch(BaseModel):
    reason: str | None = None
    appointment_type: str | None = None
    source: str | None = None
    notes: str | None = None


class Reschedule(BaseModel):
    scheduled_start: datetime
    scheduled_end: datetime

    @model_validator(mode="after")
    def valid_times(self):
        AppointmentIn(patient_id=UUID(int=0), doctor_id=UUID(int=0), scheduled_start=self.scheduled_start, scheduled_end=self.scheduled_end)
        return self


class AppointmentOut(Out):
    id: UUID
    clinic_id: UUID
    patient_id: UUID
    doctor_id: UUID
    scheduled_start: datetime
    scheduled_end: datetime
    reason: str | None
    appointment_type: str | None
    status: str
    source: str | None
    notes: str | None
    created_by: UUID | None
