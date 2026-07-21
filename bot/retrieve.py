"""Retrieve node: Qdrant search filtered by the router's service_line.

No LLM here - this node replaces v1's 8,000-token knowledge dump with
~400 tokens of exactly-relevant chunks. Embedding runs locally (FastEmbed),
so this node costs $0 per call.

Test standalone with:  uv run python -m bot.retrieve
"""

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny

from bot.config import COLLECTION, MIN_SCORE, QDRANT_URL, TOP_K
from bot.state import State

_qdrant = QdrantClient(url=QDRANT_URL)
_embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")


def retrieve(state: State) -> dict:
    """Read the latest user message + service_line, write retrieved chunks."""
    # Nothing to look up for small talk or things we don't do - and returning
    # [] here also clears any stale chunks left from the previous turn.
    if state.get("intent") in {"chitchat", "out_of_scope"}:
        return {"retrieved": []}

    question = state["messages"][-1]["content"]
    qvec = list(_embedder.query_embed(question))[0]

    # Filter to the routed service line PLUS company-wide docs: financing,
    # membership, service area and hours live in company.md and legitimately
    # answer questions asked "about" any trade.
    query_filter = None
    if state.get("service_line"):
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="service_line",
                    match=MatchAny(any=[state["service_line"], "company"]),
                )
            ]
        )

    hits = _qdrant.query_points(
        collection_name=COLLECTION,
        query=qvec.tolist(),
        limit=TOP_K,
        query_filter=query_filter,
    ).points

    retrieved = [
        {
            "text": h.payload["text"],
            "service_line": h.payload["service_line"],
            "section": h.payload["section"],
            "score": round(h.score, 3),
        }
        for h in hits
        if h.score >= MIN_SCORE
    ]
    return {"retrieved": retrieved}


if __name__ == "__main__":
    cases = [
        ("how much is a tankless water heater?", "water-heaters"),
        ("can I finance that?", "water-heaters"),
        ("I get huge ice dams on my gutters every winter", "gutters"),
        ("do you serve Boulder?", "company"),
        ("do you install swimming pools?", None),
    ]
    for question, service_line in cases:
        out = retrieve(
            {"messages": [{"role": "user", "content": question}],
             "service_line": service_line}
        )
        print(f"\n{question}  [filter={service_line}]")
        for c in out["retrieved"]:
            print(f"  {c['score']:.3f}  {c['service_line']:<14} {c['section']}")
        if not out["retrieved"]:
            print("  (nothing above MIN_SCORE)")
