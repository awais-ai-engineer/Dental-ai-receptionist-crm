from fastapi import APIRouter

from app.api.v1.endpoints import appointments, auth, conversations, doctors, escalations, health, knowledge, outbox, patients, rag, reception

router = APIRouter()
for module in (health, auth, doctors, patients, appointments, conversations, reception, escalations, knowledge, rag, outbox):
    router.include_router(module.router)
