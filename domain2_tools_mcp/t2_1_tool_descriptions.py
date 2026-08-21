"""
Task 2.1 — Design effective tool interfaces with clear descriptions and boundaries.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain2_tools_mcp/t2_1_tool_descriptions.py

THIS IS SAMPLE QUESTION 2
-------------------------
"Production logs show the agent frequently calls get_customer when users ask
about orders... Both tools have minimal descriptions ('Retrieves customer
information' / 'Retrieves order details') and accept similar identifier formats.
What's the most effective FIRST step?"

  A. Add 5-8 few-shot examples of correct routing.
  B. Expand each tool's description: input formats, example queries, edge cases,
     and boundaries explaining when to use it versus similar tools.   <-- correct
  C. Build a keyword-based routing layer.
  D. Consolidate into one lookup_entity tool.

Why B: tool descriptions are the PRIMARY mechanism the model uses to select a
tool. Minimal descriptions starve that mechanism, so fix the root cause. A is
token overhead that papers over the real problem. C throws away the model's
language understanding and has to be maintained forever. D is a legitimate
architecture change but is far more than a "first step" warrants.

Note the exam's framing: "most effective FIRST step". Several options are not
wrong in the abstract — they are wrong as the first, cheapest, highest-leverage
move. Expect that framing on the real exam.

This script measures routing accuracy under three description regimes and then
demonstrates the two related traps: overlapping tool names, and a system prompt
whose keywords silently override good descriptions.
"""

import sys
import os
import json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway

# ---------------------------------------------------------------------------
# Regime 1 — minimal descriptions (the exam's broken starting state)
# ---------------------------------------------------------------------------
TOOLS_MINIMAL = [
    {
        "name": "get_customer",
        "description": "Retrieves customer information.",
        "input_schema": {"type": "object",
                         "properties": {"identifier": {"type": "string"}},
                         "required": ["identifier"]},
    },
    {
        "name": "lookup_order",
        "description": "Retrieves order details.",
        "input_schema": {"type": "object",
                         "properties": {"identifier": {"type": "string"}},
                         "required": ["identifier"]},
    },
]

# ---------------------------------------------------------------------------
# Regime 2 — the same two tools, described properly.
#
# The four things the exam wants in a description:
#   1. input formats it accepts
#   2. example queries that should route here
#   3. edge cases
#   4. an explicit boundary vs the similar tool
# ---------------------------------------------------------------------------
TOOLS_RICH = [
    {
        "name": "get_customer",
        "description": (
            "Look up a CUSTOMER ACCOUNT and return the person's profile: customer_id, "
            "name, email, loyalty tier, account status, and lifetime value.\n\n"
            "Accepts: an email address (dana@example.com), a customer id "
            "(CUST-#####), or a phone number in E.164 form.\n"
            "Use for queries like: 'what tier am I?', 'is my account active?', "
            "'update my email', 'who is CUST-4417?'.\n"
            "Edge cases: if several accounts match a name, returns all matches — ask "
            "the customer for an additional identifier rather than guessing.\n\n"
            "BOUNDARY vs lookup_order: this tool knows nothing about orders, "
            "shipments, or refunds. If the query names an order (ORD-#####) or asks "
            "about a purchase, delivery, or return, call lookup_order instead. Call "
            "this tool first ONLY when you need a verified customer_id in order to "
            "call lookup_order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"identifier": {
                "type": "string",
                "description": "Email, CUST-##### id, or E.164 phone number"}},
            "required": ["identifier"],
        },
    },
    {
        "name": "lookup_order",
        "description": (
            "Look up a single ORDER and return its line items, amount, payment "
            "status, fulfilment status, carrier tracking, and delivery date.\n\n"
            "Accepts: an order id (ORD-#####, also written '#12345' or 'order "
            "12345'), or a carrier tracking number.\n"
            "Use for queries like: 'where is order #12345?', 'has my order shipped?', "
            "'what did I pay for ORD-88213?', 'I want to return this order'.\n"
            "Edge cases: returns not_found for orders older than 24 months (archived); "
            "direct the customer to the archive request flow in that case.\n\n"
            "BOUNDARY vs get_customer: this tool takes an ORDER identifier, not a "
            "person. It does not return profile or account data. If the query is "
            "about the account itself rather than a specific purchase, use "
            "get_customer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"identifier": {
                "type": "string",
                "description": "Order id such as ORD-88213 or '#12345', or a tracking number"}},
            "required": ["identifier"],
        },
    },
]

# ---------------------------------------------------------------------------
# Regime 3 — the "analyze_content vs analyze_document" overlap the exam names,
# and its fix: rename + re-scope so there is no functional overlap left.
# ---------------------------------------------------------------------------
TOOLS_OVERLAPPING = [
    {"name": "analyze_content", "description": "Analyzes content and extracts information.",
     "input_schema": {"type": "object", "properties": {"input": {"type": "string"}},
                      "required": ["input"]}},
    {"name": "analyze_document", "description": "Analyzes documents and extracts information.",
     "input_schema": {"type": "object", "properties": {"input": {"type": "string"}},
                      "required": ["input"]}},
]

TOOLS_SPLIT = [
    {
        "name": "extract_web_results",
        "description": (
            "Parse a WEB SEARCH RESULT PAGE (HTML or a search API response) and return "
            "the ranked result entries: title, URL, snippet, and rank. Input is raw "
            "web content, never a local file path. "
            "BOUNDARY: for a document already on disk, use extract_data_points, "
            "summarize_content, or verify_claim_against_source."
        ),
        "input_schema": {"type": "object",
                         "properties": {"html": {"type": "string", "description": "Raw search result markup"}},
                         "required": ["html"]},
    },
    {
        "name": "extract_data_points",
        "description": (
            "Pull specific NAMED FIELDS out of a document on disk. You must say which "
            "fields you want. Returns one value per requested field, plus the page or "
            "section each came from, or null when the document does not contain it. "
            "BOUNDARY: does not summarise and does not judge truth — use "
            "summarize_content or verify_claim_against_source for those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"},
                           "fields": {"type": "array", "items": {"type": "string"}}},
            "required": ["path", "fields"],
        },
    },
    {
        "name": "summarize_content",
        "description": (
            "Produce a prose summary of a document on disk at a requested length. "
            "BOUNDARY: returns prose, not structured fields. If the caller needs "
            "specific values they can compute with, use extract_data_points."
        ),
        "input_schema": {"type": "object",
                         "properties": {"path": {"type": "string"},
                                        "max_words": {"type": "integer"}},
                         "required": ["path"]},
    },
    {
        "name": "verify_claim_against_source",
        "description": (
            "Check whether a specific factual CLAIM is supported by a specific "
            "document, and return supported / contradicted / not_addressed together "
            "with the supporting excerpt. "
            "BOUNDARY: verifies one claim you already have. It does not discover "
            "claims — use extract_data_points for that."
        ),
        "input_schema": {"type": "object",
                         "properties": {"claim": {"type": "string"}, "path": {"type": "string"}},
                         "required": ["claim", "path"]},
    },
]

# Ambiguous-ish queries with an unambiguous CORRECT routing.
ROUTING_CASES = [
    ("check my order #12345", "lookup_order"),
    ("has ORD-88213 shipped yet?", "lookup_order"),
    ("I want to return the thing I bought last week, order 44120", "lookup_order"),
    ("what loyalty tier am I on? my email is dana@example.com", "get_customer"),
    ("is my account still active?", "get_customer"),
]


def first_tool(c, tools, query, system=None):
    """Return the name of the first tool the model reaches for, or None."""
    r = c.messages.create(
        model=MODEL, max_tokens=2000, tools=tools,
        tool_choice={"type": "any"},   # force a tool call so every trial is comparable
        system=system or "You are a customer support agent. Use the available tools.",
        messages=[{"role": "user", "content": query}],
    )
    calls = [b for b in r.content if b.type == "tool_use"]
    return calls[0].name if calls else None


def measure(c, tools, label, system=None):
    print(f"\n  {label}")
    correct = 0
    for query, expected in ROUTING_CASES:
        got = first_tool(c, tools, query, system=system)
        ok = got == expected
        correct += ok
        print(f"    [{'OK ' if ok else 'BAD'}] {query[:52]:54s} -> {got}"
              f"{'' if ok else f'  (expected {expected})'}")
    print(f"    routing accuracy: {correct}/{len(ROUTING_CASES)}")
    return correct


def main():
    c = client()
    banner("Tool descriptions drive tool selection",
           "Task 2.1 — this is exam Sample Question 2")

    bad("Regime 1 — minimal descriptions")
    print('    get_customer: "Retrieves customer information."')
    print('    lookup_order: "Retrieves order details."')
    n_min = measure(c, TOOLS_MINIMAL, "routing trials")

    good("Regime 2 — descriptions with formats, examples, edge cases, boundaries")
    n_rich = measure(c, TOOLS_RICH, "routing trials")

    section("Result")
    print(f"  minimal descriptions: {n_min}/{len(ROUTING_CASES)}")
    print(f"  rich descriptions:    {n_rich}/{len(ROUTING_CASES)}")
    print("  Same model, same queries, same schemas. The only variable is the prose.")
    if n_rich <= n_min:
        note("No gap on this small sample — modern models route these two apart well "
             "even from thin descriptions. The exam's premise is a production system "
             "where the gap DID show up; the mechanism (descriptions are the primary "
             "selection signal) is what you are being tested on, and it holds regardless "
             "of whether five trials happen to expose it.")

    # -- Overlap ----------------------------------------------------------
    section("Overlapping tools: the analyze_content / analyze_document trap")
    bad("Two near-identical descriptions")
    print('    analyze_content:  "Analyzes content and extracts information."')
    print('    analyze_document: "Analyzes documents and extracts information."')
    counts = Counter(
        first_tool(c, TOOLS_OVERLAPPING,
                   "Pull the revenue figure out of the Q3 report I saved at ./q3.pdf")
        for _ in range(4)
    )
    print(f"    4 identical requests routed to: {dict(counts)}")
    if len(counts) > 1:
        note("Non-deterministic routing between two tools that a human cannot tell "
             "apart either. The model is not the problem — the interface is.")
    else:
        note("Consistent this run, but note there is no PRINCIPLE distinguishing them. "
             "Consistency you cannot explain is not reliability.")

    good("Renamed and split into purpose-specific tools with explicit boundaries")
    for q, expect in [
        ("Pull the revenue figure and headcount out of ./q3.pdf", "extract_data_points"),
        ("Give me a two-paragraph overview of ./q3.pdf", "summarize_content"),
        ("Does ./q3.pdf actually support the claim that margins improved?", "verify_claim_against_source"),
        ("Here is the raw HTML of a search results page — get me the top links", "extract_web_results"),
    ]:
        got = first_tool(c, TOOLS_SPLIT, q)
        print(f"    [{'OK ' if got == expect else 'BAD'}] {q[:56]:58s} -> {got}")
    note("Each tool now has one purpose, a defined input/output contract, and a "
         "BOUNDARY line naming which sibling to use instead. That last part is what "
         "actually kills misrouting.")

    # -- System prompt keyword sensitivity --------------------------------
    section("System prompts can silently override good descriptions")
    bad("A keyword-sensitive instruction in the system prompt")
    leaky_system = (
        "You are a research assistant. Whenever the user mentions a document, "
        "always analyze the document thoroughly before responding."
    )
    got = first_tool(
        c, TOOLS_SPLIT,
        "Here is the raw HTML of a search results page for my document research — "
        "get me the top links.",
        system=leaky_system,
    )
    print(f"    routed to: {got}  (correct: extract_web_results)")
    note("The word 'document' in the system prompt creates an association that can "
         "pull routing toward the document tools even when the request is about web "
         "content. When tool selection misbehaves, audit the SYSTEM PROMPT for "
         "keyword-sensitive phrasing before you rewrite the tool descriptions again.")

    takeaway(
        "Tool descriptions are the PRIMARY selection mechanism. Fix them first.",
        "A good description has: input formats, example queries, edge cases, BOUNDARIES.",
        "Overlapping descriptions cause misrouting — rename and re-scope, don't add examples.",
        "Splitting a generic tool means giving each piece a defined input/output contract.",
        "Keyword-sensitive system prompts can override even well-written descriptions.",
        "Exam phrasing: 'most effective FIRST step' rewards root-cause + low-effort.",
    )


if __name__ == "__main__":
    main()
