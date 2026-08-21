"""
Task 5.6 — Information provenance and uncertainty in multi-source synthesis.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain5_context/t5_6_provenance.py

(See also domain1_agentic/t1_3_context_passing.py, which covers the handoff side:
getting structured claim-source mappings ACROSS an agent boundary. This file is
about what the synthesis step must then do with them.)

THE FOUR REQUIREMENTS
---------------------
1. PRESERVE CLAIM-SOURCE MAPPINGS through every summarisation step. Attribution
   is lost at the moment findings are compressed without their sources, and it is
   not recoverable downstream — nobody can re-derive which source said which
   number.

2. CONFLICTING CREDIBLE SOURCES get ANNOTATED, not resolved. Two reputable
   organisations reporting different figures is information. Silently picking one
   destroys it and presents a contested number as settled.

3. TEMPORAL DATA needs publication/collection dates in the structured output, or
   a two-year trend gets reported as a contradiction.

4. RENDER BY CONTENT TYPE. Financial data as tables, news as prose, technical
   findings as structured lists. Flattening everything into one uniform format
   is its own information loss — a table of prose summaries is worse than either.

Also here: the synthesis agent should complete its analysis WITH conflicting
values included and explicitly annotated, and let the COORDINATOR decide how to
reconcile. A subagent that resolves a conflict unilaterally has made an editorial
decision the coordinator never saw.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of

# ---------------------------------------------------------------------------
# Findings with three deliberate traps:
#   * F1 vs F2 — a genuine conflict between two credible sources, SAME year
#   * F3 vs F4 — NOT a conflict: same metric, two years apart (a trend)
#   * mixed content types that want different rendering
# ---------------------------------------------------------------------------
FINDINGS = [
    {"id": "F1", "type": "statistic",
     "claim": "38% of illustrators lost commissions to generative tools",
     "value": 38, "unit": "percent",
     "source": "Illustrators Guild Annual Survey", "source_url": "https://example.org/guild-2025",
     "published": "2025-03-11", "method": "self-selected online survey of guild members, n=1204"},
    {"id": "F2", "type": "statistic",
     "claim": "12% of illustrators lost commissions to generative tools",
     "value": 12, "unit": "percent",
     "source": "National Arts Council Labour Report", "source_url": "https://example.org/nac-2025",
     "published": "2025-05-02", "method": "stratified random sample of tax-registered "
                                          "illustrators, n=3900"},
    {"id": "F3", "type": "statistic",
     "claim": "Session-musician bookings fell 21% year over year",
     "value": 21, "unit": "percent",
     "source": "Musicians Union Quarterly", "source_url": "https://example.org/mu-2025",
     "published": "2025-10-04", "method": "union booking records"},
    {"id": "F4", "type": "statistic",
     "claim": "Session-musician bookings fell 4% year over year",
     "value": 4, "unit": "percent",
     "source": "Musicians Union Quarterly", "source_url": "https://example.org/mu-2023",
     "published": "2023-10-02", "method": "union booking records"},
    {"id": "F5", "type": "financial",
     "claim": "Stock-image licensing revenue by year",
     "table": {"2022": 4.10, "2023": 3.80, "2024": 3.05, "2025": 2.40},
     "unit": "USD billions",
     "source": "MediaMetrics Annual", "source_url": "https://example.org/mm-2025",
     "published": "2026-01-15"},
    {"id": "F6", "type": "news",
     "claim": "Three major studios announced generative previs pipelines in 2025",
     "source": "Screen Trade Weekly", "source_url": "https://example.org/stw-2025",
     "published": "2025-09-18"},
    {"id": "F7", "type": "technical",
     "claim": "Diffusion-based previs reduces iteration time",
     "details": ["mean shot iteration 4.2h -> 1.1h", "artist headcount per sequence 6 -> 4",
                 "measured across 11 sequences at one studio"],
     "source": "SIGGRAPH 2025 industry track", "source_url": "https://example.org/sig-2025",
     "published": "2025-08-09"},
]

NAIVE_SYSTEM = (
    "You are a synthesis agent. Combine the findings into a clear briefing on AI's "
    "impact on creative industries. Keep it readable."
)

PROVENANCE_SYSTEM = """\
You are a synthesis agent. Combine the findings into a briefing.

PROVENANCE RULES — these are not style preferences.

1. Every figure carries its source. No number appears without attribution.

2. When two credible sources give DIFFERENT values for the SAME metric over the
   SAME period, report BOTH with attribution and with their methodologies. Do not
   average them, do not pick the one you find more plausible, and do not describe
   the range as if it were a single finding. Where the methodologies explain the
   divergence, say so — that is the most useful sentence you can write.

3. Before calling anything a contradiction, CHECK THE DATES. Two figures for the
   same metric from different years are a TREND, not a conflict. Report them as a
   time series.

4. Structure the briefing with explicit sections separating WELL-ESTABLISHED
   findings (corroborated, or single-source with sound method) from CONTESTED
   ones (credible sources disagree).

5. Render each content type in its natural form:
     financial / time series  -> a table
     news / events            -> prose
     technical measurements   -> a structured list
   Do not flatten everything into one format.

6. Preserve the original source's characterisation. Do not restate a
   self-selected survey as if it were a random sample.
"""


def synthesise(c, system):
    r = c.messages.create(
        model=MODEL, max_tokens=12000, system=system,
        messages=[{"role": "user", "content":
                   "<findings>\n" + json.dumps(FINDINGS, indent=2) + "\n</findings>"}],
    )
    return text_of(r)


def audit(text):
    low = text.lower()
    return {
        "reports BOTH 38% and 12%": "38" in text and "12" in text,
        "attributes each to its source":
            "guild" in low and ("arts council" in low or "national arts" in low),
        "explains the methodological difference":
            any(k in low for k in ["self-selected", "self selected", "stratified",
                                   "random sample", "methodolog", "sampling"]),
        "treats 21% vs 4% as a TREND, not a conflict":
            ("2023" in text and "2025" in text) and
            not any(k in low for k in ["21% and 4% conflict", "conflicting booking",
                                       "contradictory booking"]),
        "has a contested/established split":
            any(k in low for k in ["contested", "well-established", "well established",
                                   "disputed", "corroborated"]),
        "renders the financial series as a table": text.count("|") >= 6,
        "keeps a technical finding as a list":
            ("4.2" in text and "1.1" in text),
    }


def main():
    c = client()
    banner("Provenance in multi-source synthesis", "Task 5.6")
    print(f"  {len(FINDINGS)} findings: 1 genuine conflict, 1 apparent conflict that is\n"
          f"  a trend, and three different content types.")

    bad("Naive synthesis — 'combine these into a clear briefing'")
    a = synthesise(c, NAIVE_SYSTEM)
    show("Output", a[:1200])
    ra = audit(a)
    for k, v in ra.items():
        print(f"    [{'OK ' if v else 'MISS'}] {k}")
    note("Watch for the two characteristic failures: collapsing 38% and 12% into a "
         "single figure or a bare 'between 12 and 38 percent', and treating the 2023 "
         "and 2025 booking numbers as though they disagree.")

    good("Provenance-preserving synthesis")
    b = synthesise(c, PROVENANCE_SYSTEM)
    show("Output", b[:2000])
    rb = audit(b)
    for k, v in rb.items():
        print(f"    [{'OK ' if v else 'MISS'}] {k}")

    section("Comparison")
    print(f"    naive:                {sum(ra.values())}/{len(ra)} provenance behaviours")
    print(f"    provenance-preserving:{sum(rb.values())}/{len(rb)} provenance behaviours")
    for k in ra:
        if rb[k] and not ra[k]:
            print(f"      gained: {k}")

    section("The three traps, explained")
    print(
        "  F1 vs F2 — A GENUINE CONFLICT\n"
        "    38% (Guild, self-selected survey of members) vs 12% (Arts Council,\n"
        "    stratified random sample of tax-registered illustrators), both 2025.\n"
        "    A self-selected survey of an affected population over-samples people\n"
        "    motivated to respond. That is not a reason to discard it — it measures a\n"
        "    real thing about a real group — but it is why the numbers differ, and\n"
        "    saying so is more useful than either figure alone. Averaging them to 25%\n"
        "    produces a number that no one measured and that describes nobody.\n\n"
        "  F3 vs F4 — NOT A CONFLICT\n"
        "    Same metric, same source, 2023 and 2025. Without the publication dates in\n"
        "    the structured output, an agent sees 'bookings fell 21%' and 'bookings\n"
        "    fell 4%' from one source and reasonably concludes the data is unreliable.\n"
        "    With dates, it is an accelerating decline — which is the actual finding.\n"
        "    This is why the exam requires dates in subagent output rather than\n"
        "    treating them as optional metadata.\n\n"
        "  F5 / F6 / F7 — THREE CONTENT TYPES\n"
        "    A four-year revenue series is a table. A studio announcement is a\n"
        "    sentence. A set of measured deltas is a list. Forcing all three into\n"
        "    prose loses the series' shape; forcing all three into a table produces\n"
        "    cells containing paragraphs."
    )

    section("Where the subagent's responsibility ends")
    print(
        "  A document-analysis subagent that finds conflicting values completes its\n"
        "  analysis WITH BOTH VALUES, explicitly annotated, and hands them up. It does\n"
        "  not decide which is right.\n\n"
        "  The coordinator has context the subagent lacks — the other agents' findings,\n"
        "  the audience, the purpose — and it is the layer accountable for the final\n"
        "  claim. A subagent that quietly resolves a conflict has made an editorial\n"
        "  decision that never appears in any log."
    )

    takeaway(
        "Attribution is lost at summarisation and is NOT recoverable downstream.",
        "Conflicting credible sources: report both with methods. Never average, never pick.",
        "Check dates before calling something a contradiction — it is often a trend.",
        "Require publication/collection dates in every subagent's structured output.",
        "Render financial as tables, news as prose, technical as lists. Don't flatten.",
        "Preserve the source's own characterisation (self-selected != random sample).",
        "Subagents annotate conflicts; the COORDINATOR reconciles them.",
    )


if __name__ == "__main__":
    main()
