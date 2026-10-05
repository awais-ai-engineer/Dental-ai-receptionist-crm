from fastapi import APIRouter

from app.api.v1.endpoints import appointments, auth, doctors, health, patients

router = APIRouter()
for module in (health, auth, doctors, patients, appointments):
    router.include_router(module.router)
