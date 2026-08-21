"""
Task 5.5 — Human review workflows and confidence calibration.

Needs: ANTHROPIC_API_KEY (raw Claude API) for the live extraction section.
       The statistics section runs offline.
Run:   python domain5_context/t5_5_human_review.py
       python domain5_context/t5_5_human_review.py --offline

THE HEADLINE RISK
-----------------
An aggregate accuracy figure hides segment failures. "97% accurate" can mean:

    invoices    99.2%  (n=8,400)
    receipts    98.8%  (n=1,900)
    handwritten 61.0%  (n=310)      <-- this is in the 97%
                       ------
    overall     97.0%

Automate on the 97% and you have automated a 61% process for handwritten
documents, and nobody finds out until an auditor does. The exam's requirement is
to validate accuracy BY DOCUMENT TYPE AND BY FIELD before reducing human review.

THE FOUR TECHNIQUES
-------------------
1. Segment accuracy by document type AND by field before automating anything.
2. Field-level confidence scores from the model, with thresholds CALIBRATED on a
   labelled validation set — not chosen by intuition.
3. Stratified random sampling of HIGH-confidence extractions, ongoing. This is
   the only way to detect a novel error pattern in the population you stopped
   looking at. Sampling only the low-confidence ones tells you nothing about the
   ones you are auto-approving.
4. Route to human review on low model confidence OR on ambiguous/contradictory
   source documents — the second trigger is independent of the model's confidence
   and catches cases where the model is confidently reading a bad document.

WHY STRATIFIED AND NOT SIMPLE RANDOM
------------------------------------
Simple random sampling of a population that is 96% clean invoices spends 96% of
your reviewer budget confirming what you already know. Stratified sampling forces
coverage of the small segments — which are exactly where the unknown failures
live, and are statistically invisible to a simple random sample.
"""

import sys
import os
import json
import random
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway

random.seed(7)  # deterministic so the numbers below are reproducible

# ---------------------------------------------------------------------------
# A simulated labelled validation set: 10,610 extractions with known ground truth.
# ---------------------------------------------------------------------------
SEGMENTS = {
    # doc_type:      (count, per-field accuracy)
    "invoice_typed":   (8400, {"vendor": 0.995, "total": 0.994, "date": 0.991, "po_number": 0.962}),
    "receipt_thermal": (1900, {"vendor": 0.988, "total": 0.985, "date": 0.972, "po_number": 0.410}),
    "handwritten":     (310,  {"vendor": 0.640, "total": 0.588, "date": 0.615, "po_number": 0.220}),
}


def build_population():
    pop = []
    for doc_type, (count, field_acc) in SEGMENTS.items():
        for i in range(count):
            rec = {"id": f"{doc_type}-{i:05d}", "doc_type": doc_type, "fields": {}}
            for field, acc in field_acc.items():
                correct = random.random() < acc
                # Confidence is correlated with correctness but MISCALIBRATED —
                # deliberately so. Errors still frequently arrive with high scores,
                # which is the property that makes technique 3 necessary.
                conf = random.uniform(0.86, 0.99) if correct else random.uniform(0.55, 0.97)
                rec["fields"][field] = {"correct": correct, "confidence": round(conf, 3)}
            pop.append(rec)
    random.shuffle(pop)
    return pop


def overall_accuracy(pop, doc_type=None, field=None):
    hits = total = 0
    for r in pop:
        if doc_type and r["doc_type"] != doc_type:
            continue
        for f, v in r["fields"].items():
            if field and f != field:
                continue
            total += 1
            hits += v["correct"]
    return hits / total if total else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="skip the live extraction")
    args = ap.parse_args()

    banner("Human review and confidence calibration", "Task 5.5")
    pop = build_population()
    print(f"  labelled validation set: {len(pop)} extractions, "
          f"{len(pop) * 4} field values")

    # -- 1. Aggregate hides segments ----------------------------------------
    section("1. The aggregate number hides the failure")
    bad("Reporting one overall accuracy figure")
    print(f"    overall accuracy: {overall_accuracy(pop):.1%}")
    note("On this number you would automate. Now segment it.")

    good("Segmented by document type AND field")
    fields = ["vendor", "total", "date", "po_number"]
    print(f"\n    {'doc_type':18s} {'n':>6s}  " + "  ".join(f"{f:>10s}" for f in fields))
    for doc_type in SEGMENTS:
        n = SEGMENTS[doc_type][0]
        cells = "  ".join(f"{overall_accuracy(pop, doc_type, f):>9.1%}" for f in fields)
        print(f"    {doc_type:18s} {n:6d}  {cells}")
    print(f"\n    {'ALL':18s} {len(pop):6d}  " +
          "  ".join(f"{overall_accuracy(pop, None, f):>9.1%}" for f in fields))

    worst = min(
        ((dt, f, overall_accuracy(pop, dt, f)) for dt in SEGMENTS for f in fields),
        key=lambda x: x[2],
    )
    note(f"Worst cell: {worst[0]} / {worst[1]} at {worst[2]:.1%}. It is 2.9% of the "
         "population, so it moves the aggregate by almost nothing — and it is the only "
         "part of this table that should stop you automating.")
    po_typed = overall_accuracy(pop, "invoice_typed", "po_number")
    print(
        f"\n    Two separate axes matter. po_number is weak even on typed invoices\n"
        f"    ({po_typed:.1%}) because it is often genuinely absent; handwritten is weak\n"
        "    across EVERY field. A per-type average would hide the first, a per-field\n"
        "    average would hide the second. You need the grid, not either margin."
    )

    # -- 2. Calibration ------------------------------------------------------
    section("2. Calibrating a confidence threshold on the labelled set")
    print(f"    {'threshold':>10s} {'auto-approved':>14s} {'error rate in auto':>20s} "
          f"{'sent to human':>14s}")
    rows = []
    for thr in [0.70, 0.80, 0.85, 0.90, 0.95]:
        auto = [(r, f, v) for r in pop for f, v in r["fields"].items()
                if v["confidence"] >= thr]
        errs = sum(1 for _, _, v in auto if not v["correct"])
        total_fields = len(pop) * len(fields)
        rate = errs / len(auto) if auto else 0
        rows.append((thr, len(auto), rate, total_fields - len(auto)))
        print(f"    {thr:>10.2f} {len(auto):>14d} {rate:>19.2%} "
              f"{total_fields - len(auto):>14d}")
    note("This table is what 'calibrated on a labelled validation set' means. Pick a "
         "threshold by intuition and you are choosing an error rate blind — the "
         "relationship between a confidence number and an actual error rate is not "
         "something you can guess, and it differs per model, per prompt, per segment.")

    target = 0.02
    ok = [r for r in rows if r[2] <= target]
    if ok:
        chosen = min(ok, key=lambda r: r[0])
        print(f"\n    For a 2% error budget in the auto-approved set: threshold "
              f"{chosen[0]:.2f}, auto-approving {chosen[1]} values "
              f"({chosen[1] / (len(pop) * len(fields)):.0%}).")
    else:
        note(f"No threshold reaches a {target:.0%} error rate — the honest conclusion "
             "is that this extractor is not ready for confidence-gated automation on "
             "this population, regardless of its 97% headline.")

    # -- 3. Stratified sampling ---------------------------------------------
    section("3. Stratified sampling of HIGH-confidence extractions")
    high = [r for r in pop if all(v["confidence"] >= 0.90 for v in r["fields"].values())]
    print(f"    high-confidence population: {len(high)} documents")

    budget = 150
    bad("Simple random sample")
    simple = random.sample(high, min(budget, len(high)))
    by_type = defaultdict(int)
    for r in simple:
        by_type[r["doc_type"]] += 1
    print(f"    {budget} reviews -> {dict(by_type)}")
    hw = by_type.get("handwritten", 0)
    note(f"Only {hw} handwritten documents reviewed. The segment that is actually "
         "failing is ~3% of the population, so a simple random sample barely touches "
         "it — you would need thousands of reviews to see its error rate.")

    good("Stratified sample — proportional floor per segment")
    per_segment = budget // len(SEGMENTS)
    strat = []
    for doc_type in SEGMENTS:
        pool = [r for r in high if r["doc_type"] == doc_type]
        strat += random.sample(pool, min(per_segment, len(pool)))
    by_type_s = defaultdict(int)
    for r in strat:
        by_type_s[r["doc_type"]] += 1
    print(f"    {len(strat)} reviews -> {dict(by_type_s)}")

    for label, sample in [("simple", simple), ("stratified", strat)]:
        errs = defaultdict(lambda: [0, 0])
        for r in sample:
            for f, v in r["fields"].items():
                errs[r["doc_type"]][1] += 1
                errs[r["doc_type"]][0] += (not v["correct"])
        print(f"\n    measured error rate in HIGH-confidence set ({label}):")
        for dt in SEGMENTS:
            e, n = errs[dt]
            print(f"      {dt:18s} {e}/{n}" + (f"  = {e/n:.1%}" if n else "  (no data)"))
    note("The stratified sample produces a usable error estimate for every segment, "
         "including the small one. That is the point: you are sampling the population "
         "you STOPPED reviewing, specifically to catch error patterns you have not "
         "seen yet. Sampling only low-confidence items measures nothing about it.")

    # -- 4. Second routing trigger ------------------------------------------
    section("4. Routing on source ambiguity, independent of confidence")
    print(
        "  Two independent triggers send a document to a human:\n\n"
        "    a. low model confidence on a field\n"
        "    b. the SOURCE is ambiguous or self-contradictory — line items that do not\n"
        "       sum to the stated total, two different dates for the same event, an\n"
        "       illegible region overlapping a required field\n\n"
        "  (b) matters because the model can be entirely confident while reading a\n"
        "  document that is itself wrong. Confidence measures the model's certainty\n"
        "  about what the document SAYS, not whether what it says is coherent. The\n"
        "  conflict_detected flag from t4_3 is exactly this trigger, and it fires\n"
        "  regardless of how confident the extraction was."
    )

    # -- 5. Live ------------------------------------------------------------
    if not args.offline:
        section("5. Live: field-level confidence from a real extraction")
        try:
            c = client()
            tool = {
                "name": "extract",
                "description": "Extract invoice fields with per-field confidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        f: {"type": "object",
                            "properties": {
                                "value": {"type": ["string", "number", "null"]},
                                "confidence": {"type": "number",
                                               "description": "0.0-1.0, your certainty "
                                                              "about THIS field only"},
                                "source_ambiguous": {
                                    "type": "boolean",
                                    "description": "True if the document itself is "
                                                   "unclear or self-contradictory here, "
                                                   "independent of your confidence."},
                            },
                            "required": ["value", "confidence", "source_ambiguous"]}
                        for f in ["vendor", "total_usd", "invoice_date", "po_number"]
                    },
                    "required": ["vendor", "total_usd", "invoice_date", "po_number"],
                },
            }
            doc = ("NORTHW--D SUP??Y CO   inv NW-2291-B   dated 3rd Sept 2025 (or "
                   "possibly 5th, the scan is smudged)\n  chair 1,200.00 + delivery "
                   "340.00 + warranty 95.00   TOTAL USD 1,735.00")
            r = c.messages.create(
                model=MODEL, max_tokens=4000, tools=[tool],
                tool_choice={"type": "tool", "name": "extract"},
                system="Extract the fields. Be honest in your confidence scores.",
                messages=[{"role": "user", "content": doc}])
            payload = next(b.input for b in r.content if b.type == "tool_use")
            show("Per-field extraction", json.dumps(payload, indent=2))
            for f, v in payload.items():
                route = ("HUMAN (low confidence)" if v["confidence"] < 0.85
                         else "HUMAN (ambiguous source)" if v.get("source_ambiguous")
                         else "auto-approve")
                print(f"    {f:16s} conf={v['confidence']:.2f}  "
                      f"ambiguous={str(v.get('source_ambiguous')):5s} -> {route}")
            note("Note any field that is HIGH confidence but flagged ambiguous — the "
                 "date, given the smudge. A confidence-only gate would auto-approve it.")
        except SystemExit:
            note("Skipped: no API key. The statistics above ran offline.")
        except Exception as exc:
            note(f"Skipped: {type(exc).__name__}: {str(exc)[:160]}")

    takeaway(
        "Aggregate accuracy hides segment failure. Validate by doc type AND by field.",
        "A small bad segment barely moves the aggregate and is the reason not to automate.",
        "Calibrate confidence thresholds on a LABELLED set; intuition picks blind.",
        "Stratify the sample — simple random spends the budget on the majority segment.",
        "Sample the HIGH-confidence set you stopped reviewing; that's where novel errors hide.",
        "Route on low confidence OR ambiguous source. The second is independent of the first.",
    )


if __name__ == "__main__":
    main()
