"""Answer node: gpt-5 writes the reply from retrieved context, streaming.

The only premium-model call in the graph, given the minimum context that
makes it correct: a short system prompt, the conversation summary, the
retrieved chunks, and the last few verbatim turns. Compare v1: the whole
KB + all tools + the whole history, every call.

Test standalone with:  uv run python -m bot.answer
(runs a mini pipeline: route -> retrieve -> answer, no graph yet)
"""

from bot.config import ANSWER_REASONING_EFFORT, MODEL_ANSWER
from bot.llm import client, usage_delta
from bot.prompts import ANSWER_SYSTEM
from bot.state import State

try:
    from langgraph.config import get_stream_writer
except ImportError:  # pragma: no cover
    get_stream_writer = None


def _writer():
    """Token emitter: real stream writer inside a running graph, no-op outside."""
    if get_stream_writer is not None:
        try:
            return get_stream_writer()
        except Exception:
            pass
    return lambda _payload: None


def _format_context(retrieved: list[dict]) -> str:
    if not retrieved:
        return "(nothing relevant found in the knowledge base)"
    return "\n\n".join(
        f"[{c['service_line']} / {c['section']} (relevance {c['score']})]\n{c['text']}"
        for c in retrieved
    )


def answer(state: State) -> dict:
    """Read summary + retrieved + recent turns, stream the reply, append it."""
    system = ANSWER_SYSTEM.format(
        summary=state.get("summary") or "(none yet)",
        context=_format_context(state.get("retrieved", [])),
    )
    messages = [{"role": "system", "content": system}] + state["messages"][-6:]

    write = _writer()
    stream = client.chat.completions.create(
        model=MODEL_ANSWER,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},  # else streamed calls report no usage
        reasoning_effort=ANSWER_REASONING_EFFORT,
        name="v2-answer",
    )
    parts: list[str] = []
    usage = None
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            token = chunk.choices[0].delta.content
            parts.append(token)
            write({"token": token})  # live tokens for the CLI / SSE frontend
        if chunk.usage:  # arrives once, on the final chunk
            usage = chunk.usage
    reply = "".join(parts)

    delta = usage_delta(MODEL_ANSWER, usage)
    return {
        "messages": state["messages"] + [{"role": "assistant", "content": reply}],
        "total_prompt_tokens": state.get("total_prompt_tokens", 0) + delta["prompt_tokens"],
        "total_completion_tokens": state.get("total_completion_tokens", 0) + delta["completion_tokens"],
        "total_cost": state.get("total_cost", 0.0) + delta["cost"],
    }


if __name__ == "__main__":
    # Mini pipeline, no graph: the three built nodes chained by hand.
    from bot.retrieve import retrieve
    from bot.router import route

    state: State = {
        "messages": [{"role": "user", "content": "how much is a tankless water heater?"}]
    }
    state.update(route(state))
    print(f"[router] {state['service_line']} / {state['intent']} "
          f"conf={state['confidence']:.2f}")
    state.update(retrieve(state))
    print(f"[retrieve] {len(state['retrieved'])} chunks: "
          f"{[c['section'] for c in state['retrieved']]}")
    state.update(answer(state))
    print(f"\nsunny> {state['messages'][-1]['content']}\n")
    print(f"[turn totals] in={state['total_prompt_tokens']} "
          f"out={state['total_completion_tokens']} "
          f"cost=${state['total_cost']:.4f}")
