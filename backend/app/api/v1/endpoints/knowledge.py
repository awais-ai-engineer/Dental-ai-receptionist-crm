from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DB, User, require_roles
from app.models import KnowledgeChunk, KnowledgeDocument, StaffUser
from app.schemas.knowledge import ChunkRead, DocumentCreate, DocumentRead, DocumentStatus, DocumentUpdate
from app.services.knowledge import get_document, ingest_text

router = APIRouter(prefix="/knowledge/documents", tags=["knowledge"])
Manager = Annotated[StaffUser, Depends(require_roles("admin", "receptionist"))]


@router.post("", response_model=DocumentRead, status_code=201)
async def create(payload: DocumentCreate, db: DB, user: Manager):
    return await ingest_text(db, user.clinic_id, payload.title, payload.source_type, payload.content, user.id)


@router.get("", response_model=list[DocumentRead])
async def list_documents(db: DB, user: User, status: DocumentStatus | None = None,
                         limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    query = select(KnowledgeDocument).where(KnowledgeDocument.clinic_id == user.clinic_id)
    if status:
        query = query.where(KnowledgeDocument.status == status)
    return (await db.scalars(query.order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc()).limit(limit).offset(offset))).all()


@router.get("/{document_id}", response_model=DocumentRead)
async def read(document_id: UUID, db: DB, user: User):
    return await get_document(db, user.clinic_id, document_id)


@router.patch("/{document_id}", response_model=DocumentRead)
async def update(document_id: UUID, payload: DocumentUpdate, db: DB, user: Manager):
    document = await get_document(db, user.clinic_id, document_id)
    document.title = payload.title
    await db.commit()
    await db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=204)
async def delete(document_id: UUID, db: DB, user: Manager):
    document = await get_document(db, user.clinic_id, document_id)
    await db.delete(document)
    await db.commit()


@router.get("/{document_id}/chunks", response_model=list[ChunkRead])
async def list_chunks(document_id: UUID, db: DB, user: User, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    await get_document(db, user.clinic_id, document_id)
    return (await db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.clinic_id == user.clinic_id, KnowledgeChunk.document_id == document_id).order_by(KnowledgeChunk.chunk_index).limit(limit).offset(offset))).all()
