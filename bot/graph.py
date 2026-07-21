"""Wire the nodes into the v2 graph.

        START
          | (entry_route: button/escalated -> escalate, else router)
        router
          | (after_router: handoff -> escalate, booking -> booking,
          |                else retrieve)
        retrieve --> answer --+
        booking --------------+-- (maybe_summarize: oversized history?)
          |                        |yes            |no
        escalate --> END         summarize --> END END

The graph routes, the model works: every arrow here was drawn at build
time; the LLMs only fill in classifications and prose.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from bot.answer import answer
from bot.booking import booking
from bot.config import SUMMARIZE_AFTER_TURNS
from bot.escalate import escalate
from bot.retrieve import retrieve
from bot.router import route
from bot.state import State
from bot.summarize import summarize


def entry_route(state: State) -> str:
    """The button mechanism: structured actions skip the router entirely."""
    if state.get("action") == "escalate" or state.get("escalated"):
        return "escalate"
    return "router"


def after_router(state: State) -> str:
    if state["intent"] == "handoff":
        return "escalate"
    if state["intent"] == "booking":
        return "booking"
    return "retrieve"


def maybe_summarize(state: State) -> str:
    """Pay for compression only once history is actually oversized."""
    if len(state["messages"]) > SUMMARIZE_AFTER_TURNS:
        return "summarize"
    return END


def build_graph(checkpointer=None):
    g = StateGraph(State)
    g.add_node("router", route)
    g.add_node("retrieve", retrieve)
    g.add_node("answer", answer)
    g.add_node("booking", booking)
    g.add_node("escalate", escalate)
    g.add_node("summarize", summarize)

    g.add_conditional_edges(START, entry_route, ["router", "escalate"])
    g.add_conditional_edges("router", after_router, ["retrieve", "booking", "escalate"])
    g.add_edge("retrieve", "answer")
    g.add_conditional_edges("answer", maybe_summarize, ["summarize", END])
    g.add_conditional_edges("booking", maybe_summarize, ["summarize", END])
    g.add_edge("summarize", END)
    g.add_edge("escalate", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
