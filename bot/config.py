"""Central knobs for the v2 bot. Change here, not scattered through nodes."""

# Model tiering: cheap-and-fast for routing/judging/summarizing,
# premium only where the customer actually reads the output.
MODEL_ROUTER = "gpt-5-mini"
# Answer moved gpt-5 -> gpt-5-mini after P3 latency data: gpt-5 TTFT
# spiked 28-57s on ~1 in 3 calls (median ~7s), unusable for live chat.
# Mini is stable/fast/5x cheaper on output. PROVISIONAL until the P4
# golden-set judge confirms quality parity - raise back if it doesn't.
MODEL_ANSWER = "gpt-5-mini"
MODEL_SUMMARY = "gpt-5-mini"

# Keep the answer model from burning hidden reasoning tokens on
# support questions (P1 finding: output tokens were 81% of cost).
# "minimal" chosen after the P3 latency probe: at "low", time-to-first-
# token was 6.5s of silent thinking; support answers over retrieved
# context don't need deliberation. Quality parity is verified by the
# P4 golden-set judge - if it degrades there, this is the knob to raise.
ANSWER_REASONING_EFFORT = "minimal"

# Retrieval
QDRANT_URL = "http://localhost:6333"
COLLECTION = "home_services_kb"
TOP_K = 4
MIN_SCORE = 0.45  # below this, retrieval found nothing relevant -> escalate path

# Memory
SUMMARIZE_AFTER_TURNS = 6  # compress history once it exceeds this many messages
KEEP_VERBATIM = 4  # newest messages that always stay word-for-word

# $/1M tokens - verify against the current OpenAI pricing page
PRICES = {
    "gpt-5": {"input": 1.25, "cached": 0.125, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "cached": 0.025, "output": 2.00},
}

VALID_SERVICE_LINES = [
    "hvac", "plumbing", "electrical", "roofing", "solar", "windows-doors",
    "insulation", "water-heaters", "drain-sewer", "generators",
    "smart-home", "gutters", "company",
]
