"""Central knobs for the v2 bot. Change here, not scattered through nodes."""

# Model tiering: cheap-and-fast for routing/judging/summarizing,
# premium only where the customer actually reads the output.
MODEL_ROUTER = "gpt-5-mini"
MODEL_ANSWER = "gpt-5"
MODEL_SUMMARY = "gpt-5-mini"

# Keep the answer model from burning hidden reasoning tokens on
# support questions (P1 finding: output tokens were 81% of cost).
ANSWER_REASONING_EFFORT = "low"

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
