"""
Task 4.1 — Explicit criteria to improve precision and reduce false positives.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain4_prompting/t4_1_explicit_criteria.py

THE CLAIM
---------
Vague confidence instructions do not improve precision. Specific CATEGORICAL
criteria do.

  Does not work: "be conservative", "only report high-confidence findings",
                 "don't nitpick", "use your judgment"
  Works:         "flag a comment ONLY when the claimed behaviour contradicts the
                 actual code behaviour"

Why: "high-confidence" is a property of the model's internal state, and the model
is not well calibrated about it — it is often confident about exactly the things
it gets wrong. "Contradicts the actual code behaviour" is a property of the CODE,
which is checkable. You are moving the decision from introspection to observation.

WHY FALSE POSITIVES MATTER MORE THAN THEY LOOK
----------------------------------------------
A high false-positive CATEGORY poisons the categories around it. Once developers
learn that the "possible race condition" findings are usually noise, they start
skimming past every finding, including the accurate security ones. Trust is not
tracked per category by the humans consuming it.

Hence the exam's blunt remediation: temporarily DISABLE a high-false-positive
category entirely while you fix its prompt. Shipping a category at 60% precision
is worse than not shipping it, because it is spending trust the accurate
categories need.

This script reviews one file under three prompts and counts real findings against
noise findings.
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of

# ---------------------------------------------------------------------------
# One file: 3 genuine defects, plus 5 patterns that are deliberate and correct
# here. A reviewer without explicit criteria reliably flags the deliberate ones.
# ---------------------------------------------------------------------------
CODE = '''\
"""Nightly reconciliation job. Runs unattended from cron; see ops/RUNBOOK.md."""
import time, logging

log = logging.getLogger(__name__)

# Deliberate #1: bare-ish except. This is a nightly batch job — one bad row must
# not abort the run. The exception IS logged and the row IS recorded for replay.
def reconcile_all(rows, ledger):
    failures = []
    for r in rows:
        try:
            reconcile_one(r, ledger)
        except Exception:
            log.exception("row failed, queued for replay: %s", r["id"])
            failures.append(r["id"])
    return failures


def reconcile_one(row, ledger):
    # REAL BUG #1: float arithmetic on currency. 0.1 + 0.2 != 0.3, and this
    # compounds across a 40k-row nightly run.
    expected = float(row["amount_dollars"]) * 1.0725
    actual = ledger.get(row["id"], 0.0)

    # REAL BUG #2: comparing floats with ==. Will spuriously report mismatches.
    if expected == actual:
        return "matched"

    # Deliberate #2: magic number 1.0725 is the CA tax rate, documented in the
    # RUNBOOK and intentionally not configurable for this legacy job.

    # REAL BUG #3: `or` binds looser than the author expects. Any row with
    # status "void" is treated as reconciled regardless of its age, so voided
    # rows from years ago silently pass.
    if row["age_days"] < 90 or row["status"] == "void":
        return "aged_out"

    return "mismatch"


# Deliberate #3: single-letter loop variables in a tight numeric loop. Idiomatic
# here and consistent with the rest of the module.
def checksum(vals):
    t = 0
    for i, v in enumerate(vals):
        t += (i + 1) * v
    return t % 9973


# Deliberate #4: no type hints on a private helper. The module convention is
# hints on public functions only; see standards/python.md.
def _fmt(x):
    return f"{x:,.2f}"


# Deliberate #5: time.sleep in a retry. This is a batch job with no latency SLA,
# and the gateway explicitly asks for a 2s pause between retries.
def push_with_retry(client, payload, attempts=3):
    for n in range(attempts):
        if client.push(payload):
            return True
        time.sleep(2)
    return False
'''

REAL = {
    "float currency": ["float", "currency", "decimal", "amount_dollars", "monetary"],
    "float equality": ["==", "equality", "compar", "isclose", "epsilon"],
    "or precedence": ["or ", "precedence", "short-circuit", "void", "age_days"],
}
NOISE_MARKERS = {
    "bare except": ["bare except", "except exception", "broad except", "catching exception"],
    "magic number": ["magic number", "hardcoded", "1.0725", "hard-coded", "constant"],
    "single letter": ["single-letter", "single letter", "variable name", "descriptive name",
                      "rename", "naming"],
    "missing hints": ["type hint", "type annotation", "typing"],
    "sleep": ["sleep", "blocking call", "time.sleep"],
}

# ---------------------------------------------------------------------------
PROMPT_VAGUE = """\
You are a code reviewer. Review the file and report issues.

Be conservative. Only report high-confidence findings. Don't nitpick. Use your
judgment about what matters.

Output one line per finding: FINDING | <short description>
"""

PROMPT_EXPLICIT = """\
You are a code reviewer.

REPORT a finding only if it falls in one of these categories:

  MONEY      Currency represented as a float, or arithmetic/comparison on
             currency that can lose or misreport value. Includes float equality
             comparison on any computed numeric value.
  LOGIC      A boolean expression, boundary, or control-flow construct whose
             evaluated behaviour differs from what the surrounding code or
             comments state it should be. Includes operator-precedence errors and
             off-by-one errors.
  SECURITY   Injection, missing authorization, or secret exposure.

DO NOT REPORT, even if you would normally:
  - Exception handling breadth in a batch/cron job that logs and records the
    failure. That is deliberate isolation, not swallowing.
  - Hardcoded constants that a comment or referenced document explains.
  - Variable naming, including single-letter loop variables.
  - Missing type hints or docstrings.
  - Blocking calls (sleep, synchronous I/O) in a job with no latency requirement.
  - Anything consistent with the surrounding file's established conventions.

For each finding output exactly:
FINDING | <category> | <what the code does> | <what breaks>
"""

PROMPT_EXPLICIT_PLUS_EXAMPLES = PROMPT_EXPLICIT + """
Two calibration examples.

REPORT this:
    total = float(price) * qty          # currency in float
  -> FINDING | MONEY | multiplies a float dollar amount | accumulates
     representation error across rows; the ledger will not balance

DO NOT report this:
    try:
        process(row)
    except Exception:
        log.exception("row %s failed", row.id)
        dead_letter.append(row)
  -> deliberate per-row isolation in a batch job. The failure is logged AND
     recorded for replay, so nothing is silently lost.
"""


def review(c, system):
    r = c.messages.create(model=MODEL, max_tokens=8000, system=system,
                          messages=[{"role": "user", "content": CODE}])
    return text_of(r)


def analyse(out: str):
    low = out.lower()
    lines = [l for l in out.splitlines() if l.strip().startswith("FINDING")]
    real = {k: any(m.lower() in low for m in ms) for k, ms in REAL.items()}
    noise = {k: any(m.lower() in low for m in ms) for k, ms in NOISE_MARKERS.items()}
    return lines, real, noise


def report(label, out):
    lines, real, noise = analyse(out)
    n_real, n_noise = sum(real.values()), sum(noise.values())
    print(f"\n  {label}")
    print(f"    findings emitted: {len(lines)}")
    print(f"    real bugs caught: {n_real}/3   {[k for k, v in real.items() if v]}")
    print(f"    noise categories: {n_noise}/5   {[k for k, v in noise.items() if v]}")
    for l in lines[:8]:
        print(f"      {l[:110]}")
    return n_real, n_noise, len(lines)


def main():
    c = client()
    banner("Explicit criteria beat confidence filtering",
           "Task 4.1 — precision and false positives")
    note("One file: 3 real defects, 5 deliberate patterns that look like defects.")

    bad("Prompt A — 'be conservative, only high-confidence findings'")
    out_a = review(c, PROMPT_VAGUE)
    ra, na, ta = report("vague confidence filter", out_a)

    good("Prompt B — explicit REPORT / DO NOT REPORT categories")
    out_b = review(c, PROMPT_EXPLICIT)
    rb, nb, tb = report("explicit categorical criteria", out_b)

    good("Prompt C — explicit criteria + 2 calibration examples")
    out_c = review(c, PROMPT_EXPLICIT_PLUS_EXAMPLES)
    rc_, nc, tc = report("explicit criteria + few-shot", out_c)

    section("Comparison")
    print(f"                                  real/3   noise/5   total findings")
    print(f"    A  vague confidence filter     {ra}        {na}         {ta}")
    print(f"    B  explicit criteria           {rb}        {nb}         {tb}")
    print(f"    C  explicit + examples         {rc_}        {nc}         {tc}")
    print(
        "\n  What to look at: not the totals, but whether noise dropped WITHOUT recall\n"
        "  dropping. 'Be conservative' tends to move both numbers together — it makes\n"
        "  the reviewer quieter, not more accurate. Explicit criteria move them apart,\n"
        "  because they change WHICH things qualify rather than HOW MANY."
    )
    if nb < na:
        note(f"Noise categories fell from {na} to {nb} under explicit criteria.")
    if rb < ra:
        note("Recall also fell. Check whether the DO-NOT-REPORT list is over-broad and "
             "is excluding a real defect — that is the failure mode of this technique, "
             "and it is why the exam pairs criteria with calibration examples (C).")

    section("Severity criteria need the same treatment")
    print(
        "  'Rate severity as high/medium/low' produces inconsistent classification for\n"
        "  the same reason 'be conservative' does — the scale is undefined. Define each\n"
        "  level with a CONCRETE CODE EXAMPLE:\n\n"
        "    BLOCKER  incorrect behaviour reaches production or data is lost\n"
        "             e.g. float arithmetic on a currency amount that is persisted\n"
        "    MAJOR    incorrect behaviour under a reachable edge case\n"
        "             e.g. `a < 90 or b == 'void'` where `and` was intended\n"
        "    MINOR    correct, but will mislead the next reader in a way that risks\n"
        "             a future bug\n"
        "             e.g. a comment describing behaviour the code no longer has\n\n"
        "  An anchored example per level is what makes two runs agree with each other."
    )

    section("The remediation the exam wants")
    print(
        "  When one category is generating most of the false positives:\n\n"
        "    1. DISABLE that category in production now. Do not leave it running while\n"
        "       you iterate — every noisy comment is spending trust the accurate\n"
        "       categories depend on.\n"
        "    2. Rewrite its criteria offline against real dismissed findings.\n"
        "    3. Re-enable once precision is acceptable.\n\n"
        "  This feels like a regression and is not. A review bot developers ignore has\n"
        "  a true positive rate of zero regardless of what its metrics say."
    )

    takeaway(
        "'Be conservative' / 'high confidence only' do NOT improve precision.",
        "Define WHICH categories to report and which to skip, in checkable terms.",
        "Criteria about the CODE beat criteria about the model's confidence.",
        "Anchor each severity level to a concrete code example or you get drift.",
        "One noisy category poisons trust in all of them — disable it while you fix it.",
    )


if __name__ == "__main__":
    main()
