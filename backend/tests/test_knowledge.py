from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.demo.aves_knowledge import DEMO_DOCUMENTS, seed_aves_knowledge
from app.models import KnowledgeChunk, KnowledgeDocument
from app.services.chunking import chunk_text
from app.services.knowledge import embed_document, search_chunks, validate_embedding

PREFIX = "/api/v1"


def vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second] + [0.0] * 1534


class TestEmbeddingClient:
    __test__ = False

    def __init__(self, vectors):
        self.vectors = vectors
        self.texts = None

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.texts = texts
        return self.vectors


def test_chunking_is_deterministic_and_paragraph_aware():
    text = "First paragraph has useful details.\n\nSecond paragraph adds more context.\n\n" + "Extra words " * 45
    first = chunk_text(text, size=200, overlap=30)
    assert first == chunk_text(text, size=200, overlap=30)
    assert len(first) > 1
    assert first[0].startswith("First paragraph")
    assert all(chunk and len(chunk) <= 200 for chunk in first)
    assert "Second paragraph" in " ".join(first)
    with pytest.raises(ValueError):
        chunk_text("  \n \n ")
    with pytest.raises(ValueError):
        chunk_text("content", size=100, overlap=100)


def test_embedding_vector_validation():
    assert len(validate_embedding(vector(1.0))) == 1536
    for bad in ([1.0], vector(float("nan")), vector(float("inf")), vector(0.0), [True] + [0.0] * 1535):
        with pytest.raises(ValueError):
            validate_embedding(bad)


def test_embedding_dimension_mismatch_is_explicit(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setenv("EMBEDDING_DIMENSION", "8")
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="schema migration is required"):
            validate_embedding([1.0] + [0.0] * 7)
    get_settings.cache_clear()


async def register(client, name, email):
    response = await client.post(f"{PREFIX}/auth/register", json={"clinic_name": name, "full_name": "Admin", "email": email, "password": "strong-password-123"})
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    clinic_id = (await client.get(f"{PREFIX}/auth/me", headers=headers)).json()["clinic_id"]
    return headers, UUID(clinic_id)


async def create_document(client, headers, title="Opening hours", content="The clinic opens at nine in the morning."):
    response = await client.post(f"{PREFIX}/knowledge/documents", headers=headers, json={"title": title, "source_type": "manual", "content": content})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
async def test_document_crud_chunks_and_deletion(api_client, db_session):
    client = api_client
    headers, clinic_id = await register(client, "Clinic A", "a@example.com")
    assert (await client.get(f"{PREFIX}/knowledge/documents")).status_code == 401
    assert (await client.post(f"{PREFIX}/knowledge/documents", headers=headers, json={"title": "Blank", "content": "  "})).status_code == 422
    assert (await client.post(f"{PREFIX}/knowledge/documents", headers=headers, json={"title": "PDF", "source_type": "pdf", "content": "Not supported"})).status_code == 422
    text = "Aves Dental Clinic is open on weekdays. " * 80
    created = await create_document(client, headers, content=text)
    document_id = created["id"]
    assert created["status"] == "pending" and created["created_by"] is not None
    assert (await client.get(f"{PREFIX}/knowledge/documents/{document_id}", headers=headers)).status_code == 200
    assert [item["id"] for item in (await client.get(f"{PREFIX}/knowledge/documents", headers=headers, params={"status": "pending"})).json()] == [document_id]
    chunks = (await client.get(f"{PREFIX}/knowledge/documents/{document_id}/chunks", headers=headers)).json()
    assert len(chunks) > 1
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk["metadata"] == {"source_type": "manual"} for chunk in chunks)
    assert (await client.get(f"{PREFIX}/knowledge/documents/{document_id}/chunks", headers=headers, params={"limit": 1, "offset": 1})).json()[0]["chunk_index"] == 1
    updated = await client.patch(f"{PREFIX}/knowledge/documents/{document_id}", headers=headers, json={"title": "Updated hours"})
    assert updated.status_code == 200 and updated.json()["title"] == "Updated hours"
    assert (await client.patch(f"{PREFIX}/knowledge/documents/{document_id}", headers=headers, json={"status": "ready"})).status_code == 422
    assert (await client.delete(f"{PREFIX}/knowledge/documents/{document_id}", headers=headers)).status_code == 204
    assert (await client.get(f"{PREFIX}/knowledge/documents/{document_id}", headers=headers)).status_code == 404
    assert await db_session.scalar(select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == UUID(document_id))) == 0


@pytest.mark.integration
async def test_embedding_storage_search_and_tenant_isolation(api_client, db_session):
    client = api_client
    a, clinic_a = await register(client, "Clinic A", "a@example.com")
    b, clinic_b = await register(client, "Clinic B", "b@example.com")
    doc_a = await create_document(client, a, "A knowledge", "Clinic A offers dental cleaning.")
    doc_b = await create_document(client, b, "B knowledge", "Clinic B offers orthodontics.")
    id_a, id_b = UUID(doc_a["id"]), UUID(doc_b["id"])
    for method, path, payload in (("get", f"{PREFIX}/knowledge/documents/{id_b}", None),
                                  ("get", f"{PREFIX}/knowledge/documents/{id_b}/chunks", None),
                                  ("patch", f"{PREFIX}/knowledge/documents/{id_b}", {"title": "Intruder"}),
                                  ("delete", f"{PREFIX}/knowledge/documents/{id_b}", None)):
        response = await getattr(client, method)(path, headers=a, **({"json": payload} if payload else {}))
        assert response.status_code == 404
    assert [item["id"] for item in (await client.get(f"{PREFIX}/knowledge/documents", headers=a)).json()] == [str(id_a)]
    assert [item["id"] for item in (await client.get(f"{PREFIX}/knowledge/documents", headers=b)).json()] == [str(id_b)]
    db_session.add(KnowledgeChunk(clinic_id=clinic_b, document_id=id_a, chunk_index=99, content="Cross-clinic injection", metadata_json={}))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    document_a = await db_session.get(KnowledgeDocument, id_a)
    document_b = await db_session.get(KnowledgeDocument, id_b)
    with pytest.raises(Exception) as missing_provider:
        await embed_document(db_session, document_a, None)
    assert "not configured" in str(missing_provider.value)
    client_a = TestEmbeddingClient([vector(0.0, 1.0)])
    client_b = TestEmbeddingClient([vector(1.0, 0.0)])
    await embed_document(db_session, document_a, client_a)
    await embed_document(db_session, document_b, client_b)
    assert client_a.texts == ["Clinic A offers dental cleaning."]
    stored = await db_session.scalar(select(KnowledgeChunk).where(KnowledgeChunk.document_id == id_a))
    assert len(stored.embedding) == 1536
    assert (await client.get(f"{PREFIX}/knowledge/documents/{id_a}", headers=a)).json()["status"] == "ready"
    results_a = await search_chunks(db_session, clinic_a, vector(1.0, 0.0))
    results_b = await search_chunks(db_session, clinic_b, vector(1.0, 0.0))
    assert [match.document_id for match in results_a] == [id_a]
    assert [match.document_id for match in results_b] == [id_b]
    assert results_a[0].distance > results_b[0].distance
    assert results_a[0].metadata == {"source_type": "manual"}
    assert (await client.delete(f"{PREFIX}/knowledge/documents/{id_b}", headers=a)).status_code == 404


@pytest.mark.integration
async def test_embedding_failure_does_not_mark_ready(api_client, db_session):
    client = api_client
    headers, clinic_id = await register(client, "Clinic A", "a@example.com")
    document = await create_document(client, headers, "Policies", "Cancel appointments with staff.")
    stored = await db_session.get(KnowledgeDocument, UUID(document["id"]))
    with pytest.raises(ValueError):
        await embed_document(db_session, stored, TestEmbeddingClient([[1.0, 2.0]]))
    assert (await client.get(f"{PREFIX}/knowledge/documents/{document['id']}", headers=headers)).json()["status"] == "pending"
    assert await search_chunks(db_session, clinic_id, vector(1.0)) == []


@pytest.mark.integration
async def test_optional_demo_seed_is_idempotent(api_client, db_session):
    client = api_client
    headers, clinic_id = await register(client, "Aves Dental Clinic", "aves@example.com")
    assert await seed_aves_knowledge(db_session, clinic_id) == len(DEMO_DOCUMENTS)
    assert await seed_aves_knowledge(db_session, clinic_id) == 0
    documents = (await client.get(f"{PREFIX}/knowledge/documents", headers=headers)).json()
    assert len(documents) == len(DEMO_DOCUMENTS)
    assert all(item["status"] == "pending" for item in documents)
    contents = (await db_session.scalars(select(KnowledgeChunk.content).where(KnowledgeChunk.clinic_id == clinic_id))).all()
    combined = " ".join(contents)
    for phrase in ("Dr. Sara Khan", "Dr. Michael Reed", "Dr. Emily Carter", "Dr. Daniel Brooks", "$40", "Sunday closed", "must not diagnose", "Do not invent prices"):
        assert phrase in combined
