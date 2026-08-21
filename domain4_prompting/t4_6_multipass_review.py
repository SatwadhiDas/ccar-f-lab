"""
Task 4.6 — Multi-instance and multi-pass review architectures.
Task 5.5 — Confidence calibration for review routing.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain4_prompting/t4_6_multipass_review.py

THE SELF-REVIEW LIMITATION
--------------------------
A model that just generated code retains the REASONING that produced it. Asked to
review its own output in the same session, it is measurably less likely to
question its own decisions — the justification for every choice is sitting right
there in context, and re-deriving it feels like confirming it.

The exam is specific that an INDEPENDENT INSTANCE — a fresh session with no prior
reasoning context — beats both:
  * "now review your work carefully" instructions in the same session, and
  * extended thinking.

Neither of those removes the contaminating context. Only a new instance does.
This is the same principle as CI session isolation in Task 3.6.

This script generates code with a deliberate bug baked into the requirements,
then tries three review architectures against it and counts which find it.

MULTI-PASS (see also t1_6, which measures this)
-----------------------------------------------
Split a large review into per-file local passes plus a separate cross-file
integration pass, to avoid attention dilution and contradictory findings.

CONFIDENCE CALIBRATION (Task 5.5)
---------------------------------
Have the model emit a confidence score PER FINDING, then route by it. The
important caveat, which the exam states elsewhere (Sample Question 3): raw
self-reported confidence is poorly calibrated. It is usable for ROUTING relative
attention, and it is not usable as a correctness signal. You calibrate the
thresholds against a labelled validation set — you do not trust the number.
"""

import sys
import os
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of

# The spec contains a trap: "expire entries older than the TTL" plus "check the
# cache before acquiring the lock" invites a classic check-then-act race.
SPEC = """\
Write a Python class `TTLCache` with:
  - get(key) -> value or None
  - set(key, value)
  - a max_size; when full, evict the least recently used entry
  - entries expire after ttl_seconds
  - it must be safe to use from multiple threads
  - for speed, check whether the key is present BEFORE acquiring the lock
Return only the code.
"""

REVIEW_CRITERIA = """\
You are reviewing Python code for defects.

Report: race conditions, incorrect locking, logic errors, boundary errors,
resource leaks, and incorrect eviction/expiry behaviour.
Skip: naming, formatting, type hints, docstrings.

For each finding output exactly one line:
FINDING | <confidence 0.0-1.0> | <severity blocker|major|minor> | <description>

Confidence is your own estimate that this is a real defect a maintainer would fix.
"""


def generate(c):
    r = c.messages.create(
        model=MODEL, max_tokens=8000,
        system="You are a senior Python engineer. Follow the specification exactly.",
        messages=[{"role": "user", "content": SPEC}],
    )
    return text_of(r), r


def parse_findings(text):
    out = []
    for line in text.splitlines():
        if not line.strip().startswith("FINDING"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        try:
            conf = float(re.findall(r"[\d.]+", parts[1])[0])
        except (IndexError, ValueError):
            conf = None
        out.append({"confidence": conf, "severity": parts[2].lower(), "issue": parts[3]})
    return out


RACE_MARKERS = ["race", "check-then-act", "check then act", "toctou", "outside the lock",
                "before acquiring", "not atomic", "unsynchronized", "unsynchronised",
                "double-check", "without the lock", "lock is not held"]


def found_race(findings):
    blob = " ".join(f["issue"].lower() for f in findings)
    return any(m in blob for m in RACE_MARKERS)


def main():
    c = client()
    banner("Multi-instance review and confidence calibration", "Task 4.6 / 5.5")

    section("1. Generate the code")
    code, gen_response = generate(c)
    show("Generated (truncated)", code[:900])
    note("The spec deliberately asked for the lock-free pre-check, so a check-then-act "
         "race is almost certainly present. The question is which reviewer finds it.")

    # -- A. Self-review, same session ---------------------------------------
    bad("Architecture A — self-review inside the SAME session")
    messages = [
        {"role": "user", "content": SPEC},
        {"role": "assistant", "content": gen_response.content},
        {"role": "user", "content":
            "Now review the code you just wrote for defects, carefully and critically.\n\n"
            + REVIEW_CRITERIA},
    ]
    r_self = c.messages.create(model=MODEL, max_tokens=8000, messages=messages)
    f_self = parse_findings(text_of(r_self))
    print(f"    findings: {len(f_self)}   found the race: {found_race(f_self)}")
    for f in f_self[:5]:
        print(f"      [{f['confidence']}] {f['severity']:8s} {f['issue'][:72]}")

    # -- B. Self-review + "extended thinking" style instruction -------------
    bad("Architecture B — same session, told to think harder first")
    messages_b = messages[:-1] + [{"role": "user", "content":
        "Think step by step about every concurrency interleaving that could occur in "
        "the code you just wrote, then review it for defects.\n\n" + REVIEW_CRITERIA}]
    r_think = c.messages.create(model=MODEL, max_tokens=12000, messages=messages_b)
    f_think = parse_findings(text_of(r_think))
    print(f"    findings: {len(f_think)}   found the race: {found_race(f_think)}")
    note("Still the same session, so the reasoning that produced the code is still in "
         "context. The exam's claim is that thinking harder does not substitute for "
         "removing that context.")

    # -- C. Independent instance --------------------------------------------
    good("Architecture C — INDEPENDENT instance, no generation context")
    r_indep = c.messages.create(
        model=MODEL, max_tokens=8000, system=REVIEW_CRITERIA,
        messages=[{"role": "user", "content":
                   "Review this code.\n\n```python\n" + code + "\n```"}],
    )
    f_indep = parse_findings(text_of(r_indep))
    print(f"    findings: {len(f_indep)}   found the race: {found_race(f_indep)}")
    for f in f_indep[:6]:
        print(f"      [{f['confidence']}] {f['severity']:8s} {f['issue'][:72]}")

    section("Comparison")
    for label, fs in [("A self-review", f_self), ("B self + think", f_think),
                      ("C independent", f_indep)]:
        print(f"    {label:16s} findings={len(fs):2d}  race_found={found_race(fs)}")
    if found_race(f_indep) and not found_race(f_self):
        note("The independent instance caught the race the self-review missed. Exactly "
             "the exam's claim.")
    elif found_race(f_self) and found_race(f_indep):
        note("Both caught it this run. The mechanism still holds — the generating "
             "session is BIASED toward its own choices, not blind to them. On subtler "
             "defects the gap widens, and you cannot know in advance which defects are "
             "subtle enough to matter. Architecturally, isolate.")
    note("The independent instance also never saw the SPEC — so it cannot excuse the "
         "race with 'the requirements asked for the lock-free pre-check'. That excuse "
         "is available to the self-reviewer and is a large part of the effect.")

    # -- Confidence routing --------------------------------------------------
    section("2. Confidence-based review routing (Task 5.5)")
    all_findings = f_indep
    if all_findings and any(f["confidence"] is not None for f in all_findings):
        hi = [f for f in all_findings if (f["confidence"] or 0) >= 0.8]
        mid = [f for f in all_findings if 0.5 <= (f["confidence"] or 0) < 0.8]
        lo = [f for f in all_findings if (f["confidence"] or 0) < 0.5]
        print(f"    >= 0.80 : {len(hi):2d}  -> auto-post to the PR")
        print(f"  0.50-0.79 : {len(mid):2d}  -> queue for human review")
        print(f"    <  0.50 : {len(lo):2d}  -> log only, do not surface")
        note("Those thresholds are placeholders until you calibrate them against a "
             "LABELLED validation set. Pick them by intuition and you will either spam "
             "the PR or suppress real bugs — and you will not know which.")

    print(
        "\n  The critical caveat (exam Sample Question 3): self-reported confidence is\n"
        "  POORLY CALIBRATED. An agent that is wrong about a hard case is typically\n"
        "  confident about it — which is why 'route to a human when confidence < X' was\n"
        "  the WRONG answer to the escalation question. Confidence is usable for\n"
        "  allocating scarce reviewer attention across findings; it is not usable as\n"
        "  evidence that a finding is correct."
    )

    section("3. Multi-pass, and where each technique belongs")
    print(
        "    attention dilution over many files   -> per-file passes + integration pass\n"
        "                                            (measured in domain1/t1_6)\n"
        "    reviewer biased by its own reasoning -> independent instance (this file)\n"
        "    too many findings for the reviewers  -> confidence routing + calibration\n"
        "    noisy finding CATEGORY               -> explicit criteria (t4_1)\n\n"
        "    These are four different failures. Reaching for the wrong remedy is a\n"
        "    common exam trap: a bigger context window does not fix dilution, and\n"
        "    'be more careful' does not fix self-review bias."
    )

    takeaway(
        "The generating session is biased toward its own decisions. Isolate the reviewer.",
        "An independent instance beats BOTH self-review instructions and extended thinking.",
        "Same principle as CI: never let the session that wrote the code review it.",
        "Split large reviews per-file + a cross-file integration pass (attention dilution).",
        "Confidence routes reviewer attention; it is NOT evidence of correctness.",
        "Calibrate confidence thresholds on a labelled validation set, never by intuition.",
    )


if __name__ == "__main__":
    main()
