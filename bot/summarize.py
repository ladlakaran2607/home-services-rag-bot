"""Summarize node: fold old turns into the running summary.

Closes v1's mistake #2 - unbounded history growth. After this node runs,
state carries `summary` (compressed past) + the KEEP_VERBATIM newest
messages, so per-turn context cost is capped no matter how long the
conversation gets. Lossy by design; structured facts (lead, bookings)
live in state fields and the CRM, so nothing critical depends on the
summary surviving perfectly.
"""

from bot.config import KEEP_VERBATIM, MODEL_SUMMARY
from bot.llm import client, usage_delta
from bot.prompts import SUMMARIZE_PROMPT
from bot.state import State


def summarize(state: State) -> dict:
    messages = state["messages"]
    absorbed = messages[:-KEEP_VERBATIM]
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in absorbed)

    response = client.chat.completions.create(
        model=MODEL_SUMMARY,
        messages=[
            {"role": "system", "content": SUMMARIZE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Prior summary:\n{state.get('summary') or '(none)'}\n\n"
                    f"New turns to absorb:\n{transcript}"
                ),
            },
        ],
        reasoning_effort="minimal",
        name="v2-summarize",
    )
    new_summary = response.choices[0].message.content.strip()

    delta = usage_delta(MODEL_SUMMARY, response.usage)
    return {
        "summary": new_summary,
        "messages": messages[-KEEP_VERBATIM:],  # the trim - old turns are gone
        "total_prompt_tokens": state.get("total_prompt_tokens", 0) + delta["prompt_tokens"],
        "total_completion_tokens": state.get("total_completion_tokens", 0) + delta["completion_tokens"],
        "total_cost": state.get("total_cost", 0.0) + delta["cost"],
    }
