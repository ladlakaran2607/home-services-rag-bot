# Ops runbook: the improvement loop, and how to operate this system

## The loop

Trace, evaluate, observe, diagnose, gate, release. Mapped to this repo:

- **Trace**: every LLM call auto-traces to Langfuse via the drop-in OpenAI
  wrapper (tokens, cost, latency, full prompts, named per node: v2-router,
  v2-answer, v2-booking-extract, v2-summarize). One trace per turn.
- **Evaluate (was it good?)**: answer quality is inspected against the
  knowledge base; prices must quote exactly, out-of-scope must refuse. The
  in-app Compare overlay gives per-session v1 vs v2 evidence. A formal
  golden-set judge was descoped by decision (see BUILD-PLAN); if a client
  claim ever needs the number, replay conversations.json through both bots
  and judge parity.
- **Observe (was it healthy?)**: tokens, cost, and seconds per turn in the
  console stat lines and Langfuse dashboards. Good and healthy are different
  questions; a correct answer that took 57 seconds fails.
- **Diagnose**: the trace panel shows which node did what with which data;
  Langfuse shows where the time and tokens went; checkpoints allow inspecting
  any thread's state at any past step (graph.get_state_history).
- **Gate and release**: prompts live only in bot/prompts.py, knobs only in
  bot/config.py, so every behavioral change is one reviewable diff. Rule: no
  prompt or config change ships without replaying the affected scripted
  conversations and eyeballing the trace. Git history is the prompt version
  log.

## The loop, run live: four documented iterations

1. **Router misroute.** Symptom: "my dog Bruno will be in the yard" routed as
   booking (conf 0.57) and the bot asked for a phone number. Diagnosis: the
   prompt never defined informational notes. Change: one rule in
   ROUTER_SYSTEM with examples. Result: reroutes as chitchat (conf 0.66),
   note survives into summary memory.
2. **Duplicate appointment.** Symptom: "book that too" created a second
   same-day visit (two trucks). Diagnosis: deterministic booking lacked
   idempotency. Change: dedupe in the adapter, then UNIQUE(contact_id, date)
   in the schema, plus a services array so the visit genuinely extends.
   Result: reuse confirmed in testing; the constraint makes regression
   impossible.
3. **Reasoning latency.** Symptom: replies felt slow; probe showed 6.5s
   time-to-first-token, all silent model deliberation. Change:
   ANSWER_REASONING_EFFORT to minimal. Result: TTFT ~3s. Lesson: restart the
   server before re-measuring a config change; the first re-probe ran on the
   old process and nearly caused a wrong conclusion.
4. **Answer model swap.** Symptom: premium-model TTFT spiked 28 to 57s on
   roughly one call in three across both browser and probe measurements.
   Change: MODEL_ANSWER to gpt-5-mini, provisional, documented in config.py
   with its rollback condition. Result: median 2.9s, max 5.1s over samples,
   output cost down 5x, quality holding on inspection.

The pattern in all four: observe in the instruments, change exactly one
thing, re-measure with the same instrument, record the decision where the
knob lives.

## Operating procedures

- **Start the stack**: Docker Desktop up, then `docker start qdrant`,
  `docker compose up -d` (Postgres + NocoDB), then
  `uv run uvicorn app.main:app` from the repo root. Console at :8000,
  NocoDB at :8080, Qdrant dashboard at :6333/dashboard.
- **Rebuild the knowledge base** after editing any markdown:
  `uv run python ingest.py` (full rebuild, seconds, cannot go stale).
- **Reset demo data**: truncate appointments and contacts with RESTART
  IDENTITY (command in SETUP.md); delete single rows in NocoDB directly.
- **Reset conversation threads**: drop and recreate the summit_graph
  database, or just use fresh thread ids (every page load does).
- **Read the logs**: uvicorn stdout for requests and CRM lines; Langfuse for
  everything model-shaped.

## Known gaps, accepted for a portfolio build

Each with its production shape:

- No auth or rate limiting on the API (add a gateway or FastAPI middleware).
- v1 sessions live in process memory (fine: v1 exists to be the bad example).
- Escalation latches and logs but notifies no human (production: push to
  Slack or the CRM's task queue with the conversation attached).
- No timeout-and-retry on first-token stalls (design: cancel and retry once
  after ~10s of silence; spikes rarely repeat).
- The eval gate is a discipline, not an automated CI step (production: the
  golden-set replay wired into CI, blocking prompt merges).
