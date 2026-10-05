from uuid import UUID, uuid4

import pytest
from app.models import Clinic, Conversation

pytestmark = pytest.mark.integration
PREFIX = "/api/v1"


async def register(client, name, email):
    response = await client.post(f"{PREFIX}/auth/register", json={"clinic_name": name, "full_name": "Admin", "email": email, "password": "strong-password-123"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def create_patient(client, headers):
    response = await client.post(f"{PREFIX}/patients", headers=headers, json={"first_name": "Jane", "last_name": "Doe"})
    assert response.status_code == 201
    return response.json()["id"]


async def test_conversation_lifecycle_and_messages(api_client):
    client = api_client
    headers = await register(client, "Clinic A", "a@example.com")
    patient_id = await create_patient(client, headers)
    staff_id = (await client.get(f"{PREFIX}/auth/me", headers=headers)).json()["id"]
    created = await client.post(f"{PREFIX}/conversations", headers=headers, json={"channel": "manual", "subject": "Follow up"})
    assert created.status_code == 201, created.text
    item = created.json()
    conversation_id = item["id"]
    assert item["status"] == "active" and item["last_message_at"] is None
    assert (await client.get(f"{PREFIX}/conversations/{conversation_id}", headers=headers)).json()["subject"] == "Follow up"
    linked = await client.patch(f"{PREFIX}/conversations/{conversation_id}", headers=headers, json={"patient_id": patient_id, "assigned_staff_id": staff_id, "status": "waiting_for_staff"})
    assert linked.status_code == 200
    assert linked.json()["patient_id"] == patient_id and linked.json()["assigned_staff_id"] == staff_id
    for content in ("First", "Second", "Third"):
        response = await client.post(f"{PREFIX}/conversations/{conversation_id}/messages", headers=headers, json={"content": content})
        assert response.status_code == 201, response.text
        assert response.json()["sender_type"] == "staff" and response.json()["sender_staff_id"] == staff_id
    messages = (await client.get(f"{PREFIX}/conversations/{conversation_id}/messages", headers=headers)).json()
    assert [message["content"] for message in messages] == ["First", "Second", "Third"]
    assert len((await client.get(f"{PREFIX}/conversations/{conversation_id}/messages", headers=headers, params={"limit": 2, "offset": 1})).json()) == 2
    assert (await client.get(f"{PREFIX}/conversations/{conversation_id}", headers=headers)).json()["last_message_at"] is not None
    assert [entry["id"] for entry in (await client.get(f"{PREFIX}/conversations", headers=headers, params={"status": "waiting_for_staff", "channel": "manual", "patient_id": patient_id})).json()] == [conversation_id]
    assert (await client.get(f"{PREFIX}/conversations", headers=headers, params={"status": "closed"})).json() == []
    closed = await client.post(f"{PREFIX}/conversations/{conversation_id}/close", headers=headers)
    assert closed.status_code == 200 and closed.json()["status"] == "closed" and closed.json()["ended_at"] is not None
    assert (await client.post(f"{PREFIX}/conversations/{conversation_id}/messages", headers=headers, json={"content": "Too late"})).status_code == 409
    assert (await client.patch(f"{PREFIX}/conversations/{conversation_id}", headers=headers, json={"subject": "Reopen"})).status_code == 409
    assert (await client.post(f"{PREFIX}/conversations/{conversation_id}/close", headers=headers)).status_code == 409


async def test_invalid_links_and_validation(api_client):
    client = api_client
    headers = await register(client, "Clinic A", "a@example.com")
    assert (await client.post(f"{PREFIX}/conversations", headers=headers, json={"channel": "invalid"})).status_code == 422
    assert (await client.post(f"{PREFIX}/conversations", headers=headers, json={"channel": "phone", "patient_id": str(uuid4())})).status_code == 404
    created = await client.post(f"{PREFIX}/conversations", headers=headers, json={"channel": "phone"})
    conversation_id = created.json()["id"]
    assert (await client.patch(f"{PREFIX}/conversations/{conversation_id}", headers=headers, json={"assigned_staff_id": str(uuid4())})).status_code == 404
    assert (await client.patch(f"{PREFIX}/conversations/{conversation_id}", headers=headers, json={"status": "closed"})).status_code == 422
    assert (await client.post(f"{PREFIX}/conversations/{conversation_id}/messages", headers=headers, json={"content": ""})).status_code == 422
    guessed = uuid4()
    assert (await client.get(f"{PREFIX}/conversations/{guessed}", headers=headers)).status_code == 404
    assert (await client.get(f"{PREFIX}/conversations/{guessed}/messages", headers=headers)).status_code == 404


async def test_conversation_tenant_isolation(api_client):
    client = api_client
    a = await register(client, "Clinic A", "a@example.com")
    b = await register(client, "Clinic B", "b@example.com")
    patient_a, patient_b = await create_patient(client, a), await create_patient(client, b)
    staff_a = (await client.get(f"{PREFIX}/auth/me", headers=a)).json()["id"]
    staff_b = (await client.get(f"{PREFIX}/auth/me", headers=b)).json()["id"]
    conversation_a = (await client.post(f"{PREFIX}/conversations", headers=a, json={"channel": "manual", "patient_id": patient_a})).json()["id"]
    conversation_b = (await client.post(f"{PREFIX}/conversations", headers=b, json={"channel": "phone", "patient_id": patient_b})).json()["id"]
    await client.post(f"{PREFIX}/conversations/{conversation_b}/messages", headers=b, json={"content": "Private"})
    for headers, own, foreign, foreign_patient, foreign_staff in ((a, conversation_a, conversation_b, patient_b, staff_b), (b, conversation_b, conversation_a, patient_a, staff_a)):
        assert [item["id"] for item in (await client.get(f"{PREFIX}/conversations", headers=headers)).json()] == [own]
        assert (await client.get(f"{PREFIX}/conversations/{foreign}", headers=headers)).status_code == 404
        assert (await client.get(f"{PREFIX}/conversations/{foreign}/messages", headers=headers)).status_code == 404
        assert (await client.post(f"{PREFIX}/conversations/{foreign}/messages", headers=headers, json={"content": "Intruder"})).status_code == 404
        assert (await client.patch(f"{PREFIX}/conversations/{foreign}", headers=headers, json={"subject": "Intruder"})).status_code == 404
        assert (await client.post(f"{PREFIX}/conversations/{foreign}/close", headers=headers)).status_code == 404
        assert (await client.patch(f"{PREFIX}/conversations/{own}", headers=headers, json={"patient_id": foreign_patient})).status_code == 404
        assert (await client.patch(f"{PREFIX}/conversations/{own}", headers=headers, json={"assigned_staff_id": foreign_staff})).status_code == 404


async def test_public_website_chat_access(api_client, db_session):
    client = api_client
    staff_headers = await register(client, "Clinic A", "a@example.com")
    staff = (await client.get(f"{PREFIX}/auth/me", headers=staff_headers)).json()
    clinic = await db_session.get(Clinic, UUID(staff["clinic_id"]))
    assert (await client.post(f"{PREFIX}/reception/conversations", json={"clinic_slug": "missing-clinic"})).status_code == 404
    started = await client.post(f"{PREFIX}/reception/conversations", json={"clinic_slug": clinic.slug})
    assert started.status_code == 201, started.text
    assert set(started.json()) == {"conversation_id", "access_token"}
    conversation_id = started.json()["conversation_id"]
    token = started.json()["access_token"]
    stored = await db_session.get(Conversation, UUID(conversation_id))
    assert stored.public_access_token_hash != token
    assert stored.channel == "website_chat" and stored.patient_id is None
    url = f"{PREFIX}/reception/conversations/{conversation_id}/messages"
    assert (await client.get(url, headers={"X-Conversation-Token": "x" * 40})).status_code == 404
    assert (await client.get(url)).status_code == 422
    assert (await client.get(f"{PREFIX}/conversations/{conversation_id}")).status_code == 401
    message = await client.post(url, headers={"X-Conversation-Token": token}, json={"content": "I need an appointment"})
    assert message.status_code == 201 and message.json()["sender_type"] == "patient"
    assert "sender_staff_id" not in message.json()
    assert [entry["content"] for entry in (await client.get(url, headers={"X-Conversation-Token": token})).json()] == ["I need an appointment"]
    assert (await client.post(url, headers={"X-Conversation-Token": "x" * 40}, json={"content": "Intruder"})).status_code == 404
    assert (await client.get(f"{PREFIX}/conversations/{conversation_id}", headers=staff_headers)).status_code == 200
    assert (await client.post(f"{PREFIX}/conversations/{conversation_id}/close", headers=staff_headers)).status_code == 200
    assert (await client.post(url, headers={"X-Conversation-Token": token}, json={"content": "Too late"})).status_code == 409
