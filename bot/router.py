"""Router node: gpt-5-mini classifies the turn -> service_line, intent, confidence.

The cheapest call in the graph, and the one that makes every later call
cheap: retrieval filters by its service_line, and the graph branches on
its intent. Test standalone with:  uv run python -m bot.router
"""

import json

from bot.config import MODEL_ROUTER, VALID_SERVICE_LINES
from bot.llm import client, usage_delta
from bot.prompts import ROUTER_SYSTEM
from bot.state import State

ROUTE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "route",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "service_line": {
                    "type": ["string", "null"],
                    "enum": VALID_SERVICE_LINES + [None],
                },
                "intent": {
                    "type": "string",
                    "enum": ["question", "booking", "handoff", "chitchat", "out_of_scope"],
                },
                "confidence": {"type": "number"},
            },
            "required": ["service_line", "intent", "confidence"],
            "additionalProperties": False,
        },
    },
}


def route(state: State) -> dict:
    """Read the latest user message (with context), write the classification."""
    recent = state["messages"][-5:]  # follow-ups need context, not the whole log
    context_parts = []
    if state.get("summary"):
        context_parts.append(f"Conversation summary: {state['summary']}")
    for m in recent:
        context_parts.append(f"{m['role']}: {m['content']}")
    payload = "\n".join(context_parts)

    response = client.chat.completions.create(
        model=MODEL_ROUTER,
        messages=[
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user", "content": payload},
        ],
        response_format=ROUTE_SCHEMA,
        reasoning_effort="minimal",  # classification needs speed, not thought
        name="v2-router",
    )
    decision = json.loads(response.choices[0].message.content)
    if decision["service_line"] not in VALID_SERVICE_LINES:
        decision["service_line"] = None  # belt-and-braces despite the enum

    delta = usage_delta(MODEL_ROUTER, response.usage)
    return {
        "service_line": decision["service_line"],
        "intent": decision["intent"],
        "confidence": decision["confidence"],
        "total_prompt_tokens": state.get("total_prompt_tokens", 0) + delta["prompt_tokens"],
        "total_completion_tokens": state.get("total_completion_tokens", 0) + delta["completion_tokens"],
        "total_cost": state.get("total_cost", 0.0) + delta["cost"],
    }


if __name__ == "__main__":
    # Standalone smoke test: no graph, just the node against hand-made states.
    cases = [
        [{"role": "user", "content": "how much is a tankless water heater?"}],
        [{"role": "user", "content": "my sink is leaking, can you help?"}],
        [
            {"role": "user", "content": "how much is a tankless water heater?"},
            {"role": "assistant", "content": "A tankless install runs $3,200-$5,800..."},
            {"role": "user", "content": "can I finance that?"},
        ],
        [{"role": "user", "content": "do you guys install swimming pools?"}],
        [{"role": "user", "content": "this bot is useless, get me a real person"}],
        [{"role": "user", "content": "I get huge ice dams on my gutters every winter"}],
        [{"role": "user", "content": "hi there!"}],
    ]
    for messages in cases:
        result = route({"messages": messages})
        last = messages[-1]["content"]
        print(f"{last[:52]:<54} -> {str(result['service_line']):<14} "
              f"{result['intent']:<13} conf={result['confidence']:.2f} "
              f"(${result['total_cost']:.5f})")
