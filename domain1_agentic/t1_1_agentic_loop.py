"""
Task 1.1 — Design and implement agentic loops for autonomous task execution.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain1_agentic/t1_1_agentic_loop.py

THE ONE THING THE EXAM TESTS HERE
---------------------------------
Loop control flow is driven by `stop_reason`, and by nothing else.

    stop_reason == "tool_use"  -> execute the requested tools, append the results,
                                  iterate again
    stop_reason == "end_turn"  -> the model is done; present the final response

Every wrong answer in this objective is some other termination signal:

  (a) parsing the assistant's natural-language text for "done"/"finished"
  (b) using an iteration cap as the PRIMARY stopping mechanism
  (c) treating "the response contains a text block" as completion

(c) is the sneakiest, because it is *almost* right and fails silently: Claude
routinely emits a text block AND a tool_use block in the same response ("Let me
look that up for you." + lookup_order(...)). A loop that stops on "saw text"
truncates the agent mid-task and returns a half-answer. This script demonstrates
that failure with a real API call rather than asserting it.

An iteration cap is still correct to HAVE — as a runaway backstop, not as the
control-flow mechanism. The distinction is exactly what the exam item turns on.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, show, section, takeaway, text_of

# ---------------------------------------------------------------------------
# A tiny two-tool backend, mirroring the exam's Scenario 1 support agent.
# ---------------------------------------------------------------------------
CUSTOMERS = {
    "CUST-4417": {"customer_id": "CUST-4417", "name": "Dana Whitfield", "tier": "gold", "verified": True},
}
ORDERS = {
    "ORD-88213": {"order_id": "ORD-88213", "customer_id": "CUST-4417", "item": "Aeron chair",
                  "amount_usd": 1395.00, "status": "delivered", "delivered_on": "2026-07-29"},
}

TOOLS = [
    {
        "name": "get_customer",
        "description": (
            "Look up a customer account by email address and return the canonical "
            "customer record, including the verified customer_id required by every "
            "downstream order and refund operation. Use this FIRST whenever the user "
            "identifies themselves by name or email rather than by a customer_id. "
            "Returns: customer_id, name, tier, verified. "
            "Does NOT return orders — use lookup_order for that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "The customer's email address, e.g. dana@example.com"}
            },
            "required": ["email"],
        },
    },
    {
        "name": "lookup_order",
        "description": (
            "Retrieve the full details of a single order by its order_id (format: "
            "ORD-#####), including item, amount, status, and delivery date. Requires a "
            "verified customer_id from get_customer so the order can be confirmed as "
            "belonging to the caller. Use this when the user asks about a specific "
            "order, shipment, or return. "
            "Does NOT search orders by customer — it resolves one known order_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier, e.g. ORD-88213"},
                "customer_id": {"type": "string", "description": "Verified customer_id from get_customer"},
            },
            "required": ["order_id", "customer_id"],
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    """Dispatch a tool call. Returns a JSON-ish string the model reads back."""
    import json

    if name == "get_customer":
        rec = next((c for c in CUSTOMERS.values() if args["email"].startswith(c["name"].split()[0].lower())), None)
        rec = rec or CUSTOMERS["CUST-4417"]
        return json.dumps(rec)
    if name == "lookup_order":
        order = ORDERS.get(args.get("order_id"))
        if not order:
            return json.dumps({"error": "order_not_found", "order_id": args.get("order_id")})
        return json.dumps(order)
    return json.dumps({"error": "unknown_tool", "name": name})


SYSTEM = (
    "You are a customer support agent. Verify the customer with get_customer before "
    "looking up any order. Answer the customer's question completely."
)
PROMPT = (
    "Hi, this is Dana (dana@example.com). Can you tell me what I paid for order "
    "ORD-88213 and whether it has been delivered?"
)


# ---------------------------------------------------------------------------
# CORRECT: control flow keyed on stop_reason
# ---------------------------------------------------------------------------
def correct_loop(c, max_iterations: int = 12):
    """
    The canonical agentic loop.

    Note the shape carefully — the exam's distractors each break one line of it:

      1. Send the full message history every time (the API is stateless).
      2. Append the assistant's ENTIRE `response.content` to history, not just the
         text. Dropping the tool_use blocks makes the following tool_result
         orphaned and the request 400s.
      3. Collect ALL tool_result blocks into ONE user message. Splitting them
         across several user messages silently teaches Claude to stop making
         parallel tool calls.
      4. Terminate on stop_reason, and only on stop_reason.
    """
    messages = [{"role": "user", "content": PROMPT}]
    iterations = 0

    while True:
        iterations += 1
        if iterations > max_iterations:
            # Backstop, NOT the control-flow mechanism. Reaching this is a bug
            # signal worth alerting on, not a normal exit path.
            raise RuntimeError(f"runaway loop: exceeded {max_iterations} iterations")

        response = c.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages
        )
        print(f"  iteration {iterations}: stop_reason={response.stop_reason!r}  "
              f"blocks={[b.type for b in response.content]}")

        # (4) The single termination decision.
        if response.stop_reason == "end_turn":
            return text_of(response), iterations

        if response.stop_reason == "max_tokens":
            raise RuntimeError("hit max_tokens mid-task — raise max_tokens or stream")

        if response.stop_reason == "refusal":
            # Safety classifiers declined. Never index into content[0] before this
            # check — on a refusal the content list can be empty.
            return "[refused]", iterations

        if response.stop_reason == "pause_turn":
            # A server-side tool ran long. Re-send to resume; do NOT inject a
            # "continue" user message.
            messages.append({"role": "assistant", "content": response.content})
            continue

        # stop_reason == "tool_use": run the tools and feed results back.
        messages.append({"role": "assistant", "content": response.content})  # (2)

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"      -> executing {block.name}({block.input})")
            try:
                result = execute_tool(block.name, block.input)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )
            except Exception as exc:
                # Return the failure to the model as a tool_result rather than
                # raising. The agent can then adapt. Dropping the block entirely
                # would orphan the tool_use and 400 the next request.
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id,
                     "content": f"error: {exc}", "is_error": True}
                )

        messages.append({"role": "user", "content": tool_results})  # (3)


# ---------------------------------------------------------------------------
# ANTI-PATTERN: stop when the response contains any text
# ---------------------------------------------------------------------------
def text_presence_loop(c, max_iterations: int = 12):
    """
    Distractor (c): "the assistant produced prose, so it must be finished."

    Claude very often narrates before acting, putting a text block and a tool_use
    block in the SAME response. This loop returns that narration as the final
    answer and never runs the tools.
    """
    messages = [{"role": "user", "content": PROMPT}]
    for i in range(max_iterations):
        response = c.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages
        )
        text = text_of(response)
        if text.strip():  # <-- the bug
            return text, i + 1, response.stop_reason
        messages.append({"role": "assistant", "content": response.content})
        results = [
            {"type": "tool_result", "tool_use_id": b.id, "content": execute_tool(b.name, b.input)}
            for b in response.content if b.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})
    return "[cap hit]", max_iterations, None


def main():
    c = client()
    banner("Agentic loop control flow", "Task 1.1 — stop_reason drives the loop")

    good("Loop terminating on stop_reason == 'end_turn'")
    answer, iters = correct_loop(c)
    show("Final answer", answer)
    note(f"Completed in {iters} iterations. The tools actually ran.")

    bad("Loop terminating on 'the response contains text'")
    answer2, iters2, sr = text_presence_loop(c)
    show("Returned to the user", answer2)
    note(f"Stopped after {iters2} iteration(s) with stop_reason={sr!r}.")
    if sr == "tool_use":
        note("stop_reason was 'tool_use' — the model was mid-task and the loop "
             "returned its narration as if it were the answer.")
    else:
        note("This run happened to emit no leading narration. Re-run it; the failure "
             "is intermittent, which is exactly what makes it dangerous in production.")

    section("Why an iteration cap is not the answer either")
    print(
        "  An iteration cap cannot distinguish 'finished in 3 turns' from 'stuck in a\n"
        "  retry loop for 3 turns'. It has no access to the model's intent. Keep the cap\n"
        "  as a runaway backstop — raise on it, don't return on it — and let stop_reason\n"
        "  make the actual decision."
    )

    takeaway(
        "Continue while stop_reason == 'tool_use'; stop when it is 'end_turn'.",
        "Append the whole response.content to history — tool_use blocks included.",
        "All tool_results for one turn go in ONE user message.",
        "Iteration caps are backstops. Natural-language 'done' parsing is never correct.",
    )


if __name__ == "__main__":
    main()
