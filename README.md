# Home Services RAG Bot

A customer support and booking bot for a fictional 12-trade home services
company, built twice on purpose: v1 the naive way (entire knowledge base in
the prompt, full history every turn, premium model for everything) and v2 the
optimized way (routing, filtered RAG, rolling summarization, model tiering,
deterministic booking). Both run behind one console with a live trace panel
and a Compare view, so the difference is measured, not claimed.

Measured on identical questions through the same console:

| Metric | v2 | v1 | Factor |
|---|---|---|---|
| Input tokens, pricing question | 438 | 7,681 | 17x |
| Cost, pricing question | $0.0006 | $0.0224 | 37x |
| Latency per reply | 3 to 5s streamed | 14 to 30s silent | ~4x |
| Full 4-question conversation | $0.013 | $0.086 | 6.6x |

Quality held by inspection: prices quote exactly from the knowledge base,
out-of-scope questions get an honest refusal and a human handoff offer.

## Architecture

Customer → chat console (SSE) → FastAPI → LangGraph graph:
router (mini model classifies service line + intent) → retrieve (Qdrant,
filtered) → answer (streams) with booking, escalation, and summarization as
separate nodes. Postgres holds the CRM (NocoDB renders it as a GUI) and the
LangGraph checkpoints (conversations survive restarts). Langfuse traces every
call. Diagram: architecture/architecture-diagram.excalidraw.

The bot is deliberately a workflow, not an agent: every path is drawn at
build time and the models only classify, compose, and extract. Why that is
the right call here, and when it is not, is the subject of
[architecture/decision-memo.md](architecture/decision-memo.md).

## Repo map

```
knowledge-base/    13 authored markdown docs (the "company")
ingest.py          chunk + embed + load Qdrant (full rebuild each run)
v1_naive.py        the baseline bot, deliberately bloated, instrumented
bot/               the v2 graph: config, state, prompts, one file per node
app/               FastAPI + the console (SSE, trace panel, CRM tab, Compare)
conversations.json scripted test conversations (both bots replay these)
run_baseline.py    replays the scripts against v1, writes results/
architecture/      decision memo, RAG design, token optimization, CRM adapter
ops/RUNBOOK.md     the improvement loop + operating procedures
db/schema.sql      CRM schema (idempotency lives here as a constraint)
```

## Run it

See [SETUP.md](SETUP.md). Short version: Docker for Qdrant + Postgres +
NocoDB, uv for Python, one .env, `uv run python ingest.py` once, then
`uv run uvicorn app.main:app` and open localhost:8000.

## Honest limitations

No auth or rate limiting, escalation notifies no human yet, the eval gate is
a discipline rather than CI, and the formal LLM-judge quality score was
descoped in favor of inspection plus the live Compare view. Details and
production shapes for each: [ops/RUNBOOK.md](ops/RUNBOOK.md).
