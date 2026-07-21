"""The State schema - the single object that flows through the graph.

Every node receives the current State, does its one job, and returns a
dict containing ONLY the keys it changed. LangGraph merges that partial
update into the state and passes the result to the next node. Nothing
else is shared between nodes - if it isn't in State, it doesn't exist.
"""

from typing import Optional, TypedDict


class Lead(TypedDict, total=False):
    """Structured facts about the customer, captured as they appear.

    Kept as explicit fields (not buried in chat history) so they survive
    summarization and can be written to the CRM at booking time.
    """

    name: str
    phone: str
    city: str
    service_line: str
    preferred_date: str
    time_window: str


class State(TypedDict, total=False):
    # --- conversation memory ---
    # Recent turns, verbatim, in OpenAI message format ({role, content}).
    # Grows each turn until summarize compresses the oldest into `summary`.
    messages: list[dict]
    # Running compressed memory of everything summarize has absorbed.
    summary: str

    # --- this turn's routing (written by router, read by everyone after) ---
    service_line: Optional[str]  # one of VALID_SERVICE_LINES, or None
    intent: str  # question | booking | handoff | chitchat | out_of_scope
    confidence: float  # router's own 0-1 confidence in the classification

    # --- this turn's retrieval (written by retrieve, read by answer) ---
    retrieved: list[dict]  # [{text, service_line, section, score}, ...]

    # --- durable facts ---
    lead: Lead

    # --- control ---
    # Structured UI event ("escalate" button etc.). When set, graph entry
    # skips the router and jumps straight to the named node - the button
    # mechanism decided in the P2 design conversation.
    action: Optional[str]
    escalated: bool  # once True, the bot stops answering; a human owns it

    # --- observability (accumulated across the whole conversation) ---
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost: float
