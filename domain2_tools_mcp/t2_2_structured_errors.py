"""
Task 2.2 — Implement structured error responses for MCP tools.
Task 5.3 — Error propagation across multi-agent systems.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain2_tools_mcp/t2_2_structured_errors.py

THE ERROR TAXONOMY THE EXAM USES
--------------------------------
  transient   timeout, service unavailable, 503        -> retryable, retry it
  validation  bad input, malformed id, not found       -> not retryable as-is,
                                                          fix the input / ask
  business    policy violation (refund window closed)  -> NOT retryable ever;
                                                          explain to the customer
  permission  caller lacks authorisation               -> not retryable; escalate

The exam's core claim: uniform errors ("Operation failed") prevent the agent from
making an appropriate recovery decision, because all four categories collapse
into one indistinguishable signal. The agent then does the same wrong thing for
all of them — usually retrying a business-rule violation until it gives up.

The fields that carry the decision:
    isError: true            MCP's flag that this result is a failure
    errorCategory            transient | validation | business | permission
    isRetryable: true|false  the retry decision, decided by the SERVER
    message                  human-readable, and customer-safe for business errors

Plus one distinction that is its own exam item: an ACCESS FAILURE (the query
could not run) is not the same as a VALID EMPTY RESULT (the query ran and matched
nothing). Collapsing them means the coordinator either retries a successful
search or reports "no data" for a search that never happened.

This script runs the same four failures under both regimes and shows what the
agent does with each.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of

TOOL = [{
    "name": "process_refund",
    "description": (
        "Issue a refund against a delivered order. Returns a refund_id on success. "
        "Failures are returned as structured error objects, not exceptions — read "
        "errorCategory and isRetryable to decide what to do next."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string"}, "amount_usd": {"type": "number"}},
        "required": ["order_id", "amount_usd"],
    },
}]

SEARCH_TOOL = [{
    "name": "search_orders",
    "description": (
        "Search a customer's orders by keyword. Returns {matches: [...]} on success. "
        "A successful search that matched nothing returns matches: [] with "
        "status 'ok' — that is NOT an error. A search that could not run returns an "
        "error object with errorCategory set."
    ),
    "input_schema": {"type": "object",
                     "properties": {"customer_id": {"type": "string"}, "query": {"type": "string"}},
                     "required": ["customer_id", "query"]},
}]

# ---------------------------------------------------------------------------
# The four failures, in both shapes.
# ---------------------------------------------------------------------------
UNIFORM = json.dumps({"error": "Operation failed. Please try again."})

STRUCTURED = {
    "transient": json.dumps({
        "isError": True,
        "errorCategory": "transient",
        "isRetryable": True,
        "retryAfterSeconds": 2,
        "message": "Payment gateway timed out after 30s. The refund was not issued.",
    }),
    "validation": json.dumps({
        "isError": True,
        "errorCategory": "validation",
        "isRetryable": False,
        "field": "order_id",
        "message": "order_id 'ORD-9999999' does not exist. Confirm the order number "
                   "with the customer before retrying.",
    }),
    "business": json.dumps({
        "isError": True,
        "errorCategory": "business",
        "isRetryable": False,
        "policyCode": "REFUND_WINDOW_EXPIRED",
        "message": "This order was delivered 94 days ago and the refund window is 30 "
                   "days, so a refund cannot be issued.",
        # A customer-safe explanation the agent can relay verbatim. Without this the
        # agent invents its own wording for a policy decision, which is how you end
        # up with agents inventing policy.
        "customerExplanation": "Refunds are available for 30 days after delivery, and "
                               "this order was delivered about three months ago. I can "
                               "open a store-credit request or connect you with a "
                               "supervisor to review an exception.",
        "alternativeWorkflows": ["issue_store_credit", "escalate_to_human"],
    }),
    "permission": json.dumps({
        "isError": True,
        "errorCategory": "permission",
        "isRetryable": False,
        "message": "This API key is not authorised to issue refunds above $1,000. "
                   "Escalate to an agent with refund-approval scope.",
    }),
}

SYSTEM = (
    "You are a customer support agent. When a tool fails, decide what to do next and "
    "state your decision explicitly in the form 'DECISION: <retry|ask_customer|"
    "explain_and_stop|escalate>' followed by one sentence of reasoning."
)


def probe(c, tool_result: str, user_turn: str, tools=TOOL, tool_name="process_refund"):
    """
    Send a request, intercept the first tool call, return the given failure, and
    report what the agent decided to do with it.
    """
    messages = [{"role": "user", "content": user_turn}]
    r = c.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM, tools=tools,
                          tool_choice={"type": "any"}, messages=messages)
    calls = [b for b in r.content if b.type == "tool_use"]
    if not calls:
        return "(no tool call)"
    messages.append({"role": "assistant", "content": r.content})
    messages.append({"role": "user", "content": [{
        "type": "tool_result", "tool_use_id": calls[0].id,
        "content": tool_result, "is_error": True,
    }]})
    r2 = c.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM, tools=tools,
                           messages=messages)
    retried = [b.name for b in r2.content if b.type == "tool_use"]
    text = text_of(r2)
    return text, retried


def decision_of(text: str) -> str:
    """
    Pull the DECISION token out of the reply.

    Note the markdown strip. The model writes `DECISION: **escalate**` often
    enough that a naive `.split()[0]` yields `**escalate**`, which then fails
    every string comparison downstream and makes a correct answer look wrong.
    Grading model output on formatted text is its own small discipline — strip
    the formatting before you compare, or your evaluation measures markdown.
    """
    for line in str(text).splitlines():
        if "DECISION:" in line:
            token = line.split("DECISION:", 1)[1].strip()
            token = token.lstrip("*_` ").split()[0] if token.strip("*_` ") else ""
            return token.strip("*_`.,:;").lower()
    return "?"


def main():
    c = client()
    banner("Structured error responses", "Task 2.2 / 5.3 — error taxonomy and recovery")

    ask = "Please refund order ORD-88213 for $1,395."

    bad("Regime 1 — every failure returns the same uniform error")
    print(f'    tool_result: {UNIFORM}')
    for label in ["transient", "validation", "business", "permission"]:
        text, retried = probe(c, UNIFORM, ask)
        print(f"    [{label:10s}] decision={decision_of(text):16s} "
              f"retried_tools={retried}")
    note("Four genuinely different situations, one indistinguishable signal. The agent "
         "cannot do anything but guess — and it guesses the same way every time, which "
         "means one of the four is always handled wrong.")

    good("Regime 2 — structured errors carrying category and retryability")
    expected = {"transient": "retry", "validation": "ask_customer",
                "business": "explain_and_stop", "permission": "escalate"}
    for label, payload in STRUCTURED.items():
        text, retried = probe(c, payload, ask)
        d = decision_of(text)
        match = "OK " if d.startswith(expected[label][:5]) else "  "
        print(f"    [{match}] {label:10s} decision={d:18s} retried={bool(retried)}")
        if label == "business":
            show("      customer-facing wording produced", text[:420])
    note("Each category produced a different, appropriate recovery — because the "
         "SERVER made the retryability decision and handed it over, rather than "
         "leaving the agent to infer it from prose.")

    # -- empty result vs access failure ------------------------------------
    section("Access failure vs valid empty result")
    print("  Both of these 'return nothing'. They demand opposite responses.")

    valid_empty = json.dumps({
        "status": "ok", "matches": [], "searched": 412,
        "message": "Search completed successfully. No orders matched 'blue widget'.",
    })
    access_failure = json.dumps({
        "isError": True, "errorCategory": "transient", "isRetryable": True,
        "message": "Order index unavailable (503). The search did not run.",
        "partialResults": None,
    })

    q = "Do I have any orders for a blue widget? I'm CUST-4417."
    for label, payload in [("valid empty result", valid_empty), ("access failure", access_failure)]:
        text, retried = probe(c, payload, q, tools=SEARCH_TOOL, tool_name="search_orders")
        print(f"    [{label:19s}] decision={decision_of(text):16s} retried={bool(retried)}")
    note("The empty result should end the search and report 'you have none'. The access "
         "failure should be retried. Collapsing them into 'no results' is the exam's "
         "silent-suppression anti-pattern: the coordinator reports a confident 'nothing "
         "found' for a query that never executed.")

    section("Propagating to a coordinator (Task 5.3)")
    print(
        "  A subagent should handle transient failures LOCALLY — retry, then move on —\n"
        "  and only propagate what it could not resolve. When it does propagate, the\n"
        "  payload is not a status string; it is:\n\n"
        "      {\n"
        '        \"failureType\": \"timeout\",\n'
        '        \"attempted\": \"web search: AI impact on session musicians 2024-2025\",\n'
        '        \"partialResults\": [ ...the 3 sources it did get... ],\n'
        '        \"alternatives\": [\"retry with narrower date range\", \"try the news index\"]\n'
        "      }\n\n"
        "  Given that, the coordinator can retry with a modified query, route around the\n"
        "  failure, or proceed with partial results and ANNOTATE the coverage gap in the\n"
        "  final report. Given 'search unavailable', it can only guess.\n\n"
        "  Two anti-patterns the exam names explicitly:\n"
        "    - silently returning empty results as success (hides the failure entirely)\n"
        "    - terminating the whole workflow on one subagent failure (throws away the\n"
        "      work that DID succeed)"
    )

    takeaway(
        "isError + errorCategory + isRetryable + message. The server decides retryability.",
        "transient=retry, validation=fix input, business=explain & stop, permission=escalate.",
        "Business errors need a customer-safe explanation, or the agent invents policy.",
        "Access failure != valid empty result. Never collapse them.",
        "Subagents recover locally; propagate only what they can't fix, WITH partial results.",
        "Never suppress errors as success; never kill the workflow over one failure.",
    )


if __name__ == "__main__":
    main()
