"""v1 - the deliberately naive "before" bot.

Reproduces the three classic token-bloat mistakes on purpose:
  1. The ENTIRE knowledge base is pasted into the system prompt.
  2. The full conversation history is resent on every turn.
  3. Every tool schema is attached to every call, needed or not.
One premium model handles everything, including trivial questions.

Every call is traced to Langfuse (tokens, cost, latency) via the
drop-in OpenAI wrapper. Per-turn usage is also printed to the terminal.

Run with:  uv run python v1_naive.py   (type 'quit' to exit)
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langfuse import get_client
from langfuse.openai import OpenAI  # drop-in wrapper: auto-traces every call

load_dotenv()

KB_DIR = Path("knowledge-base")
MODEL = "gpt-5"  # premium tier for EVERYTHING - that's the point of v1

# $/1M tokens - verify against the current OpenAI pricing page
PRICE_INPUT = 1.25
PRICE_CACHED = 0.125
PRICE_OUTPUT = 10.00


def build_system_prompt() -> str:
    """The bloat, mistake #1: every doc, in full, on every single call."""
    parts = [
        "You are Sunny, the virtual assistant for Summit Home Services, a "
        "multi-trade home services company in the Denver metro area. Answer "
        "customer questions using the company knowledge below, capture leads, "
        "and book appointments with the tools provided. Be friendly, concise, "
        "and honest; never invent prices or services not listed below.\n\n"
        "=== COMPANY KNOWLEDGE (full) ==="
    ]
    for path in sorted(KB_DIR.rglob("*.md")):
        _, _, body = path.read_text(encoding="utf-8").split("---", 2)
        parts.append(f"\n\n--- {path.name} ---\n{body.strip()}")
    return "".join(parts)


# The bloat, mistake #3: all schemas ride along on every call.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_lead",
            "description": "Save a new lead (name + phone + service interest) to the CRM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "service_line": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["name", "phone", "service_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book an appointment for an existing or new customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "service_line": {"type": "string"},
                    "preferred_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time_window": {"type": "string", "enum": ["morning", "afternoon"]},
                },
                "required": ["name", "phone", "service_line", "preferred_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_service_area",
            "description": "Check whether a city/area is inside the service area.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financing_options",
            "description": "Return financing options for a given job estimate in dollars.",
            "parameters": {
                "type": "object",
                "properties": {"job_estimate": {"type": "number"}},
                "required": ["job_estimate"],
            },
        },
    },
]

SERVICE_AREA = {
    "denver", "aurora", "lakewood", "arvada", "westminster", "thornton",
    "centennial", "littleton", "highlands ranch", "broomfield", "golden", "parker",
}


def run_tool(name: str, args: dict) -> str:
    """Mock tool execution - P2 replaces this with the real CRM adapter."""
    if name == "create_lead":
        return json.dumps({"status": "ok", "lead_id": "L-1042"})
    if name == "book_appointment":
        return json.dumps({"status": "booked", "appointment_id": "A-2317",
                           "date": args.get("preferred_date"),
                           "window": args.get("time_window", "morning")})
    if name == "check_service_area":
        inside = args.get("city", "").strip().lower() in SERVICE_AREA
        return json.dumps({"inside_service_area": inside, "trip_fee": 0 if inside else 49})
    if name == "get_financing_options":
        est = float(args.get("job_estimate", 0))
        opts = []
        if est > 1000:
            opts.append("0% interest for 12 months (on approved credit)")
        if est > 5000:
            opts.append("term loans up to 120 months, 7.9%-13.9% APR")
        return json.dumps({"options": opts or ["not available under $1,000"]})
    return json.dumps({"error": f"unknown tool {name}"})


def cost_of(usage) -> float:
    """Dollars for one call, splitting cached from uncached input tokens."""
    cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
    uncached = usage.prompt_tokens - cached
    return (uncached * PRICE_INPUT + cached * PRICE_CACHED
            + usage.completion_tokens * PRICE_OUTPUT) / 1_000_000


def chat() -> None:
    client = OpenAI()
    system_prompt = build_system_prompt()
    print(f"[v1] system prompt is ~{len(system_prompt) // 4} tokens, "
          f"resent on every single call\n")

    # Mistake #2 lives here: this list only ever grows, and all of it
    # goes back to the model on every turn.
    messages = [{"role": "system", "content": system_prompt}]
    totals = {"prompt": 0, "cached": 0, "completion": 0, "cost": 0.0, "calls": 0}

    while True:
        user_input = input("you> ").strip()
        if user_input.lower() in {"quit", "exit"}:
            break
        if not user_input:
            continue
        messages.append({"role": "user", "content": user_input})

        # Inner loop: keep calling until the model stops asking for tools.
        while True:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                name="v1-naive-turn",  # trace name in Langfuse
            )
            usage = response.usage
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
            call_cost = cost_of(usage)
            totals["prompt"] += usage.prompt_tokens
            totals["cached"] += cached
            totals["completion"] += usage.completion_tokens
            totals["cost"] += call_cost
            totals["calls"] += 1
            print(f"   [tokens] in={usage.prompt_tokens} (cached={cached}) "
                  f"out={usage.completion_tokens}  cost=${call_cost:.4f}")

            msg = response.choices[0].message
            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    result = run_tool(tc.function.name, json.loads(tc.function.arguments))
                    print(f"   [tool] {tc.function.name} -> {result}")
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": result})
                continue  # go around: let the model use the tool results
            print(f"\nsunny> {msg.content}\n")
            messages.append({"role": "assistant", "content": msg.content})
            break

    print(f"\n=== session totals ({totals['calls']} calls) ===")
    print(f"  prompt tokens:     {totals['prompt']:,} (cached {totals['cached']:,})")
    print(f"  completion tokens: {totals['completion']:,}")
    print(f"  estimated cost:    ${totals['cost']:.4f}")
    get_client().flush()  # push any buffered traces to Langfuse before exit


if __name__ == "__main__":
    chat()
