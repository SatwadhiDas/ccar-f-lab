"""
Task 4.5 — Design efficient batch processing strategies.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain4_prompting/t4_5_batch_processing.py
       python domain4_prompting/t4_5_batch_processing.py --no-submit   (facts only)

THE FACTS THE EXAM TESTS
------------------------
  * 50% cost saving on all token usage.
  * Up to a 24-hour processing window. NO guaranteed latency SLA. Most batches
    finish in under an hour — "usually fast" is not a guarantee you can design a
    blocking workflow around.
  * custom_id correlates request to response. Results come back in ARBITRARY
    ORDER, so you key by custom_id and never by position.
  * The batch API does NOT support multi-turn tool calling within a request. You
    cannot execute a tool mid-request and feed the result back. Agentic loops are
    therefore not batchable — batch the single-shot steps only.

SAMPLE QUESTION 11
------------------
Two workflows: (1) a blocking pre-merge check developers wait on, (2) an
overnight technical-debt report. Manager proposes moving both to batch for the
50% saving.

  A. Batch the reports only; keep real-time for the pre-merge check.  <-- correct
  B. Batch both, poll for completion.
  C. Keep real-time for both (fear of ordering issues).
  D. Batch both with a timeout fallback to real-time.

B fails because polling does not change the SLA — you are still hostage to a
24-hour window while a developer waits. C is a misconception: ordering is a
solved problem via custom_id. D adds a fallback path, duplicate spend, and two
code paths to maintain, to avoid simply matching each API to its workload.

The decision rule is one question: IS ANYONE WAITING ON THIS?
    blocking / interactive  -> synchronous API
    latency-tolerant        -> batch API

SLA ARITHMETIC — worth practising, it shows up as a calculation item
--------------------------------------------------------------------
Committed end-to-end SLA of 30 hours, with a worst case of 24 hours inside the
batch window, leaves 6 hours of slack. Submitting every 4 hours means a document
arriving just after a submission waits at most 4h before it is picked up, then at
most 24h to process: 28h worst case, inside 30h with 2h spare. Submit every 8h
and the worst case is 32h — you have blown the SLA on paper before you start.
"""

import sys
import os
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway

DOCS = {
    "doc-001": "Invoice NW-1001, vendor Northwind, total USD 420.00, dated 2025-01-04.",
    "doc-002": "Invoice AC-7781, vendor Acme Parts, total USD 1,204.55, dated 2025-02-11.",
    "doc-003": "Receipt from Blue Bottle, $18.40, 2025-03-02, card ending 4417.",
    "doc-004": "Invoice ZZ-0001 — TOTAL ILLEGIBLE — water damage, vendor unreadable.",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": ["string", "null"]},
        "total_usd": {"type": ["number", "null"]},
        "doc_type": {"type": "string", "enum": ["invoice", "receipt", "unclear", "other"]},
    },
    "required": ["vendor", "total_usd", "doc_type"],
}


def build_requests():
    """
    Build the batch. Note the imports — the batch request params are typed.

    custom_id is YOUR correlation key. Make it something you can join back to your
    own records (a document id, a row primary key), not an array index — because
    results do not come back in submission order and a resubmission of failures
    will not preserve positions either.
    """
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    tool = {"name": "extract", "description": "Extract document fields.",
            "input_schema": SCHEMA}

    return [
        Request(
            custom_id=doc_id,
            params=MessageCreateParamsNonStreaming(
                model=MODEL,
                max_tokens=1024,
                tools=[tool],
                tool_choice={"type": "tool", "name": "extract"},
                messages=[{"role": "user", "content": text}],
            ),
        )
        for doc_id, text in DOCS.items()
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-submit", action="store_true",
                    help="skip the live batch submission")
    ap.add_argument("--wait", type=int, default=600,
                    help="seconds to poll before giving up (default 600)")
    args = ap.parse_args()

    c = client()
    banner("Message Batches API", "Task 4.5 — this is exam Sample Question 11")

    # -- Decision rule -------------------------------------------------------
    section("Matching the API to the workload")
    workloads = [
        ("pre-merge CI check (developer is waiting)", "blocking", "synchronous"),
        ("overnight technical-debt report", "latency-tolerant", "batch"),
        ("nightly test generation", "latency-tolerant", "batch"),
        ("weekly compliance audit over 40k docs", "latency-tolerant", "batch"),
        ("live support agent turn", "blocking", "synchronous"),
        ("agentic loop with tool calls", "n/a", "synchronous (batch cannot do it)"),
    ]
    for name, kind, api in workloads:
        print(f"    {name:44s} {kind:16s} -> {api}")
    note("The last row is a capability limit, not a latency judgement: the batch API "
         "does not support multi-turn tool calling inside a request, so no agentic "
         "loop can be batched however tolerant of latency it is.")

    # -- SLA arithmetic ------------------------------------------------------
    section("SLA arithmetic")
    for cadence in (2, 4, 8, 12):
        worst = cadence + 24
        verdict = "OK" if worst <= 30 else "BREACH"
        print(f"    submit every {cadence:2d}h -> worst case {worst:2d}h vs 30h SLA   [{verdict}]")
    note("Worst case = submission cadence + the 24h batch ceiling. Design against the "
         "ceiling, not against the typical completion time.")

    if args.no_submit:
        print("\n  --no-submit given; skipping the live batch.")
        return

    # -- Live batch ----------------------------------------------------------
    section("Submitting a live batch")
    batch = c.messages.batches.create(requests=build_requests())
    print(f"  batch id: {batch.id}")
    print(f"  status:   {batch.processing_status}")
    print(f"  submitted {len(DOCS)} requests at 50% of standard token cost")

    deadline = time.time() + args.wait
    while time.time() < deadline:
        batch = c.messages.batches.retrieve(batch.id)
        counts = batch.request_counts
        print(f"  [{int(time.time() - (deadline - args.wait)):4d}s] {batch.processing_status:12s} "
              f"processing={counts.processing} succeeded={counts.succeeded} "
              f"errored={counts.errored}")
        if batch.processing_status == "ended":
            break
        time.sleep(15)

    if batch.processing_status != "ended":
        note(f"Still running after {args.wait}s. That is NOT a failure — it is the "
             "point of the exercise. There is no latency guarantee, which is exactly "
             "why a developer-blocking pre-merge check cannot live here. Re-run later "
             "with the batch id, or raise --wait.")
        return

    # -- Results -------------------------------------------------------------
    section("Correlating results by custom_id")
    results, failures = {}, []
    order_seen = []
    for result in c.messages.batches.results(batch.id):
        order_seen.append(result.custom_id)
        kind = result.result.type
        if kind == "succeeded":
            msg = result.result.message
            calls = [b for b in msg.content if b.type == "tool_use"]
            results[result.custom_id] = calls[0].input if calls else None
        else:
            failures.append((result.custom_id, kind,
                             getattr(getattr(result.result, "error", None), "type", "")))

    print(f"  submission order: {list(DOCS)}")
    print(f"  result order:     {order_seen}")
    if order_seen != list(DOCS):
        note("Different order. This is why custom_id exists and why indexing by "
             "position is a data-corruption bug waiting to happen.")
    else:
        note("Same order this run — which proves nothing. Order is not guaranteed; "
             "key by custom_id regardless.")

    print()
    for doc_id in DOCS:
        payload = results.get(doc_id)
        print(f"    {doc_id}: {json.dumps(payload) if payload else '(no result)'}")

    if failures:
        section("Handling failures")
        for cid, kind, err in failures:
            print(f"    {cid}: {kind} {err}")
        print(
            "\n  Resubmit ONLY the failed custom_ids, with a modification that addresses\n"
            "  the cause — chunk a document that exceeded the context limit, fix a\n"
            "  malformed request, drop an unreadable scan to human review. Resubmitting\n"
            "  the whole batch pays full price again for the requests that succeeded."
        )

    print(
        "\n  One more strategy the exam names: refine the prompt on a SAMPLE first.\n"
        "  A 40,000-document batch that comes back 30% malformed costs a full\n"
        "  resubmission cycle and a day of wall clock. Run 50 documents synchronously,\n"
        "  fix the prompt against the failures, then batch the rest — first-pass\n"
        "  success rate is the number that dominates total batch cost."
    )

    takeaway(
        "50% cheaper, up to 24h, NO latency SLA. Design against the 24h ceiling.",
        "Blocking/interactive -> synchronous. Latency-tolerant -> batch. That's the rule.",
        "Polling does not change the SLA (distractor B). custom_id solves ordering (C).",
        "Batch cannot do multi-turn tool calling — agentic loops are not batchable.",
        "Key results by custom_id; never by position.",
        "Resubmit only failed custom_ids, with a fix. Refine the prompt on a sample first.",
    )


if __name__ == "__main__":
    main()
