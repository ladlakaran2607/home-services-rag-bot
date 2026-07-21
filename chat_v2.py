"""Terminal chat with the v2 graph - and a live view of the pipeline.

Prints each node's decision as it happens ([router], [retrieve] lines),
then streams the answer token by token. This is the terminal preview of
the P3 frontend's trace panel.

Commands:  /human  simulates the "Talk to a human" button (structured
           action, skips the router).  quit  exits.

Run with:  uv run python chat_v2.py
"""

from langfuse import get_client

from bot.graph import build_graph

THREAD = {"configurable": {"thread_id": "cli-session"}}


def current_messages(graph) -> list[dict]:
    snapshot = graph.get_state(THREAD)
    return (snapshot.values or {}).get("messages", []) if snapshot else []


def main() -> None:
    graph = build_graph()
    print("[v2] chat ready - /human for the escalation button, quit to exit\n")

    while True:
        user_input = input("you> ").strip()
        if user_input.lower() in {"quit", "exit"}:
            break
        if not user_input:
            continue

        history = current_messages(graph)
        if user_input == "/human":
            turn_input = {"messages": history, "action": "escalate"}
        else:
            turn_input = {
                "messages": history + [{"role": "user", "content": user_input}]
            }

        streaming_text = False
        for mode, payload in graph.stream(
            turn_input, THREAD, stream_mode=["updates", "custom"]
        ):
            if mode == "custom" and "token" in payload:
                if not streaming_text:
                    print("sunny> ", end="", flush=True)
                    streaming_text = True
                print(payload["token"], end="", flush=True)
            elif mode == "updates":
                for node, update in payload.items():
                    if node == "router":
                        print(
                            f"   [router]   {update['service_line']} / "
                            f"{update['intent']} conf={update['confidence']:.2f}"
                        )
                    elif node == "retrieve":
                        sections = [c["section"] for c in update["retrieved"]]
                        print(f"   [retrieve] {len(sections)} chunks {sections}")
                    elif node == "booking":
                        captured = {k: v for k, v in (update.get("lead") or {}).items() if v}
                        print(f"   [booking]  lead so far: {captured}")
                        print(f"sunny> {update['messages'][-1]['content']}")
                    elif node == "escalate":
                        print(f"sunny> {update['messages'][-1]['content']}")
                    elif node == "summarize":
                        print(f"   [summarize] history -> {len(update['messages'])} "
                              f"verbatim msgs + summary: \"{update['summary']}\"")
        if streaming_text:
            print()

        values = graph.get_state(THREAD).values
        print(
            f"   [totals]   in={values.get('total_prompt_tokens', 0):,} "
            f"out={values.get('total_completion_tokens', 0):,} "
            f"cost=${values.get('total_cost', 0.0):.4f}\n"
        )

    get_client().flush()


if __name__ == "__main__":
    main()
