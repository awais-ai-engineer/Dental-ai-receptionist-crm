from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.api.deps import DB

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health():
    return {"status": "ok", "service": "aves-ai-receptionist-api"}


@router.get("/db")
async def database_health(db: DB):
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ok"}
