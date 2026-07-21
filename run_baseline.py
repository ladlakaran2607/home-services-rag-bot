"""Replay the scripted conversations in conversations.json against v1.

Produces results/baseline_v1.json: per-turn and per-conversation token,
cost, and tool-call numbers, plus the bot's actual answers (kept so a
judge model can later compare v2's answers against these for quality
parity). Reruns are cheap and reproducible - this is the "before"
measurement the whole project reports against.

Run with:  uv run python run_baseline.py
"""

import json
import time
from pathlib import Path

from langfuse import get_client
from langfuse.openai import OpenAI

from v1_naive import MODEL, TOOLS, build_system_prompt, cost_of, run_tool

CONVERSATIONS_FILE = Path("conversations.json")
RESULTS_DIR = Path("results")


def run_conversation(client: OpenAI, system_prompt: str, conv: dict) -> dict:
    """Play one scripted conversation, fresh history, and record everything."""
    messages = [{"role": "system", "content": system_prompt}]
    record = {"id": conv["id"], "description": conv["description"], "turns": []}

    for user_msg in conv["turns"]:
        messages.append({"role": "user", "content": user_msg})
        turn = {
            "user": user_msg,
            "assistant": None,
            "calls": 0,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "cost": 0.0,
            "tools_used": [],
        }
        while True:  # tool round-trips until the model answers in text
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                name=f"baseline-{conv['id']}",
            )
            usage = response.usage
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
            turn["calls"] += 1
            turn["prompt_tokens"] += usage.prompt_tokens
            turn["cached_tokens"] += cached
            turn["completion_tokens"] += usage.completion_tokens
            turn["cost"] += cost_of(usage)

            msg = response.choices[0].message
            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    result = run_tool(tc.function.name, json.loads(tc.function.arguments))
                    turn["tools_used"].append(tc.function.name)
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )
                continue
            turn["assistant"] = msg.content
            messages.append({"role": "assistant", "content": msg.content})
            break
        record["turns"].append(turn)

    for key in ("calls", "prompt_tokens", "cached_tokens", "completion_tokens", "cost"):
        record[key] = sum(t[key] for t in record["turns"])
    return record


def main() -> None:
    client = OpenAI()
    system_prompt = build_system_prompt()
    conversations = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
    RESULTS_DIR.mkdir(exist_ok=True)

    records = []
    for conv in conversations:
        started = time.time()
        record = run_conversation(client, system_prompt, conv)
        records.append(record)
        print(
            f"{conv['id']:<26} turns={len(record['turns'])} calls={record['calls']} "
            f"in={record['prompt_tokens']:,} (cached {record['cached_tokens']:,}) "
            f"out={record['completion_tokens']:,} cost=${record['cost']:.4f} "
            f"[{time.time() - started:.0f}s]"
        )

    totals = {
        key: sum(r[key] for r in records)
        for key in ("calls", "prompt_tokens", "cached_tokens", "completion_tokens", "cost")
    }
    report = {
        "bot": "v1-naive",
        "model": MODEL,
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "totals": totals,
        "conversations": records,
    }
    out_path = RESULTS_DIR / "baseline_v1.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== v1 baseline totals ===")
    print(f"  conversations:     {len(records)}")
    print(f"  api calls:         {totals['calls']}")
    print(f"  prompt tokens:     {totals['prompt_tokens']:,} (cached {totals['cached_tokens']:,})")
    print(f"  completion tokens: {totals['completion_tokens']:,}")
    print(f"  estimated cost:    ${totals['cost']:.4f}")
    print(f"\nwritten to {out_path}")
    get_client().flush()


if __name__ == "__main__":
    main()
