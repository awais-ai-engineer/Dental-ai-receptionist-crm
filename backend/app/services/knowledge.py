import math
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import KnowledgeChunk, KnowledgeDocument
from app.models.knowledge import STORED_EMBEDDING_DIMENSION
from app.services.chunking import chunk_text


class EmbeddingClient(Protocol):
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class ChunkMatch:
    chunk_id: UUID
    document_id: UUID
    content: str
    metadata: dict
    distance: float


def validate_embedding(vector: list[float]) -> list[float]:
    dimension = get_settings().embedding_dimension
    if dimension != STORED_EMBEDDING_DIMENSION:
        raise RuntimeError(f"EMBEDDING_DIMENSION={dimension} does not match migrated vector({STORED_EMBEDDING_DIMENSION}); a schema migration is required")
    if len(vector) != dimension or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
        raise ValueError(f"Embedding must contain {dimension} finite numbers")
    if not any(vector):
        raise ValueError("Embedding must not be a zero vector for cosine search")
    return [float(value) for value in vector]


async def get_document(db: AsyncSession, clinic_id: UUID, document_id: UUID) -> KnowledgeDocument:
    item = await db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id, KnowledgeDocument.clinic_id == clinic_id))
    if item is None:
        raise HTTPException(404, "Knowledge document not found")
    return item


async def ingest_text(db: AsyncSession, clinic_id: UUID, title: str, source_type: str, content: str, created_by: UUID | None = None) -> KnowledgeDocument:
    settings = get_settings()
    chunks = chunk_text(content, settings.knowledge_chunk_size, settings.knowledge_chunk_overlap)
    document = KnowledgeDocument(clinic_id=clinic_id, title=title, source_type=source_type, status="pending", created_by=created_by)
    db.add(document)
    await db.flush()
    for index, chunk in enumerate(chunks):
        db.add(KnowledgeChunk(clinic_id=clinic_id, document_id=document.id, chunk_index=index, content=chunk, metadata_json={"source_type": source_type}))
    await db.commit()
    await db.refresh(document)
    return document


async def embed_document(db: AsyncSession, document: KnowledgeDocument, client: EmbeddingClient | None) -> KnowledgeDocument:
    if client is None:
        raise HTTPException(503, "Embedding provider is not configured")
    chunks = (await db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.clinic_id == document.clinic_id, KnowledgeChunk.document_id == document.id).order_by(KnowledgeChunk.chunk_index))).all()
    vectors = await client.embed_texts([chunk.content for chunk in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("Embedding provider returned the wrong number of vectors")
    validated = [validate_embedding(vector) for vector in vectors]
    for chunk, vector in zip(chunks, validated, strict=True):
        chunk.embedding = vector
    document.status = "ready"
    document.error_message = None
    await db.commit()
    await db.refresh(document)
    return document


async def search_chunks(db: AsyncSession, clinic_id: UUID, query_embedding: list[float], limit: int = 5) -> list[ChunkMatch]:
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")
    vector = validate_embedding(query_embedding)
    distance = KnowledgeChunk.embedding.cosine_distance(vector)
    rows = (await db.execute(select(KnowledgeChunk, distance.label("distance"))
        .join(KnowledgeDocument, (KnowledgeDocument.id == KnowledgeChunk.document_id) & (KnowledgeDocument.clinic_id == KnowledgeChunk.clinic_id))
        .where(KnowledgeChunk.clinic_id == clinic_id, KnowledgeDocument.status == "ready", KnowledgeChunk.embedding.is_not(None))
        .order_by(distance, KnowledgeChunk.id).limit(limit))).all()
    return [ChunkMatch(chunk_id=chunk.id, document_id=chunk.document_id, content=chunk.content, metadata=chunk.metadata_json, distance=float(score)) for chunk, score in rows]
