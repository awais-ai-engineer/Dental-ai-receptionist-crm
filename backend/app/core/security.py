from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 characters")
    return jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UUID:
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise InvalidTokenError("Authentication is not configured")
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return UUID(payload["sub"])
