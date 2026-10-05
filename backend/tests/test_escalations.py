from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models import Clinic, Doctor, Escalation, StaffUser
from app.services.escalations import escalation_created_payload, notification_recipients, recipient_roles

pytestmark = pytest.mark.integration
PREFIX = "/api/v1"


async def register(client, name, email):
    response = await client.post(f"{PREFIX}/auth/register", json={"clinic_name": name, "full_name": "Admin", "email": email, "password": "strong-password-123"})
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    return headers, (await client.get(f"{PREFIX}/auth/me", headers=headers)).json()


async def add_staff(db, clinic_id, email, role):
    user = StaffUser(clinic_id=UUID(clinic_id), email=email, full_name=email.split("@")[0], hashed_password=hash_password("strong-password-123"), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_patient(client, headers):
    response = await client.post(f"{PREFIX}/patients", headers=headers, json={"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com", "phone": "+15551234567"})
    assert response.status_code == 201
    return response.json()["id"]


async def create_conversation(client, headers, patient_id=None):
    response = await client.post(f"{PREFIX}/conversations", headers=headers, json={"channel": "manual", "patient_id": patient_id})
    assert response.status_code == 201
    return response.json()["id"]


async def test_escalation_lifecycle_and_conversation_atomicity(api_client, db_session):
    client = api_client
    headers, admin = await register(client, "Clinic A", "admin@example.com")
    patient = await create_patient(client, headers)
    conversation = await create_conversation(client, headers, patient)
    handoff = await client.post(f"{PREFIX}/conversations/{conversation}/handoff", headers=headers)
    assert handoff.status_code == 200 and handoff.json()["status"] == "waiting_for_staff"
    assert (await client.patch(f"{PREFIX}/conversations/{conversation}", headers=headers, json={"assigned_staff_id": admin["id"]})).status_code == 200
    bad = await client.post(f"{PREFIX}/escalations", headers=headers, json={"conversation_id": conversation, "assigned_doctor_id": str(uuid4()), "severity": "high", "reason": "Needs review"})
    assert bad.status_code == 404
    assert (await client.get(f"{PREFIX}/conversations/{conversation}", headers=headers)).json()["status"] == "waiting_for_staff"
    created = await client.post(f"{PREFIX}/escalations", headers=headers, json={"conversation_id": conversation, "severity": "high", "reason": "  Needs prompt staff review  ", "summary": "Call patient"})
    assert created.status_code == 201, created.text
    item = created.json()
    escalation_id = item["id"]
    assert item["patient_id"] == patient and item["source"] == "manual" and item["reason"] == "Needs prompt staff review"
    assert item["assigned_staff_id"] == admin["id"]
    assert item["status"] == "open" and item["acknowledged_at"] is None and item["resolved_at"] is None
    assert (await client.get(f"{PREFIX}/conversations/{conversation}", headers=headers)).json()["status"] == "escalated"
    assert (await client.get(f"{PREFIX}/escalations/{escalation_id}", headers=headers)).status_code == 200
    assert [entry["id"] for entry in (await client.get(f"{PREFIX}/escalations", headers=headers, params={"status": "open", "severity": "high", "patient_id": patient, "conversation_id": conversation})).json()] == [escalation_id]
    assert (await client.post(f"{PREFIX}/escalations/{escalation_id}/resolve", headers=headers)).status_code == 409
    updated = await client.patch(f"{PREFIX}/escalations/{escalation_id}", headers=headers, json={"summary": "Staff called patient"})
    assert updated.status_code == 200 and updated.json()["summary"] == "Staff called patient"
    acknowledged = await client.post(f"{PREFIX}/escalations/{escalation_id}/acknowledge", headers=headers)
    assert acknowledged.status_code == 200 and acknowledged.json()["status"] == "acknowledged" and acknowledged.json()["acknowledged_at"]
    assert acknowledged.json()["assigned_staff_id"] == admin["id"]
    assert (await client.get(f"{PREFIX}/conversations/{conversation}", headers=headers)).json()["assigned_staff_id"] == admin["id"]
    assert (await client.post(f"{PREFIX}/escalations/{escalation_id}/acknowledge", headers=headers)).status_code == 409
    resolved = await client.post(f"{PREFIX}/escalations/{escalation_id}/resolve", headers=headers)
    assert resolved.status_code == 200 and resolved.json()["status"] == "resolved" and resolved.json()["resolved_at"]
    assert (await client.patch(f"{PREFIX}/escalations/{escalation_id}", headers=headers, json={"summary": "Changed"})).status_code == 409
    stored = await db_session.get(Escalation, UUID(escalation_id))
    assert stored.resolved_at is not None


async def test_assignment_permissions_and_recipient_routing(api_client, db_session):
    client = api_client
    headers, admin = await register(client, "Clinic A", "admin@example.com")
    receptionist = await add_staff(db_session, admin["clinic_id"], "reception@example.com", "receptionist")
    duplicate_case = await add_staff(db_session, admin["clinic_id"], "RECEPTION@example.com", "receptionist")
    doctor_user = await add_staff(db_session, admin["clinic_id"], "doctor@example.com", "doctor")
    doctor_response = await client.post(f"{PREFIX}/doctors", headers=headers, json={"full_name": "Dr Smith", "staff_user_id": str(doctor_user.id)})
    assert doctor_response.status_code == 201
    doctor_id = doctor_response.json()["id"]
    patient = await create_patient(client, headers)
    assert recipient_roles("appointment.requested") == ("receptionist",)
    for severity, expected_roles in (("low", {"receptionist"}), ("medium", {"receptionist"}), ("high", {"receptionist", "admin"}), ("critical", {"receptionist", "admin", "doctor"})):
        payload = {"severity": severity, "reason": "Staff follow-up", "patient_id": patient}
        if severity == "critical":
            payload["assigned_doctor_id"] = doctor_id
        response = await client.post(f"{PREFIX}/escalations", headers=headers, json=payload)
        assert response.status_code == 201, response.text
        item = await db_session.get(Escalation, UUID(response.json()["id"]))
        recipients = await notification_recipients(db_session, item)
        assert {recipient.role for recipient in recipients} == expected_roles
        assert len({recipient.email.casefold() for recipient in recipients}) == len(recipients)
        event = await escalation_created_payload(db_session, item)
        assert event["event"] == "escalation.created" and event["event_id"] == str(item.id)
        assert event["data"]["patient"]["email"] == "jane@example.com"
        assert {entry["role"] for entry in event["data"]["recipients"]} == expected_roles
    no_doctor = await client.post(f"{PREFIX}/escalations", headers=headers, json={"severity": "critical", "reason": "Urgent review"})
    item = await db_session.get(Escalation, UUID(no_doctor.json()["id"]))
    assert {user.role for user in await notification_recipients(db_session, item)} == {"receptionist", "admin"}
    assigned = await client.patch(f"{PREFIX}/escalations/{no_doctor.json()['id']}", headers=headers, json={"assigned_staff_id": str(receptionist.id), "assigned_doctor_id": doctor_id})
    assert assigned.status_code == 200 and assigned.json()["assigned_doctor_id"] == doctor_id
    receptionist_login = await client.post(f"{PREFIX}/auth/login", json={"email": receptionist.email, "password": "strong-password-123"})
    receptionist_headers = {"Authorization": f"Bearer {receptionist_login.json()['access_token']}"}
    assert (await client.patch(f"{PREFIX}/escalations/{no_doctor.json()['id']}", headers=receptionist_headers, json={"severity": "low"})).status_code == 403
    assert (await client.post(f"{PREFIX}/escalations/{no_doctor.json()['id']}/acknowledge", headers=receptionist_headers)).status_code == 200
    assert (await client.post(f"{PREFIX}/escalations/{no_doctor.json()['id']}/resolve", headers=receptionist_headers)).status_code == 403
    doctor_login = await client.post(f"{PREFIX}/auth/login", json={"email": doctor_user.email, "password": "strong-password-123"})
    doctor_headers = {"Authorization": f"Bearer {doctor_login.json()['access_token']}"}
    assert (await client.get(f"{PREFIX}/escalations/{no_doctor.json()['id']}", headers=doctor_headers)).status_code == 200
    assert (await client.post(f"{PREFIX}/escalations/{no_doctor.json()['id']}/resolve", headers=doctor_headers)).status_code == 200
    assert (await client.patch(f"{PREFIX}/escalations/{no_doctor.json()['id']}", headers=doctor_headers, json={"summary": "No"})).status_code == 409
    doctor_created = await client.post(f"{PREFIX}/escalations", headers=doctor_headers, json={"severity": "medium", "reason": "Doctor requested follow-up"})
    assert doctor_created.status_code == 201 and doctor_created.json()["assigned_doctor_id"] == doctor_id
    assert (await client.get(f"{PREFIX}/escalations/{doctor_created.json()['id']}", headers=doctor_headers)).status_code == 200
    assert duplicate_case.id != receptionist.id


async def test_tenant_isolation_and_validation(api_client, db_session):
    client = api_client
    a, admin_a = await register(client, "Clinic A", "a@example.com")
    b, admin_b = await register(client, "Clinic B", "b@example.com")
    patient_a, patient_b = await create_patient(client, a), await create_patient(client, b)
    conversation_a, conversation_b = await create_conversation(client, a, patient_a), await create_conversation(client, b, patient_b)
    staff_b = await add_staff(db_session, admin_b["clinic_id"], "staffb@example.com", "receptionist")
    doctor_b = (await client.post(f"{PREFIX}/doctors", headers=b, json={"full_name": "Dr B"})).json()["id"]
    escalation_a = (await client.post(f"{PREFIX}/escalations", headers=a, json={"severity": "low", "reason": "Follow up", "conversation_id": conversation_a})).json()["id"]
    escalation_b = (await client.post(f"{PREFIX}/escalations", headers=b, json={"severity": "low", "reason": "Follow up", "conversation_id": conversation_b})).json()["id"]
    for headers, own, foreign in ((a, escalation_a, escalation_b), (b, escalation_b, escalation_a)):
        assert [item["id"] for item in (await client.get(f"{PREFIX}/escalations", headers=headers)).json()] == [own]
        for action in (None, "acknowledge", "resolve"):
            path = f"{PREFIX}/escalations/{foreign}" + (f"/{action}" if action else "")
            response = await (client.get(path, headers=headers) if action is None else client.post(path, headers=headers))
            assert response.status_code == 404
        assert (await client.patch(f"{PREFIX}/escalations/{foreign}", headers=headers, json={"summary": "Intruder"})).status_code == 404
    for field, value in (("patient_id", patient_b), ("conversation_id", conversation_b), ("assigned_staff_id", str(staff_b.id)), ("assigned_doctor_id", doctor_b)):
        assert (await client.post(f"{PREFIX}/escalations", headers=a, json={"severity": "high", "reason": "Follow up", field: value})).status_code == 404
        assert (await client.patch(f"{PREFIX}/escalations/{escalation_a}", headers=a, json={field: value})).status_code in (404, 422)
    assert (await client.post(f"{PREFIX}/escalations", headers=a, json={"severity": "invalid", "reason": "Follow up"})).status_code == 422
    assert (await client.post(f"{PREFIX}/escalations", headers=a, json={"severity": "low", "reason": "   "})).status_code == 422
    assert (await client.post(f"{PREFIX}/escalations", headers=a, json={"severity": "low", "reason": "Wrong patient", "conversation_id": conversation_a, "patient_id": patient_b})).status_code == 409


async def test_public_handoff_token_scope(api_client, db_session):
    client = api_client
    headers, admin = await register(client, "Clinic A", "a@example.com")
    clinic = await db_session.get(Clinic, UUID(admin["clinic_id"]))
    endpoint = f"{PREFIX}/reception/conversations"
    first = (await client.post(endpoint, json={"clinic_slug": clinic.slug})).json()
    second = (await client.post(endpoint, json={"clinic_slug": clinic.slug})).json()
    first_url = f"{endpoint}/{first['conversation_id']}/handoff"
    second_url = f"{endpoint}/{second['conversation_id']}/handoff"
    assert (await client.post(first_url)).status_code == 422
    assert (await client.post(first_url, headers={"X-Conversation-Token": "x" * 40})).status_code == 404
    assert (await client.post(second_url, headers={"X-Conversation-Token": first["access_token"]})).status_code == 404
    assert (await client.post(first_url, headers={"X-Conversation-Token": first["access_token"]}, json={"assigned_staff_id": str(uuid4())})).status_code == 204
    first_conversation = (await client.get(f"{PREFIX}/conversations/{first['conversation_id']}", headers=headers)).json()
    assert first_conversation["status"] == "waiting_for_staff" and first_conversation["assigned_staff_id"] is None
    assert (await client.get(f"{PREFIX}/escalations")).status_code == 401
    assert (await client.get(f"{PREFIX}/escalations/{uuid4()}")).status_code == 401
