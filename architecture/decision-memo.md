# Decision memo: how this bot was built, and why

The scenario this project simulates: a multi-trade home services company has a
chatbot that answers questions across 12 service lines and books appointments.
The naive build works but burns tokens and money. The engagement question is
always the same: optimize in place or rebuild, and on what stack?

This memo records every major decision, the alternatives considered, and the
honest boundaries of each choice. Numbers quoted are measured from this repo's
own instrumented runs, not estimates.

## 1. Workflow, not agent

The most important call happens before any framework talk. Anthropic's
taxonomy draws the line cleanly: a workflow runs LLMs through code paths you
predefined; an agent lets the model direct its own process and tool usage.

Every conversation this bot handles has the same shape: classify the message,
fetch relevant knowledge, answer, maybe book, maybe escalate. The paths are
fully enumerable. That makes it a workflow, and building it as an agent would
mean paying a premium model to rediscover the same control flow on every
single turn.

The counterexample that proves the rule is Ledger Sentinel (a sibling project):
invoice exception investigation, where the next probe depends on what the last
probe revealed and the decision tree is genuinely not pre-mappable. There the
model owns the routing and the stop condition, and the graph provides
guardrails around it. Two systems, same framework, opposite control
philosophies, each justified by problem shape. One line to remember:

> Home services: the graph routes and the model works.
> Ledger Sentinel: the model routes and the graph guards.

## 2. Why LangGraph and not the alternatives

The 2026 landscape, and where each option fell for this project:

- **Raw API calls, no framework.** Where v1 (the deliberately naive baseline)
  lives, and honestly where a single-turn FAQ bot could stay. Falls over the
  moment you need branching, durable multi-turn state, and human handoff.
- **ReAct loop, hand-rolled (with LlamaIndex or similar for retrieval).**
  Great learning exercise, wrong economics here. A ReAct agent resends its
  growing thought-and-observation scratchpad every iteration and decides at
  runtime how many loops to take. Flexible, token-hungry, variable cost. For
  a bounded support flow, one classify-fetch-answer pass does the same job at
  a quarter of the input tokens with a fixed, known cost per turn.
- **Provider SDKs (Claude Agent SDK, OpenAI Agents SDK).** The right default
  for simple agent loops in 2026. The Claude Agent SDK is built for agents
  that operate in an execution environment (files, code, computers), which is
  not this problem. The OpenAI Agents SDK's handoff model fits multi-agent
  trees, also not this problem.
- **LangGraph (chosen).** Earned its place for four concrete reasons:
  conditional edges make the branching explicit and testable per node; the
  state object with checkpointing gives durable multi-turn memory and true
  multi-user isolation by thread id; interrupts and terminal nodes make
  escalation a first-class exit rather than a prompt suggestion; and node
  boundaries are where model tiering and token accounting naturally attach.
  Rebuilding those four by hand around raw API calls produces a worse private
  LangGraph, eventually.
- **n8n.** Would be the right call when the client's own team must maintain
  the bot visually, or the bot is one branch of a wider automation estate.
  The trade is fine-grained token and latency control, which was the entire
  point of this engagement. This portfolio has separate n8n projects; this
  one stays code-first.
- **Botpress and bot platforms.** Fastest to a working support bot, weakest
  at the custom token-economics story a client in cost trouble is paying for.

## 3. The five techniques that produced the reduction

v1 makes three classic mistakes: entire knowledge base in the system prompt,
full history resent every turn, all tool schemas on every call, all on a
premium model. v2 stacks five fixes:

1. **RAG.** Knowledge moved to Qdrant. Retrieval fetches 3 to 5 chunks
   filtered by the routed service line plus company-wide docs. Knowledge size
   is now decoupled from per-call cost, which is the core insight of the
   whole build.
2. **Semantic routing.** A cheap classifier (structured output, minimal
   reasoning) narrows service line and intent before anything expensive runs.
   Measured at $0.0002 per classification.
3. **Rolling summarization.** History beyond the newest 4 messages is
   compressed into a sub-120-word summary by the cheap model. Turn 8 and
   turn 50 cost the same. Structured facts (lead fields, bookings) live in
   state and the CRM, so critical data never depends on lossy summary memory.
4. **Model tiering.** Cheap model for routing, extraction, and summarizing.
   The answer model also ended up on the cheap tier (see section 5).
5. **Prompt caching.** Automatic on OpenAI for repeated prefixes over 1,024
   tokens. Note that caching also discounts v1's giant prompt, so honest
   reporting shows raw tokens and effective cost separately. Caching softens
   the bill; it does not shrink the tokens shipped, and completion tokens
   never cache.

Plus one inversion worth naming: booking does not use LLM tool-calling. The
model only extracts structured fields; plain code decides completeness and
calls the CRM deterministically. No tool-call round-trips, no hallucinated
bookings, and the same-day idempotency guard lives in a database constraint
where no caller can bypass it.

## 4. Measured results (live instrumented sessions)

Same questions asked in both modes through the same console:

| Metric | v2 | v1 | Factor |
|---|---|---|---|
| Input tokens, pricing question | 438 | 7,681 | 17x |
| Cost, pricing question | $0.0006 | $0.0224 | 37x |
| Latency, pricing question | 3.4s | 13.9s | 4x |
| Input tokens, booking turn | ~1,100 | 15,964 | 14x |
| Full 4-question conversation cost | $0.013 | $0.086 | 6.6x |

Quality is verified by inspection against the knowledge base (prices must
quote exactly; out-of-scope questions must refuse rather than invent). A
formal LLM-judge parity score was deliberately descoped; the claim made here
is measured cost and latency reduction at inspected quality, not a judged
quality delta.

Also measured, and worth telling clients: v1 collects details it cannot
store. Its eager prompt asks for addresses and emails that its own tool
schema has no fields for. Structure is a quality feature, not just a cost one.

## 5. Decisions revised mid-build, with data

The improvement loop ran live four times during the build. Each iteration:
observe in traces, diagnose, change one thing, re-measure.

- **Router misroute.** "My dog will be in the yard" classified as booking
  intent (confidence 0.57, the router honestly flagging its own guess). Fix:
  one rule in the router prompt defining informational notes as chitchat.
- **Duplicate appointment.** "Book that too" created a second same-day visit.
  Fix: idempotency guard, first in the adapter, then as a database UNIQUE
  constraint. One visit per contact per day became physics, not politeness.
- **Reasoning latency.** Time to first token was 6.5s at the answer model's
  default deliberation. Support answers over retrieved context do not need
  deliberation. Reasoning effort dropped to minimal: first token ~3s.
- **Answer model downgrade.** The premium answer model showed first-token
  spikes of 28 to 57 seconds on roughly one call in three. The mini tier
  measured median 2.9s, max 5.1s across samples, at one fifth the output
  price, with quality holding on inspection. The premium model was not
  earning its cost anywhere in this pipeline.

## 6. CRM backend: an adapter, so it is a deployment detail

The bot writes to a CRM interface (upsert contact, book appointment), with
each call annotated with its GoHighLevel equivalent. Behind it: local
Postgres as the system of record, NocoDB rendering the same tables as a
spreadsheet GUI for demos, a mock for tests. Airtable or GHL itself are
each an afternoon behind the same interface. Choosing the backend last,
behind an adapter, is the transferable pattern; the specific backend is not.

## 7. What this build would do differently at real production scale

Honest gaps, known and accepted for a portfolio build: no rate limiting or
auth on the API; v1 sessions are in-process memory; the escalation handoff
notifies no human (it latches and logs); latency mitigation (timeout plus
retry on first-token stalls) is designed but not built; the golden-set eval
gate is documented but not automated. Each is listed in the ops runbook with
its production shape.
