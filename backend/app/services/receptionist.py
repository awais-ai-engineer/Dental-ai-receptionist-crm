"""Bounded, validated decisions over the public receptionist tool registry."""

import json
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation
from app.services.providers import ProviderError
from app.services.receptionist_tools import ReceptionistToolContext, TOOL_REGISTRY, ToolResult, execute_tool, tool_spec

MAX_TOOL_STEPS = 3


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ReceptionistResponse(BaseModel):
    answer: str
    actions: list[ToolResult] = Field(default_factory=list)


def _render(result: ToolResult) -> str:
    if not result.success:
        return result.message or "I couldn't complete that request. Please contact clinic staff."
    data = result.data
    if result.tool == "search_clinic_knowledge":
        return data["answer"]
    if result.tool == "list_doctors":
        doctors = data["doctors"]
        return "Our available doctors are: " + "; ".join(f"{d['full_name']} ({d['specialization'] or 'general dentistry'})" for d in doctors) + "." if doctors else "I couldn't find an active doctor matching that request."
    if result.tool == "search_available_slots":
        entries = [f"{d['doctor_name']}: {', '.join(d['slots'][:8])}" for d in data["doctors"] if d["slots"]]
        return "Available appointment starts (UTC): " + "; ".join(entries) + "." if entries else "No suitable available slots were found for that date."
    if result.tool == "create_appointment_request":
        return f"Your appointment request for {data['scheduled_start']} has been submitted. The clinic still needs to confirm it. Reference: {data['appointment_id']}."
    if result.tool == "reschedule_appointment":
        return f"Your reschedule request for {data['scheduled_start']} has been submitted. The clinic still needs to confirm it. Reference: {data['appointment_id']}."
    if result.tool == "cancel_appointment":
        return f"Your appointment {data['appointment_id']} has been cancelled."
    if result.tool == "request_human_handoff":
        return "I've asked clinic staff to take over this conversation."
    if result.tool == "create_escalation":
        return "I've flagged your request for clinic staff. If you have severe bleeding or trouble breathing, contact local emergency services immediately."
    return "Please contact clinic staff for help."


async def orchestrate(db: AsyncSession, conversation: Conversation, patient_message: str, llm_client, embedding_client) -> ReceptionistResponse:
    ctx = ReceptionistToolContext.from_conversation(conversation)
    results: list[ToolResult] = []
    system = (
        "You are selecting one receptionist tool at a time. Return ONLY JSON with keys tool and arguments. "
        "Use a tool name from the provided allowlist or use tool='respond' with empty arguments when done. "
        "Never supply clinic_id, patient_id, staff IDs, SQL, or arbitrary functions. "
        "The backend validates all arguments and determines identity. Do not diagnose or claim a booking is confirmed. "
        "Choose at most one tool per response. For bookings, list doctors, search slots, then request only a returned slot. "
        "For ambiguous changes, use respond and let the backend ask for details. "
        f"Tools: {json.dumps(tool_spec())}"
    )
    for step in range(MAX_TOOL_STEPS):
        user = {"patient_message": patient_message, "prior_tool_results": [r.model_dump(mode="json") for r in results]}
        raw = await llm_client.complete([{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user)}])
        try:
            decision = Decision.model_validate_json(raw)
        except ValidationError as exc:
            raise ProviderError("AI provider returned an invalid tool decision") from exc
        if decision.tool == "respond":
            if decision.arguments:
                raise ProviderError("AI provider returned an invalid tool decision")
            return ReceptionistResponse(answer=_render(results[-1]) if results else "I can help with clinic information, doctors, appointments, or connect you with staff. Please tell me what you need.", actions=results)
        if decision.tool not in TOOL_REGISTRY:
            raise ProviderError("AI provider requested an unavailable tool")
        result = await execute_tool(decision.tool, decision.arguments, db=db, ctx=ctx, conversation=conversation,
                                    patient_message=patient_message, embedding_client=embedding_client, llm_client=llm_client)
        if not result.success and result.error_code in ("unknown_tool", "invalid_arguments"):
            raise ProviderError("AI provider returned an invalid tool decision")
        results.append(result)
        if not result.success or decision.tool in ("search_clinic_knowledge", "create_appointment_request", "reschedule_appointment", "cancel_appointment", "request_human_handoff", "create_escalation"):
            return ReceptionistResponse(answer=_render(result), actions=results)
    return ReceptionistResponse(answer="I reached the limit for this request. Please contact clinic staff for help.", actions=results)
