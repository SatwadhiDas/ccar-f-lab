"""
Task 5.2 — Escalation and ambiguity resolution patterns.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain5_context/t5_2_escalation.py

THIS IS SAMPLE QUESTION 3
-------------------------
"Your agent achieves 55% first-contact resolution, well below the 80% target.
Logs show it escalates straightforward cases (standard damage replacements with
photo evidence) while attempting to autonomously handle complex situations
requiring policy exceptions."

  A. Explicit escalation criteria in the system prompt + few-shot examples.  <-- correct
  B. Self-reported confidence score, route below a threshold.
  C. A separate classifier model trained on historical tickets.
  D. Sentiment analysis, escalate on negative sentiment.

Why each distractor fails, in the exam's own terms:

  B  LLM self-reported confidence is POORLY CALIBRATED. Re-read the premise: the
     agent is ALREADY confidently wrong on the hard cases. Asking it to score its
     own confidence samples the same broken judgment twice.
  C  Over-engineered. It needs labelled data and ML infrastructure, and prompt
     optimisation has not been tried yet. Note the exam's consistent preference
     for the proportionate first response.
  D  Solves a DIFFERENT problem. Sentiment measures how upset someone is;
     complexity is about whether the case has a policy answer. A calm customer
     can present an impossible case and a furious one a trivial one.

THE THREE LEGITIMATE ESCALATION TRIGGERS
----------------------------------------
  1. The customer explicitly asks for a human.
  2. Policy is silent, ambiguous, or the request needs an exception.
  3. The agent cannot make meaningful progress.

Note what is NOT on that list: "the case is complex", "the customer is angry",
"confidence is low".

TWO REFINEMENTS THE EXAM ALSO TESTS
-----------------------------------
  * An explicit request for a human is honoured IMMEDIATELY — you do not
    investigate first and then escalate. But mere frustration is different:
    acknowledge it, offer to resolve if the issue is within your capability, and
    escalate only if they reiterate the preference.
  * Multiple customer matches require ASKING for another identifier, never
    picking one heuristically ("the most recent", "the one with orders").
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of

WEAK_SYSTEM = """\
You are a customer support agent. Resolve customer issues where you can, and
escalate to a human agent when a case is too complex for you to handle.
"""

STRONG_SYSTEM = """\
You are a customer support agent. Target: resolve 80%+ of contacts yourself.

ESCALATE only when one of these is true:
  1. The customer explicitly asks for a human, supervisor, or manager.
  2. Policy is silent or ambiguous on their specific request, or the resolution
     requires an exception to stated policy.
  3. You cannot make meaningful progress — a required tool keeps failing, or the
     information you need does not exist in any system you can reach.

RESOLVE otherwise. Specifically, DO NOT escalate merely because:
  - the case involves several issues at once (decompose and handle each),
  - the customer is angry (frustration is not complexity),
  - the amount is large but the policy is clear,
  - you feel uncertain but policy actually covers the situation.

WHEN THE CUSTOMER IS FRUSTRATED but the issue is within your capability:
acknowledge the frustration, state what you can do right now, and do it. Escalate
only if they then repeat that they want a person.

WHEN THEY EXPLICITLY ASK FOR A HUMAN: escalate immediately. Do not investigate
first, do not attempt a resolution first, do not ask them to explain again.

WHEN A LOOKUP RETURNS MULTIPLE MATCHES: ask for an additional identifier (order
number, postcode, last four of the card). Never choose among matches by heuristic.

EXAMPLES

Customer: "My chair arrived cracked, here's a photo, I want a replacement."
-> RESOLVE. Standard damage replacement with evidence. Policy is explicit. Issue
   the replacement. Escalating this is the exact failure we are fixing.

Customer: "Your competitor has it $200 cheaper, match it or I'm cancelling."
-> ESCALATE (trigger 2). Policy covers price adjustments on OUR OWN site only and
   is silent on competitor matching. This is a policy gap, not a hard case.

Customer: "This is the fourth time I've called about this. Get me a manager."
-> ESCALATE (trigger 1). Immediately. Do not investigate first.

Customer: "I'm furious, this has been a disaster. My refund never arrived."
-> RESOLVE. Angry, but a missing refund on a returned item is squarely within
   policy. Acknowledge, then process it. Escalate only if they ask for a person.

Customer: "I want to return it, it's been 45 days, policy says 30."
-> ESCALATE (trigger 2). Requires an exception to stated policy.

Output your decision on the first line as exactly:
DECISION: RESOLVE
or
DECISION: ESCALATE — trigger <1|2|3>
Then your reply to the customer.
"""

CASES = [
    ("standard damage + photo",
     "My chair arrived with a cracked base. I've attached a photo. I'd like a "
     "replacement please.", "RESOLVE"),
    ("competitor price match (policy gap)",
     "I found this exact chair $200 cheaper at a competitor. Match it or I'm "
     "cancelling my order.", "ESCALATE"),
    ("explicit request for a human",
     "This is the fourth time I've called about this. I want to speak to a manager.",
     "ESCALATE"),
    ("angry but in-policy",
     "I am absolutely furious. This has been a complete disaster from start to "
     "finish. My refund still hasn't arrived and I returned the item three weeks ago.",
     "RESOLVE"),
    ("past the return window (needs exception)",
     "I'd like to return this. I know it's been 45 days and the policy says 30, "
     "but I was in hospital.", "ESCALATE"),
    ("multi-issue but each in-policy",
     "Three things: my refund is late, I was charged twice for shipping, and I want "
     "to update the email on my account.", "RESOLVE"),
    ("large amount, clear policy",
     "I need to return an $8,400 conference table. Unopened, delivered six days ago.",
     "RESOLVE"),
]


def decide(c, system, message):
    r = c.messages.create(model=MODEL, max_tokens=3000, system=system,
                          messages=[{"role": "user", "content": message}])
    text = text_of(r)
    first = next((l for l in text.splitlines() if "DECISION" in l.upper()), "")
    if "ESCALATE" in first.upper() or (not first and "escalat" in text.lower()[:300]):
        return "ESCALATE", text
    if "RESOLVE" in first.upper():
        return "RESOLVE", text
    return ("ESCALATE" if "escalat" in text.lower() else "RESOLVE"), text


def run_suite(c, system, label):
    print(f"\n  {label}")
    correct = 0
    for name, msg, expected in CASES:
        got, _ = decide(c, system, msg)
        ok = got == expected
        correct += ok
        print(f"    [{'OK ' if ok else 'BAD'}] {name:36s} -> {got:8s} (want {expected})")
    rate = correct / len(CASES)
    print(f"    correct: {correct}/{len(CASES)}  ({rate:.0%})")
    return correct


def main():
    c = client()
    banner("Escalation calibration", "Task 5.2 — this is exam Sample Question 3")

    bad("Prompt A — 'escalate when a case is too complex for you'")
    n1 = run_suite(c, WEAK_SYSTEM, "vague criterion")
    note("'Too complex' has no definition, so the model substitutes its own — and its "
         "sense of difficulty does not match your policy boundary. That mismatch is "
         "precisely the 55%-resolution failure in the exam's premise.")

    good("Prompt B — explicit triggers + explicit non-triggers + few-shot")
    n2 = run_suite(c, STRONG_SYSTEM, "explicit criteria with examples")

    section("Result")
    print(f"    vague criterion:   {n1}/{len(CASES)}")
    print(f"    explicit criteria: {n2}/{len(CASES)}")
    print(
        "\n  Look at WHICH cases move. The valuable change is 'angry but in-policy' and\n"
        "  'large amount, clear policy' flipping to RESOLVE, while 'competitor price\n"
        "  match' and 'past the return window' stay ESCALATE. That is calibration —\n"
        "  not escalating less, but escalating on the right axis."
    )

    # -- Multiple matches ----------------------------------------------------
    section("Ambiguity resolution: multiple customer matches")
    multi = json.dumps({
        "matches": [
            {"customer_id": "CUST-4417", "name": "Dana Whitfield",
             "email": "d***a@example.com", "orders": 12, "last_order": "2025-08-02"},
            {"customer_id": "CUST-9002", "name": "Dana Whitfield",
             "email": "d***d@example.com", "orders": 3, "last_order": "2025-07-11"},
        ],
        "match_count": 2,
    })
    tool = [{
        "name": "get_customer",
        "description": ("Look up a customer by name or email. If several accounts "
                        "match, returns them all with match_count > 1."),
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}},
                         "required": ["name"]},
    }]
    messages = [{"role": "user", "content":
                 "Hi, this is Dana Whitfield. Can you refund my last order?"}]
    r = c.messages.create(model=MODEL, max_tokens=3000, system=STRONG_SYSTEM,
                          tools=tool, tool_choice={"type": "any"}, messages=messages)
    call = next(b for b in r.content if b.type == "tool_use")
    messages += [
        {"role": "assistant", "content": r.content},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.id,
                                      "content": multi}]},
    ]
    r2 = c.messages.create(model=MODEL, max_tokens=3000, system=STRONG_SYSTEM,
                           tools=tool, messages=messages)
    reply = text_of(r2)
    acted = [b.name for b in r2.content if b.type == "tool_use"]
    show("Agent's response to an ambiguous match", reply[:600])
    asked = any(w in reply.lower() for w in
                ["order number", "postcode", "zip", "last four", "confirm", "which",
                 "additional", "identifier", "email address"])
    print(f"    asked for another identifier: {'YES' if asked else 'NO'}")
    print(f"    acted on a guessed match:     {'YES' if acted else 'NO'}")
    if asked and not acted:
        note("Correct. Picking 'the one with 12 orders' or 'the most recent' would "
             "refund a stranger's order. Heuristic selection among identity matches is "
             "never acceptable — ask.")

    section("Why the distractors fail")
    print(
        "  B  self-reported confidence\n"
        "     The premise says the agent is CONFIDENTLY handling cases it should\n"
        "     escalate. A confidence score is that same broken judgment, sampled\n"
        "     again. LLM confidence is poorly calibrated; it is useful for routing\n"
        "     reviewer attention (t4_6), not for gating autonomy.\n\n"
        "  C  separate trained classifier\n"
        "     Needs labelled data, training, serving, monitoring — before anyone has\n"
        "     tried writing down the escalation criteria. The exam consistently rewards\n"
        "     the proportionate first response.\n\n"
        "  D  sentiment analysis\n"
        "     Measures the wrong variable. See the 'angry but in-policy' case above:\n"
        "     maximum frustration, entirely resolvable. And the price-match case is\n"
        "     calm and genuinely needs a human. Sentiment and complexity are\n"
        "     uncorrelated."
    )

    takeaway(
        "Triggers: explicit human request, policy gap/exception, no meaningful progress.",
        "NOT triggers: complexity, anger, large amounts, the agent 'feeling' unsure.",
        "Explicit request for a human -> escalate IMMEDIATELY, no investigation first.",
        "Frustration -> acknowledge and resolve; escalate only if they reiterate.",
        "Multiple identity matches -> ask for another identifier. Never guess.",
        "Self-reported confidence is poorly calibrated. Never gate escalation on it.",
        "Sentiment measures upset, not complexity. Different variable entirely.",
    )


if __name__ == "__main__":
    main()
