"""FastAPI backend for Summit Chat.

Endpoints:
  GET  /            the chat page (app/static/index.html)
  POST /chat        SSE stream: step / token / message / totals / done events
  GET  /crm         contacts + appointments straight from Postgres

The stream is a thin translation layer: LangGraph's own stream events
(node updates + custom token events) become the SSE events the trace
panel renders. The frontend is a renderer of what the graph broadcasts.

Run with:  uv run uvicorn app.main:app --reload   (from the repo root)
"""

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from bot.graph import build_graph

load_dotenv()

# --- v2: the graph, checkpointed in Postgres (summit_graph database) ---
_pool = ConnectionPool(
    os.environ["CHECKPOINT_DATABASE_URL"],
    kwargs={"autocommit": True, "row_factory": dict_row},
    open=True,
)
checkpointer = PostgresSaver(_pool)
checkpointer.setup()  # creates its tables on first run, no-op after
graph = build_graph(checkpointer)

# --- v1: the naive bot, kept around for the toggle ---
from v1_naive import MODEL as V1_MODEL  # noqa: E402
from v1_naive import TOOLS, build_system_prompt, cost_of, run_tool  # noqa: E402
from langfuse.openai import OpenAI  # noqa: E402

v1_client = OpenAI()
v1_system_prompt = build_system_prompt()
v1_sessions: dict[str, dict] = {}  # thread_id -> {messages, totals}

app = FastAPI(title="Summit Chat")
STATIC = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    thread_id: str
    message: str | None = None
    action: str | None = None  # "escalate" = the Talk-to-a-human button
    bot: str = "v2"


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def stream_v2(req: ChatRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    snapshot = graph.get_state(config)
    history = (snapshot.values or {}).get("messages", []) if snapshot else []

    if req.action:
        turn_input = {"messages": history, "action": req.action}
    else:
        turn_input = {"messages": history + [{"role": "user", "content": req.message}]}

    for mode, payload in graph.stream(turn_input, config, stream_mode=["updates", "custom"]):
        if mode == "custom" and "token" in payload:
            yield sse({"type": "token", "text": payload["token"]})
        elif mode == "updates":
            for node, update in payload.items():
                if node == "router":
                    yield sse({"type": "step", "node": "router", "detail": {
                        "service_line": update.get("service_line"),
                        "intent": update.get("intent"),
                        "confidence": update.get("confidence"),
                    }})
                elif node == "retrieve":
                    yield sse({"type": "step", "node": "retrieve", "detail": {
                        "chunks": [
                            {"score": c["score"], "service_line": c["service_line"],
                             "section": c["section"]}
                            for c in update.get("retrieved", [])
                        ],
                    }})
                elif node == "booking":
                    yield sse({"type": "step", "node": "booking", "detail": {
                        "lead": {k: v for k, v in (update.get("lead") or {}).items() if v},
                    }})
                    yield sse({"type": "message", "text": update["messages"][-1]["content"]})
                elif node == "escalate":
                    yield sse({"type": "step", "node": "escalate", "detail": {}})
                    yield sse({"type": "message", "text": update["messages"][-1]["content"]})
                elif node == "summarize":
                    yield sse({"type": "step", "node": "summarize", "detail": {
                        "kept_messages": len(update.get("messages", [])),
                        "summary": update.get("summary", ""),
                    }})

    values = graph.get_state(config).values
    yield sse({"type": "totals",
               "in": values.get("total_prompt_tokens", 0),
               "out": values.get("total_completion_tokens", 0),
               "cost": round(values.get("total_cost", 0.0), 4)})
    yield sse({"type": "done"})


def stream_v1(req: ChatRequest):
    session = v1_sessions.setdefault(req.thread_id, {
        "messages": [{"role": "system", "content": v1_system_prompt}],
        "totals": {"in": 0, "out": 0, "cost": 0.0},
    })
    messages, totals = session["messages"], session["totals"]
    text = req.message or "I'd like to talk to a human."
    messages.append({"role": "user", "content": text})

    yield sse({"type": "step", "node": "monolith", "detail": {
        "note": "single call: full KB + full history + all tool schemas"}})

    while True:  # tool round-trips, same loop as run_baseline
        response = v1_client.chat.completions.create(
            model=V1_MODEL, messages=messages, tools=TOOLS, name="app-v1-turn")
        usage = response.usage
        totals["in"] += usage.prompt_tokens
        totals["out"] += usage.completion_tokens
        totals["cost"] += cost_of(usage)
        msg = response.choices[0].message
        if msg.tool_calls:
            messages.append(msg)
            for tc in msg.tool_calls:
                result = run_tool(tc.function.name, json.loads(tc.function.arguments))
                yield sse({"type": "step", "node": "tool", "detail": {
                    "name": tc.function.name, "result": result}})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue
        messages.append({"role": "assistant", "content": msg.content})
        yield sse({"type": "message", "text": msg.content})
        break

    yield sse({"type": "totals", "in": totals["in"], "out": totals["out"],
               "cost": round(totals["cost"], 4)})
    yield sse({"type": "done"})


@app.post("/chat")
def chat(req: ChatRequest):
    streamer = stream_v1 if req.bot == "v1" else stream_v2
    return StreamingResponse(streamer(req), media_type="text/event-stream")


@app.get("/crm")
def crm_view():
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        contacts = conn.execute(
            "SELECT id, name, phone, city, service_line, created_at::text "
            "FROM contacts ORDER BY id"
        ).fetchall()
        appointments = conn.execute(
            "SELECT a.id, c.name AS contact, a.services, a.date::text, "
            "a.time_window, a.status FROM appointments a "
            "JOIN contacts c ON c.id = a.contact_id ORDER BY a.id"
        ).fetchall()
    return {"contacts": contacts, "appointments": appointments}


@app.get("/")
def index():
    # no-store: the console is a single dev-served file; stale caches have
    # already cost one debugging session.
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
