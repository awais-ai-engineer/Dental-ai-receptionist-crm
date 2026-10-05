from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DB, User
from app.services.providers import ProviderError, get_embedding_client, get_llm_client
from app.services.rag import Answer, answer_question

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10000)


@router.post("/query", response_model=Answer)
async def query(payload: QueryRequest, db: DB, user: User,
                embedding_client=Depends(get_embedding_client), llm_client=Depends(get_llm_client)):
    try:
        return await answer_question(db, user.clinic_id, payload.question.strip(), embedding_client, llm_client)
    except ProviderError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
