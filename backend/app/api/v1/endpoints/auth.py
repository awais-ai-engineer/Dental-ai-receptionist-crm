import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, User
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Clinic, StaffUser
from app.schemas.core import Login, Register, StaffOut, Token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=201)
async def register(payload: Register, db: DB):
    if len(get_settings().jwt_secret_key) < 32:
        raise HTTPException(503, "Authentication is not configured")
    email = payload.email.lower()
    if await db.scalar(select(StaffUser.id).where(StaffUser.email == email)):
        raise HTTPException(409, "Email already registered")
    slug = re.sub(r"[^a-z0-9]+", "-", payload.clinic_name.lower()).strip("-") + "-" + uuid4().hex[:8]
    clinic = Clinic(name=payload.clinic_name, slug=slug)
    db.add(clinic)
    await db.flush()
    user = StaffUser(clinic_id=clinic.id, email=email, full_name=payload.full_name, hashed_password=hash_password(payload.password), role="admin")
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Registration conflict") from None
    return Token(access_token=create_access_token(user.id))


@router.post("/login", response_model=Token)
async def login(payload: Login, db: DB):
    user = await db.scalar(select(StaffUser).where(StaffUser.email == payload.email.lower(), StaffUser.is_active))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    clinic = await db.get(Clinic, user.clinic_id)
    if clinic is None or not clinic.is_active:
        raise HTTPException(401, "Invalid credentials")
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=StaffOut)
async def me(user: User):
    return user
