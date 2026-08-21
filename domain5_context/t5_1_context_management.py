"""
Task 5.1 — Manage conversation context to preserve critical information.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain5_context/t5_1_context_management.py

THREE FAILURES, THREE FIXES
---------------------------
1. PROGRESSIVE SUMMARIZATION destroys precision. Numbers, percentages, dates and
   customer-stated expectations get condensed into "the customer was unhappy
   about a delayed refund". The agent then cannot answer "how much?" and, worse,
   will answer anyway with something plausible.
   FIX: a persistent CASE FACTS block — transactional facts extracted into
   structured form and re-injected verbatim on every request, OUTSIDE the
   summarised history.

2. LOST IN THE MIDDLE. Models process the beginning and end of a long input
   reliably; material in the middle gets dropped. Aggregate 20 subagent findings
   and items 8-14 quietly vanish.
   FIX: put a key-findings summary at the BEGINNING, and give every section an
   explicit header so nothing depends on positional attention alone.

3. TOOL OUTPUT ACCUMULATION. An order lookup returns 40+ fields; 5 are relevant.
   The other 35 stay in context for the rest of the conversation, consuming
   budget proportional to their volume rather than their usefulness.
   FIX: trim tool output to the relevant fields BEFORE it enters context.

All three are measured live below.
"""

import sys
import os
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import (MODEL, client, banner, bad, good, note, section, show,
                    takeaway, text_of, usage_line)

# ---------------------------------------------------------------------------
# 1. Progressive summarization
# ---------------------------------------------------------------------------
LONG_HISTORY = """\
[turn 1]  Customer: Hi, I'm calling about order ORD-88213.
[turn 2]  Agent: Let me pull that up.
[turn 3]  Customer: I paid $1,395.00 on 2025-07-29 for an Aeron chair.
[turn 4]  Agent: I see it, delivered 2025-08-02.
[turn 5]  Customer: It arrived with a cracked base. I returned it on 2025-08-06,
          tracking 1Z994A. Your policy page says refunds process in 10 business
          days. It's been over three weeks.
[turn 6]  Agent: I'm sorry about that. Let me check the refund status.
[turn 7]  Customer: I was told on 2025-08-14 by an agent named Priya that it would
          be processed within 48 hours. That was 12 days ago.
[turn 8]  Agent: I don't see a refund record. Let me escalate.
[turn 9]  Customer: I also want the $40 expedited shipping refunded — I paid for
          two-day delivery and it took nine days.
[turn 10] Agent: Noted.
... (34 more turns of back and forth about scheduling a callback) ...
"""

VAGUE_SUMMARY = (
    "Summary of earlier conversation: The customer contacted us about a chair "
    "order that arrived damaged. They returned it and are waiting on a refund, "
    "which has taken longer than expected. They are frustrated and have spoken to "
    "a previous agent. They also raised a shipping concern."
)

# The same history, but with the transactional facts extracted into a structured
# block that is re-injected VERBATIM every turn, outside the summarised prose.
CASE_FACTS = json.dumps({
    "order_id": "ORD-88213",
    "item": "Aeron chair",
    "amount_paid_usd": 1395.00,
    "purchase_date": "2025-07-29",
    "delivery_date": "2025-08-02",
    "defect": "cracked base",
    "return_date": "2025-08-06",
    "return_tracking": "1Z994A",
    "stated_policy_sla_days": 10,
    "prior_commitment": {"by": "Priya", "on": "2025-08-14", "promised": "48 hours"},
    "secondary_claim": {"type": "expedited_shipping_refund", "amount_usd": 40.00,
                        "reason": "paid 2-day, delivered in 9 days"},
    "refund_status": "no record found",
}, indent=2)

PROBE = ("What exactly does this customer need refunded, and what specific "
         "commitments have we already made to them? Give amounts and dates.")

FACTS_TO_RECALL = {
    "order amount 1395": ["1395", "1,395"],
    "shipping claim $40": ["$40", "40.00", "40 "],
    "the 48-hour promise": ["48"],
    "prior agent Priya": ["priya"],
    "10-day policy SLA": ["10 business", "10 day", "ten day"],
    "return tracking": ["1z994a"],
}


def recall_score(answer: str):
    low = answer.lower()
    return {k: any(m.lower() in low for m in ms) for k, ms in FACTS_TO_RECALL.items()}


def ask(c, system, user):
    r = c.messages.create(model=MODEL, max_tokens=4000, system=system,
                          messages=[{"role": "user", "content": user}])
    return text_of(r), r


# ---------------------------------------------------------------------------
# 3. Tool output trimming
# ---------------------------------------------------------------------------
FAT_ORDER = {
    "order_id": "ORD-88213", "customer_id": "CUST-4417", "status": "delivered",
    "amount_usd": 1395.00, "currency": "USD", "delivered_on": "2025-08-02",
    "item": "Aeron chair", "sku": "AX-2-GRAPHITE", "qty": 1,
    # 30+ fields no return workflow will ever consult:
    "warehouse_id": "WH-14", "picker_id": "EMP-9921", "pick_time_ms": 44120,
    "pack_station": "PS-7", "carton_type": "C-XL", "carton_weight_kg": 22.4,
    "dim_l_cm": 84, "dim_w_cm": 68, "dim_h_cm": 41, "pallet_id": "PLT-3391",
    "route_code": "R-88-W", "driver_id": "DRV-221", "vehicle_id": "VH-45",
    "manifest_id": "MF-77120", "scan_events": [
        {"code": "PU", "ts": 1753747200}, {"code": "IT", "ts": 1753833600},
        {"code": "OD", "ts": 1753920000}, {"code": "DL", "ts": 1754006400},
    ],
    "insurance_policy": "INS-4412", "insured_value_usd": 1500.00,
    "customs_code": None, "hs_code": None, "origin_country": "US",
    "tax_jurisdiction": "CA-SF", "tax_rate": 0.0725, "tax_collected_usd": 101.14,
    "promo_code": None, "discount_usd": 0.0, "gift_wrap": False,
    "marketing_source": "paid_search", "campaign_id": "CMP-2025-Q3-014",
    "device_type": "desktop", "session_id": "sess_9f21aa", "ab_bucket": "B",
}
RETURN_RELEVANT = ["order_id", "customer_id", "status", "amount_usd", "delivered_on", "item"]


def main():
    c = client()
    banner("Context management", "Task 5.1 — summarization, position, tool output")

    # -- 1 -------------------------------------------------------------------
    section("1. Progressive summarization vs a persistent case-facts block")

    bad("Summarised history only")
    a1, r1 = ask(c, "You are a customer support agent continuing a long conversation.",
                 f"{VAGUE_SUMMARY}\n\n{PROBE}")
    show("Answer", a1[:700])
    s1 = recall_score(a1)
    print(f"    facts recovered: {sum(s1.values())}/{len(s1)}  "
          f"{[k for k, v in s1.items() if v]}")
    note("Every number in this answer is either absent or invented. The summary is a "
         "faithful description of the EMOTIONAL content and a total loss of the "
         "TRANSACTIONAL content — which is the only part you can act on.")

    good("Same summary PLUS a persistent case-facts block")
    a2, r2 = ask(
        c,
        "You are a customer support agent continuing a long conversation. The "
        "<case_facts> block is authoritative and complete for all transactional "
        "details. Never contradict it and never invent a figure that is not in it.",
        f"{VAGUE_SUMMARY}\n\n<case_facts>\n{CASE_FACTS}\n</case_facts>\n\n{PROBE}",
    )
    show("Answer", a2[:800])
    s2 = recall_score(a2)
    print(f"    facts recovered: {sum(s2.values())}/{len(s2)}  "
          f"{[k for k, v in s2.items() if v]}")
    print(f"    token cost: summary-only {usage_line(r1)}  |  with facts {usage_line(r2)}")
    note("The facts block costs a few hundred tokens per turn and is the reason the "
         "agent can quote $1,395.00 and the 48-hour commitment. Summarise the PROSE; "
         "never summarise the numbers.")

    # -- 2 -------------------------------------------------------------------
    section("2. Lost in the middle")
    findings = [f"FINDING-{i:02d}: module_{i} has an unhandled {name} on the "
                f"{place} path."
                for i, (name, place) in enumerate(
                    [("KeyError", "retry"), ("TypeError", "import"), ("race", "cache"),
                     ("leak", "socket"), ("overflow", "counter"), ("deadlock", "lock"),
                     ("IndexError", "batch"), ("ValueError", "parse"),
                     ("timeout", "fetch"), ("NPE", "callback"), ("regression", "sort"),
                     ("off-by-one", "window"), ("encoding", "export"),
                     ("rounding", "invoice"), ("collision", "hash"),
                     ("staleness", "replica"), ("truncation", "log"),
                     ("drift", "clock"), ("dup", "queue"), ("nil", "config")], 1)]
    blob = "\n".join(findings)

    bad("20 findings dumped in a flat list, question at the end")
    a3, _ = ask(c, "You are a triage assistant.",
                f"{blob}\n\nList the ID of every finding above. Just the IDs, comma separated.")
    got3 = set(re.findall(r"FINDING-(\d+)", a3))
    missing3 = sorted(set(f"{i:02d}" for i in range(1, 21)) - got3)
    print(f"    recovered {len(got3)}/20;  missing: {missing3 or 'none'}")
    if missing3 and any(8 <= int(m) <= 14 for m in missing3):
        note("The omissions cluster in the middle — the positional effect, live.")

    good("Key-findings summary FIRST, explicit section headers")
    structured = (
        "## SUMMARY (read this first)\n"
        f"20 findings, FINDING-01 through FINDING-20. Categories: exceptions (01,02,07,08,10), "
        "concurrency (03,06,16,18), resources (04,05,09), correctness (11,12,14,15,19,20), "
        "data handling (13,17).\n\n"
        + "\n".join(f"### {f.split(':')[0]}\n{f.split(': ',1)[1]}" for f in findings)
    )
    a4, _ = ask(c, "You are a triage assistant.",
                f"{structured}\n\nList the ID of every finding above. Just the IDs, comma separated.")
    got4 = set(re.findall(r"FINDING-(\d+)", a4))
    missing4 = sorted(set(f"{i:02d}" for i in range(1, 21)) - got4)
    print(f"    recovered {len(got4)}/20;  missing: {missing4 or 'none'}")
    note("Two mitigations at once: the up-front summary means the full inventory "
         "appears in a high-attention position, and the headers give every item its "
         "own anchor instead of relying on position within a wall of text.")

    # -- 3 -------------------------------------------------------------------
    section("3. Trimming verbose tool output")
    fat = json.dumps(FAT_ORDER)
    thin = json.dumps({k: FAT_ORDER[k] for k in RETURN_RELEVANT})
    tf = c.messages.count_tokens(model=MODEL,
                                 messages=[{"role": "user", "content": fat}]).input_tokens
    tt = c.messages.count_tokens(model=MODEL,
                                 messages=[{"role": "user", "content": thin}]).input_tokens
    print(f"    full order record : {len(FAT_ORDER)} fields, {tf} tokens")
    print(f"    return-relevant   : {len(RETURN_RELEVANT)} fields, {tt} tokens")
    print(f"    saved per lookup  : {tf - tt} tokens  ({100 * (tf - tt) // tf}%)")
    print(f"    over 15 lookups   : ~{(tf - tt) * 15} tokens, and they stay in context")
    show("What the agent actually needs", thin)
    note("The pick station, pallet id and A/B bucket are never relevant to a return, "
         "but once they enter context they are re-sent on EVERY subsequent request for "
         "the rest of the conversation. Trim at the tool boundary — a PostToolUse hook "
         "is a natural place (see domain1_agentic/t1_5_hooks.py).")

    section("Passing context BETWEEN agents")
    print(
        "  The same discipline applies at every handoff:\n\n"
        "    * Require subagents to include METADATA (dates, source locations,\n"
        "      methodological context) in structured output, so the synthesis step has\n"
        "      something to reason with.\n"
        "    * When a downstream agent has a small context budget, change the UPSTREAM\n"
        "      agent to return structured data — key facts, citations, relevance scores\n"
        "      — rather than verbose content and reasoning chains. Fix it at the\n"
        "      producer, not by truncating at the consumer.\n\n"
        "  Truncating at the consumer throws away an arbitrary slice. Restructuring at\n"
        "  the producer throws away the part that was never needed."
    )

    takeaway(
        "Summarise prose; NEVER summarise numbers, dates, or stated commitments.",
        "Keep a persistent structured case-facts block OUTSIDE the summarised history.",
        "Lost-in-the-middle: put a summary FIRST and give every section a header.",
        "Trim tool output at the boundary — unneeded fields persist for the whole session.",
        "Fix context bloat at the PRODUCING agent, not by truncating at the consumer.",
    )


if __name__ == "__main__":
    main()
