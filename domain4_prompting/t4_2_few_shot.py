"""
Task 4.2 — Few-shot prompting for output consistency and quality.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain4_prompting/t4_2_few_shot.py

WHEN THE EXAM WANTS FEW-SHOT
----------------------------
  * Detailed instructions alone are producing INCONSISTENT output format.
  * The hard cases are AMBIGUOUS and you need to show the reasoning for choosing
    one action over a plausible alternative.
  * Extraction across VARIED document structures (inline citations vs a
    bibliography, methodology in its own section vs embedded in prose) is
    returning empty/null for fields that are present but formatted unexpectedly.
  * You need the model to GENERALISE to patterns you did not enumerate, rather
    than matching only the cases you listed.

WHEN THE EXAM DOES **NOT** WANT FEW-SHOT — know this boundary
-------------------------------------------------------------
Sample Question 2: tools are being misrouted because their descriptions are
minimal. Few-shot examples are listed as a DISTRACTOR there; the answer is to fix
the descriptions. Examples add token overhead to every request without addressing
the root cause. Reach for few-shot when the instruction is CLEAR but application
is inconsistent — not when the instruction is missing.

How many: 2-4 targeted examples. The exam is specific about this. They should
cover the ambiguous middle, not the obvious cases the model already handles.
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of

# ---------------------------------------------------------------------------
# Three papers, three completely different structural conventions. The naive
# extractor handles the first and returns nulls for the other two.
# ---------------------------------------------------------------------------
PAPERS = {
    "A — conventional structure": """\
Title: Generative Models in Studio Practice
Authors: R. Okonkwo, L. Ferrand
Published: 2025-04-12

METHODOLOGY
We surveyed 1,204 working illustrators using a stratified random sample drawn from
guild membership rolls. Response rate was 61%.

REFERENCES
[1] Ferrand L. (2023). Labour shifts in commercial art. J. Creative Econ 8(2).
""",
    "B — bibliography-free, inline citations, no headings": """\
Generative Models and the Session Musician
Kaur & Oyelaran, submitted to the Q4 2025 issue of Audio Practice Review

This work reports on a two-wave panel of 380 session musicians recruited through
three London studios (a design previously validated by Ferrand 2023, and refined
following Okonkwo et al. 2024 who noted the sampling bias in guild-only rolls).
Attrition between waves was 9%. We do not repeat the instrument here; it appears
in full in Kaur 2024.
""",
    "C — memo format, informal measurements, no explicit date line": """\
MEMO — internal, do not circulate
re: what we're seeing in the illustration market
from the desk of J. Ainsworth, third quarter

Look, we talked to somewhere north of two hundred freelancers over the summer —
call it 210, 215, we stopped counting carefully after August. Roughly a third said
they'd lost at least one commission to an AI tool. Method was just phone calls,
nothing fancy, no sampling frame to speak of.
""",
}

SCHEMA_HINT = """\
Return exactly these fields, one per line:
TITLE:
AUTHORS:
DATE:              (ISO 8601 YYYY-MM-DD, or YYYY-QN, or "unknown")
SAMPLE_SIZE:       (integer, or a range like "210-215", or "unknown")
METHOD:            (one phrase, or "unknown")
CITED_WORKS:       (semicolon-separated, or "none")
"""

PROMPT_PLAIN = f"""\
You extract study metadata from research documents.

{SCHEMA_HINT}
Use "unknown" when a field is genuinely absent.
"""

# 2 targeted examples. Note what they demonstrate: not the easy case, but the two
# structural variants that break naive extraction — inline citations with no
# reference list, and an informal measurement with no explicit date.
PROMPT_FEWSHOT = f"""\
You extract study metadata from research documents.

{SCHEMA_HINT}
Use "unknown" only when a field is genuinely absent from the document. A field
written in an unexpected FORMAT is present, not absent.

EXAMPLE 1 — citations appear inline; there is no REFERENCES section.
Input:
    Effects of Automation on Studio Work
    Delacroix & Mbeki, to appear in the Spring 2024 Review of Media Labour
    We interviewed 96 engineers (a protocol adapted from Hoffmann 2021 and
    critiqued by Silva et al. 2022).
Output:
    TITLE: Effects of Automation on Studio Work
    AUTHORS: Delacroix, Mbeki
    DATE: 2024-Q2
    SAMPLE_SIZE: 96
    METHOD: interviews
    CITED_WORKS: Hoffmann 2021; Silva et al. 2022
Why: cited works were extracted from INLINE parenthetical citations even though
there is no bibliography. "Spring 2024" resolves to a quarter, not "unknown".

EXAMPLE 2 — informal measurements, no explicit date, no formal method.
Input:
    NOTES from the field, second quarter, M. Duarte
    Chatted with maybe 40-odd studio owners, give or take. No real method here,
    just conversations at the trade show.
Output:
    TITLE: NOTES from the field
    AUTHORS: M. Duarte
    DATE: 2025-Q2
    SAMPLE_SIZE: ~40
    METHOD: informal conversations
    CITED_WORKS: none
Why: "maybe 40-odd" is an approximate sample size, not an absent one — record it
as approximate rather than discarding it. An informal method is still a method.
"""


def extract(c, system, doc):
    r = c.messages.create(model=MODEL, max_tokens=2000, system=system,
                          messages=[{"role": "user", "content": doc}])
    return text_of(r)


def fields(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Z_]+):\s*(.*)", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def unknowns(f):
    return [k for k, v in f.items()
            if v.lower() in ("unknown", "none", "n/a", "")
            and k in ("DATE", "SAMPLE_SIZE", "METHOD", "CITED_WORKS")]


def main():
    c = client()
    banner("Few-shot prompting", "Task 4.2 — consistency, ambiguity, generalization")

    # -- 1. Varied document structures --------------------------------------
    section("1. Extraction across varied document structures")
    totals = {"plain": 0, "fewshot": 0}
    for label, doc in PAPERS.items():
        print(f"\n  {label}")
        a = fields(extract(c, PROMPT_PLAIN, doc))
        b = fields(extract(c, PROMPT_FEWSHOT, doc))
        ua, ub = unknowns(a), unknowns(b)
        totals["plain"] += len(ua)
        totals["fewshot"] += len(ub)
        print(f"    instructions only : unknown/empty -> {ua or 'none'}")
        print(f"        {'  '.join(f'{k}={a.get(k)!r}' for k in ('DATE','SAMPLE_SIZE','CITED_WORKS'))}")
        print(f"    with 2 examples   : unknown/empty -> {ub or 'none'}")
        print(f"        {'  '.join(f'{k}={b.get(k)!r}' for k in ('DATE','SAMPLE_SIZE','CITED_WORKS'))}")

    section("Result")
    print(f"  spurious 'unknown' fields, instructions only: {totals['plain']}")
    print(f"  spurious 'unknown' fields, with few-shot:     {totals['fewshot']}")
    note("The information was present in every document. What differed was the FORMAT "
         "it was presented in. This is the exam's 'empty/null extraction of required "
         "fields' failure, and few-shot examples of varied structures are the named fix.")

    # -- 2. Generalization ---------------------------------------------------
    section("2. Generalization to a structure the examples never showed")
    print("  Document C is a memo — neither example covered a memo, informal counting,\n"
          "  or 'third quarter' with no year. Did the examples transfer?")
    c_out = fields(extract(c, PROMPT_FEWSHOT, PAPERS["C — memo format, informal measurements, no explicit date line"]))
    print(f"    DATE:        {c_out.get('DATE')!r}")
    print(f"    SAMPLE_SIZE: {c_out.get('SAMPLE_SIZE')!r}")
    print(f"    METHOD:      {c_out.get('METHOD')!r}")
    note("The examples taught a PRINCIPLE — approximate values are values, informal "
         "methods are methods — rather than a lookup table of formats. That transfer to "
         "unseen patterns is exactly what the exam means by enabling the model to "
         "generalise rather than matching only pre-specified cases.")

    # -- 3. Format consistency ----------------------------------------------
    section("3. Format consistency for actionable output")
    diff = ('def apply(rate, amount):\n'
            '    return float(amount) * rate   # currency as float\n')
    vague = ("Review this code and give actionable feedback about any issues, "
             "including where the problem is, how severe it is, and how to fix it.")
    shaped = vague + """

Format EVERY finding exactly like these:

  src/billing/tax.py:14 | MAJOR | float arithmetic on a currency amount |
  represent money in integer minor units and divide only at display time

  src/api/orders.py:88 | BLOCKER | user input concatenated into SQL |
  use a parameterised query with bound parameters
"""
    a = extract(c, vague, diff)
    b = extract(c, shaped, diff)
    show("Detailed instructions only", a[:400])
    show("With 2 format examples", b[:400])
    piped = len([l for l in b.splitlines() if l.count("|") >= 3])
    print(f"  lines matching the target shape: {piped}")
    note("Prose instructions describing a format get approximated. Two examples OF the "
         "format get reproduced. When a downstream parser consumes this, the difference "
         "is whether your pipeline works.")

    # -- 4. The boundary -----------------------------------------------------
    section("4. When NOT to reach for few-shot")
    print(
        "  Sample Question 2: two tools are misrouted because their descriptions are\n"
        "  minimal ('Retrieves customer information'). Adding 5-8 routing examples is\n"
        "  an explicit DISTRACTOR. The answer is to expand the descriptions.\n\n"
        "  The distinction:\n"
        "    Instruction is MISSING or WRONG      -> fix the instruction\n"
        "    Instruction is CLEAR, application is\n"
        "      inconsistent or format drifts      -> few-shot examples\n\n"
        "  Few-shot examples ride along on every request forever. Spend them on the\n"
        "  ambiguous middle, not on compensating for something you could have just\n"
        "  said clearly. 2-4 targeted examples, showing the REASONING for choosing one\n"
        "  action over a plausible alternative — that is the exam's specification."
    )

    takeaway(
        "Few-shot is the fix for INCONSISTENT application, not for MISSING instructions.",
        "2-4 targeted examples covering the ambiguous middle, not the obvious cases.",
        "Show the reasoning for choosing one action over a plausible alternative.",
        "Examples of varied document structures fix spurious empty/null extraction.",
        "Good examples teach a principle and generalise to patterns you never listed.",
        "For format consistency, show the format — describing it in prose gets approximated.",
        "Sample Question 2: few-shot is the WRONG answer when descriptions are the problem.",
    )


if __name__ == "__main__":
    main()
