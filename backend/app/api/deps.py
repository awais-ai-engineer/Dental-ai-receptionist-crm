from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Clinic, StaffUser

DB = Annotated[AsyncSession, Depends(get_db)]
bearer = HTTPBearer(auto_error=False)


async def current_user(db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> StaffUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        user_id = decode_access_token(credentials.credentials)
    except (InvalidTokenError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None
    user = await db.get(StaffUser, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    clinic = await db.get(Clinic, user.clinic_id)
    if clinic is None or not clinic.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    return user


User = Annotated[StaffUser, Depends(current_user)]


def require_roles(*roles: str):
    async def check(user: User) -> StaffUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user
    return check
