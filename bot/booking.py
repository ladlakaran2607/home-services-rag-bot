"""Booking node: extract facts -> code decides -> CRM executes.

The tool-use inversion vs v1: no LLM tool-calling loop. A mini model
only EXTRACTS structured fields from the conversation; plain Python
checks completeness, asks for what's missing (template, zero tokens),
or books through the CRM adapter (deterministic, unhallucinatable).
"""

import json
from datetime import date

from bot.config import MODEL_ROUTER, VALID_SERVICE_LINES
from bot.crm import crm, in_service_area
from bot.llm import client, usage_delta
from bot.prompts import BOOKING_EXTRACT
from bot.state import State

REQUIRED = ("name", "phone", "service_line", "preferred_date")
ASK_LABELS = {
    "name": "your name",
    "phone": "the best phone number to reach you",
    "service_line": "which service you need",
    "preferred_date": "what day works for you",
}

EXTRACT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "lead_details",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "phone": {"type": ["string", "null"]},
                "city": {"type": ["string", "null"]},
                "service_line": {
                    "type": ["string", "null"],
                    "enum": [s for s in VALID_SERVICE_LINES if s != "company"] + [None],
                },
                "preferred_date": {"type": ["string", "null"]},
                "time_window": {"type": ["string", "null"], "enum": ["morning", "afternoon", None]},
            },
            "required": ["name", "phone", "city", "service_line", "preferred_date", "time_window"],
            "additionalProperties": False,
        },
    },
}


def booking(state: State) -> dict:
    # 1. EXTRACT (mini model, structured output, minimal effort)
    today = date.today()
    transcript = "\n".join(
        f"{m['role']}: {m['content']}" for m in state["messages"][-8:]
    )
    if state.get("summary"):
        transcript = f"Summary of earlier turns: {state['summary']}\n{transcript}"
    response = client.chat.completions.create(
        model=MODEL_ROUTER,
        messages=[
            {"role": "system", "content": BOOKING_EXTRACT.format(
                today=today.isoformat(), weekday=today.strftime("%A"))},
            {"role": "user", "content": transcript},
        ],
        response_format=EXTRACT_SCHEMA,
        reasoning_effort="minimal",
        name="v2-booking-extract",
    )
    extracted = json.loads(response.choices[0].message.content)

    # 2. MERGE into durable lead state (never lose an earlier fact)
    lead = dict(state.get("lead") or {})
    for key, value in extracted.items():
        if value:
            lead[key] = value
    if not lead.get("service_line") and state.get("service_line") not in (None, "company"):
        lead["service_line"] = state["service_line"]

    # 3. DECIDE in code
    missing = [k for k in REQUIRED if not lead.get(k)]
    if missing:
        wanted = " and ".join(ASK_LABELS[k] for k in missing[:2])  # max two asks
        reply = f"Happy to get that booked. Could I get {wanted}?"
    else:
        lead_id = crm.create_or_update_lead(lead)
        appointment = crm.book_appointment(lead_id, lead)
        window = appointment["window"]
        if appointment.get("already_existed"):
            reply = (
                f"You're all set, {lead['name'].split()[0]} - I've added that "
                f"to your existing visit on {appointment['date']} ({window}). "
                f"One trip, the technician will handle both."
            )
        else:
            reply = (
                f"You're booked, {lead['name'].split()[0]}! "
                f"{lead['service_line']} visit on {appointment['date']} "
                f"({window} - you'll get a 2-hour arrival window and a text "
                f"with your technician's name when they're en route)."
            )
        if lead.get("city") and not in_service_area(lead["city"]):
            reply += (
                f" Note: {lead['city']} is outside our standard service "
                f"area, so a $49 trip fee may apply - we'll confirm by phone."
            )

    delta = usage_delta(MODEL_ROUTER, response.usage)
    return {
        "messages": state["messages"] + [{"role": "assistant", "content": reply}],
        "lead": lead,
        "total_prompt_tokens": state.get("total_prompt_tokens", 0) + delta["prompt_tokens"],
        "total_completion_tokens": state.get("total_completion_tokens", 0) + delta["completion_tokens"],
        "total_cost": state.get("total_cost", 0.0) + delta["cost"],
    }
