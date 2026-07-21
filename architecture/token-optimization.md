# Token optimization: the five techniques and the measured arithmetic

The engagement premise: a working multi-service bot that eats tokens. This doc
is the technical half of the story, what exactly wastes the tokens and what
exactly recovers them, with numbers from this repo's own instrumented runs.

## Anatomy of the bloat (v1, measured)

v1 ships, on every single API call:

- The full knowledge base in the system prompt: ~7,680 tokens measured by the
  tokenizer (the chars/4 estimate said 7,920; never bill by heuristics).
- The complete conversation history, growing roughly 500 tokens per turn.
- All four tool schemas, needed or not.
- One premium model for everything, including "do you serve Parker?"

Measured baseline (8 scripted conversations, 25 user turns, 29 API calls):
231,856 prompt tokens, 27,301 completion tokens, $0.337. Per question, about
9,300 input tokens whose relevant knowledge averaged a few hundred.

The counterintuitive finding: with prompt caching active, 81 percent of v1's
dollars were completion tokens. Input bloat is the famous problem; output
verbosity and hidden reasoning were the bigger invoice line. Any optimization
plan that only fixes retrieval leaves most of the money on the table.

## Technique 1: RAG (kills the knowledge dump)

Move the KB to a vector store. Retrieve 3 to 5 chunks (~400 tokens) filtered
by service line instead of shipping ~7,680 tokens of everything. Knowledge
size and per-call cost are now independent: the company can add 50 service
lines and the per-question cost does not move.

Measured: the same pricing question dropped from 8,200 input tokens (v1,
cached) to 1,299 total across both v2 calls. See rag-design.md for the
retrieval internals.

## Technique 2: Semantic routing (makes everything downstream cheap)

A mini model classifies each message into service_line and intent with a
strict JSON schema at minimal reasoning effort. Measured: ~$0.0002 and about
2 seconds per classification. The label drives the retrieval filter and the
graph branch, so no expensive component ever runs blind. It also carries an
honesty channel: the router reports its own confidence, and it visibly
dropped to 0.57 on the one message it misread during testing.

## Technique 3: Rolling summarization (caps history growth)

Beyond the newest 4 messages, history is compressed into a sub-120-word
summary by the mini model, refreshed every other turn or so. Turn 8 and turn
50 send the same context volume. Two design rules make it safe:

- The summary prompt lists what must survive verbatim (names, phones, prices
  quoted, bookings, open questions).
- Critical facts do not depend on the summary at all: lead fields live in
  graph state, bookings live in the CRM. Summary memory is conversational
  color, not the system of record.

Verified end to end: a dog's name mentioned in turn 1 survived two
compressions and was recalled correctly after the original message had been
trimmed from history.

## Technique 4: Model tiering (prices the work correctly)

Routing, extraction, and summarization run on gpt-5-mini. The answer model
also ended up on mini after latency data (see below). Output tokens, the 81
percent line item, now bill at one fifth the premium rate.

## Technique 5: Prompt caching (free, and honestly accounted)

OpenAI caches repeated prompt prefixes over 1,024 tokens automatically, with
cached input billed at a steep discount. Two honest notes the report must
carry:

- Caching also helps v1. Its giant prompt cached across turns in our runs,
  which is why the fair report shows raw tokens and effective cost as
  separate columns. Raw tokens are where the bloat is undeniable.
- Back-to-back replay overstates cache benefit versus real users, who type
  slowly and let the cache expire between turns. The v1 baseline is therefore
  conservative: production v1 would cost more than our measurement.

## The sixth lever nobody bills for: latency

Two changes came from watching time-to-first-token, not tokens:

- Reasoning effort to minimal on answers: TTFT dropped from 6.5s of silent
  deliberation to ~3s. A support answer over retrieved context does not need
  chain-of-thought.
- Answer model to mini: the premium model spiked 28 to 57 seconds TTFT on
  roughly one call in three (median ~7s). Mini measured median 2.9s, max 5.1s
  across samples. For live chat this was disqualifying for premium regardless
  of cost.

Latency claims in any client report should quote median and p95, never single
runs; the spikes are real and land randomly.

## What stacked, in one table

| Waste | Fix | Mechanism |
|---|---|---|
| KB in every prompt | RAG | 8k tokens becomes ~400 relevant ones |
| Full history resent | Summarization | context volume capped forever |
| All tool schemas always | No tool-calling; extract + code | zero schemas shipped |
| Premium model everywhere | Tiering | 5x cheaper output, stabler latency |
| Static prefix rebilled | Caching | automatic discount, honestly reported |

Measured outcome across live sessions: 14 to 17x fewer input tokens per turn,
6.6x cheaper per conversation, roughly 4x faster per reply, at quality
verified by inspection against the knowledge base.

## When not to do all this

Honesty for the discovery call: a single-service bot with a 2-page knowledge
base does not need RAG; a low-traffic internal tool does not need tiering;
and if conversations are one or two turns, summarization is dead code. The
techniques earn their complexity when knowledge is wide, conversations are
long, or volume is high. This project's fictional client had all three.
