"""Shared LLM plumbing: one traced client, one place for cost math."""

from dotenv import load_dotenv
from langfuse.openai import OpenAI  # every call auto-traced to Langfuse

from bot.config import PRICES

load_dotenv()

client = OpenAI()


def usage_delta(model: str, usage) -> dict:
    """Turn one API response's usage into state-counter increments.

    Returned keys match the observability fields in State; callers add
    them to the running totals they read from state.
    """
    cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
    prices = PRICES[model]
    cost = (
        (usage.prompt_tokens - cached) * prices["input"]
        + cached * prices["cached"]
        + usage.completion_tokens * prices["output"]
    ) / 1_000_000
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cost": cost,
    }
