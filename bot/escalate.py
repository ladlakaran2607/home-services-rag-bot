"""Escalate node: the human-handoff exit. No LLM, no tokens, cannot fail.

Reachable three ways (the layered-trust design):
  1. The frontend's "Talk to a human" button (state.action == "escalate")
  2. The router classifying intent == "handoff"
  3. Future: low-confidence / empty-retrieval policies

Once `escalated` is True, the graph short-circuits here on every later
turn - the bot stops answering because a human owns the conversation.
"""

from bot.state import State

HANDOFF_MESSAGE = (
    "No problem - I'm connecting you with a Summit team member now. "
    "They'll have this whole conversation, so you won't need to repeat "
    "yourself. If we're outside office hours (Mon-Sat 7am-7pm), you'll "
    "get a call first thing next morning."
)

ALREADY_ESCALATED_MESSAGE = (
    "A team member has this conversation and will be with you shortly - "
    "I've added your latest message to the thread."
)


def escalate(state: State) -> dict:
    already = state.get("escalated", False)
    reply = ALREADY_ESCALATED_MESSAGE if already else HANDOFF_MESSAGE
    return {
        "messages": state["messages"] + [{"role": "assistant", "content": reply}],
        "escalated": True,
        "action": None,  # consume the button event so it doesn't re-fire
    }
