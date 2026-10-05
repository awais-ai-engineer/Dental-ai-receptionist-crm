from uuid import UUID

import pytest
from sqlalchemy import select

from app.main import app
from app.models import KnowledgeDocument, Message
from app.services.providers import ProviderError, get_embedding_client, get_llm_client
PREFIX = "/api/v1"


def vector(first, second=0):
    return [first, second] + [0.0] * 1534


async def register(client, name, email):
    response = await client.post(f"{PREFIX}/auth/register", json={"clinic_name": name, "full_name": "Admin", "email": email, "password": "strong-password-123"})
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    clinic_id = (await client.get(f"{PREFIX}/auth/me", headers=headers)).json()["clinic_id"]
    return headers, UUID(clinic_id)


async def create_document(client, headers, title, content):
    response = await client.post(f"{PREFIX}/knowledge/documents", headers=headers, json={"title": title, "content": content})
    assert response.status_code == 201, response.text
    return response.json()


class FakeEmbeddings:
    def __init__(self, fail=False):
        self.fail = fail

    async def embed_texts(self, texts):
        if self.fail:
            raise ProviderError("AI provider timed out", 504)
        return [vector(0, 1) if "unknown" in text.lower() else vector(1, 0) for text in texts]


class FakeLLM:
    def __init__(self, fail=False):
        self.fail = fail
        self.messages = []

    async def complete(self, messages):
        self.messages.append(messages)
        if self.fail:
            raise ProviderError("AI provider timed out", 504)
        return "The clinic offers dental cleaning."


@pytest.mark.integration
async def test_processing_rag_and_public_persistence(api_client, db_session):
    embed, llm = FakeEmbeddings(), FakeLLM()
    app.dependency_overrides[get_embedding_client] = lambda: embed
    app.dependency_overrides[get_llm_client] = lambda: llm
    try:
        headers, clinic_id = await register(api_client, "Clinic A", "rag-a@example.com")
        other, _ = await register(api_client, "Clinic B", "rag-b@example.com")
        document = await create_document(api_client, headers, "Services", "Clinic A offers dental cleaning.")
        other_doc = await create_document(api_client, other, "Secret", "Clinic B offers cosmetic work.")
        assert (await api_client.post(f"{PREFIX}/knowledge/documents/{other_doc['id']}/process", headers=headers)).status_code == 404
        processed = await api_client.post(f"{PREFIX}/knowledge/documents/{document['id']}/process", headers=headers)
        assert processed.status_code == 200 and processed.json()["status"] == "ready"
        assert (await api_client.post(f"{PREFIX}/knowledge/documents/{document['id']}/process", headers=headers)).json()["status"] == "ready"
        answer = await api_client.post(f"{PREFIX}/knowledge/query", headers=headers, json={"question": "Do you offer dental cleaning?"})
        assert answer.status_code == 200, answer.text
        assert answer.json()["sources"][0]["document_id"] == document["id"]
        assert answer.json()["sources"][0]["document_title"] == "Services"
        assert "Clinic A offers dental cleaning" in llm.messages[0][1]["content"]
        assert "Clinic B" not in llm.messages[0][1]["content"]
        unknown = await api_client.post(f"{PREFIX}/knowledge/query", headers=headers, json={"question": "unknown price?"})
        assert unknown.status_code == 200 and unknown.json()["sources"] == []
        assert "confirmed" in unknown.json()["answer"]
        assert len(llm.messages) == 1
        clinic_slug = (await api_client.get(f"{PREFIX}/auth/me", headers=headers)).json().get("clinic_slug")
        if not clinic_slug:
            from app.models import Clinic
            clinic_slug = (await db_session.get(Clinic, clinic_id)).slug
        started = await api_client.post(f"{PREFIX}/reception/conversations", json={"clinic_slug": clinic_slug})
        assert started.status_code == 201, started.text
        cid, token = started.json()["conversation_id"], started.json()["access_token"]
        path = f"{PREFIX}/reception/conversations/{cid}/ask"
        assert (await api_client.post(path, headers={"X-Conversation-Token": "x" * 32}, json={"content": "Do you offer dental cleaning?"})).status_code == 404
        asked = await api_client.post(path, headers={"X-Conversation-Token": token}, json={"content": "Do you offer dental cleaning?"})
        assert asked.status_code == 200 and asked.json()["sources"][0]["document_id"] == document["id"]
        messages = (await db_session.scalars(select(Message).where(Message.conversation_id == UUID(cid)).order_by(Message.created_at))).all()
        assert [m.sender_type for m in messages] == ["patient", "ai"]
        assert (await api_client.get(f"{PREFIX}/reception/conversations/{cid}/messages", headers={"X-Conversation-Token": token})).json()[-1]["content"] == asked.json()["answer"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
async def test_provider_failures_mark_document_failed_and_do_not_fake_reply(api_client, db_session):
    embed, llm = FakeEmbeddings(fail=True), FakeLLM()
    app.dependency_overrides[get_embedding_client] = lambda: embed
    app.dependency_overrides[get_llm_client] = lambda: llm
    try:
        headers, clinic_id = await register(api_client, "Clinic A", "rag-fail@example.com")
        doc = await create_document(api_client, headers, "Services", "Clinic A offers dental cleaning.")
        response = await api_client.post(f"{PREFIX}/knowledge/documents/{doc['id']}/process", headers=headers)
        assert response.status_code == 504
        assert (await db_session.get(KnowledgeDocument, UUID(doc["id"]))).status == "failed"
        embed.fail = False
        assert (await api_client.post(f"{PREFIX}/knowledge/documents/{doc['id']}/process", headers=headers)).json()["status"] == "ready"
        llm.fail = True
        from app.models import Clinic
        slug = (await db_session.get(Clinic, clinic_id)).slug
        started = (await api_client.post(f"{PREFIX}/reception/conversations", json={"clinic_slug": slug})).json()
        cid, token = started["conversation_id"], started["access_token"]
        asked = await api_client.post(f"{PREFIX}/reception/conversations/{cid}/ask", headers={"X-Conversation-Token": token}, json={"content": "Do you offer cleaning?"})
        assert asked.status_code == 504
        messages = (await db_session.scalars(select(Message).where(Message.conversation_id == UUID(cid)))).all()
        assert [m.sender_type for m in messages] == ["patient"]
    finally:
        app.dependency_overrides.clear()
