"""
Task 5.3 — Error propagation strategies across multi-agent systems.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain5_context/t5_3_error_propagation.py

THIS IS SAMPLE QUESTION 8
-------------------------
"The web search subagent times out while researching a complex topic. Which error
propagation approach best enables intelligent recovery?"

  A. Return structured error context: failure type, attempted query, partial
     results, potential alternatives.                                <-- correct
  B. Retry with exponential backoff inside the subagent, then return a generic
     "search unavailable" after retries are exhausted.
  C. Catch the timeout and return an empty result set marked successful.
  D. Propagate the exception to a top-level handler that terminates the workflow.

B is the trap, because the retry half is genuinely GOOD practice — local recovery
for transient failures is exactly what the exam wants. What makes B wrong is the
second half: collapsing everything into "search unavailable" throws away the
attempted query, the partial results it did collect, and the failure type. The
coordinator is left with nothing to decide with.

C and D are the two named anti-patterns:
  C  silently suppressing an error as success — the coordinator reports a
     confident "nothing found" for a search that never ran.
  D  terminating the entire workflow on one subagent failure — discarding all the
     work that DID succeed.

WHAT A GOOD PROPAGATION PAYLOAD CONTAINS
----------------------------------------
    failure_type        so the coordinator can choose retry vs route-around
    attempted           so it does not reissue the identical failing query
    partial_results     so the successful portion is not thrown away
    alternatives        the subagent knows its own domain; let it suggest
    coverage_gap        what is now unknown, for annotation in the final report

And the last step people forget: the final report must ANNOTATE which findings
are well-supported and which topic areas have gaps due to unavailable sources.
A report that silently omits the gap is indistinguishable from a complete one.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of

COORDINATOR_SYSTEM = """\
You are a research coordinator. You dispatched three subagents and their results
are below. Decide what to do next, then produce the briefing.

Begin your response with a PLAN block listing, for each subagent, exactly one of:
  RETRY_MODIFIED  — reissue with a changed query (say what you would change)
  ROUTE_AROUND    — use a different source or subagent
  ACCEPT_PARTIAL  — proceed with what came back
  NO_ACTION       — nothing needed

Then write the briefing. The briefing MUST have a "Coverage" section stating
which topic areas are well-supported and which have gaps, and why.
"""

# --- Regime A: generic statuses ------------------------------------------
GENERIC = json.dumps({
    "music_agent": {"status": "search unavailable"},
    "film_agent": {"status": "ok", "findings": [
        "Studio VFX headcount down 14% YoY (Screen Trade Weekly, 2025-09)",
        "Three major studios adopted generative previs in 2025 (IndustryWatch, 2025-06)",
    ]},
    "writing_agent": {"status": "ok", "findings": []},
}, indent=2)

# --- Regime B: structured error context ----------------------------------
STRUCTURED = json.dumps({
    "music_agent": {
        "status": "partial_failure",
        "failure_type": "timeout",
        "attempted": "session musician bookings AND generative audio 2024..2025, "
                     "sources: trade press + union reports",
        "retries_attempted": 3,
        "local_recovery": "retried 3x with backoff; the union-report index host "
                          "did not respond on any attempt",
        "partial_results": [
            "Library-music session bookings fell 21% YoY (Musicians Union Quarterly, "
            "2025-10-04)",
        ],
        "alternatives": [
            "narrow the date range to 2025 only and retry the trade-press index",
            "the PRS royalty-distribution dataset covers overlapping ground and "
            "responded normally",
        ],
        "coverage_gap": "no data on live-performance or touring work; only library "
                        "music is represented",
    },
    "film_agent": {
        "status": "ok",
        "findings": [
            "Studio VFX headcount down 14% YoY (Screen Trade Weekly, 2025-09)",
            "Three major studios adopted generative previs in 2025 (IndustryWatch, 2025-06)",
        ],
    },
    "writing_agent": {
        # THE distinction from Task 2.2, at the coordinator layer: this search RAN
        # and legitimately matched nothing. It is not a failure and must not be
        # retried.
        "status": "ok",
        "findings": [],
        "searched": 1180,
        "note": "Search completed successfully. No sources in the indexed set "
                "addressed generative tools in long-form fiction publishing. This is "
                "a genuine absence of coverage, not an access failure.",
    },
}, indent=2)


def coordinate(c, payload):
    r = c.messages.create(
        model=MODEL, max_tokens=8000, system=COORDINATOR_SYSTEM,
        messages=[{"role": "user", "content":
                   "Topic: the impact of AI on creative industries.\n\n"
                   "<subagent_results>\n" + payload + "\n</subagent_results>"}],
    )
    return text_of(r)


def analyse(text):
    low = text.lower()
    return {
        "named a recovery action for the failed agent":
            any(k in low for k in ["retry_modified", "route_around", "accept_partial"]),
        "kept the partial result (the 21% figure)": "21%" in text or "21 %" in text,
        "has a Coverage section": "coverage" in low,
        "distinguished 'no results' from 'search failed'":
            any(k in low for k in ["no action", "no_action", "genuine absence",
                                   "not an access failure", "legitimately"]),
        "avoided retrying the empty-but-successful search":
            "writing" in low and ("no_action" in low or "no action" in low
                                  or "accept_partial" in low),
    }


def main():
    c = client()
    banner("Error propagation across agents", "Task 5.3 — this is exam Sample Question 8")

    bad("Regime A — generic statuses ('search unavailable', bare empty list)")
    a = coordinate(c, GENERIC)
    show("Coordinator output", a[:1000])
    ra = analyse(a)
    for k, v in ra.items():
        print(f"    [{'OK ' if v else 'MISS'}] {k}")
    note("The coordinator has no failure type, no attempted query, and no partial "
         "results. It cannot tell whether to retry, route around, or proceed — and it "
         "cannot tell the writing agent's genuine empty result apart from the music "
         "agent's failure, because both are just 'a status'.")

    good("Regime B — structured error context with partial results")
    b = coordinate(c, STRUCTURED)
    show("Coordinator output", b[:1400])
    rb = analyse(b)
    for k, v in rb.items():
        print(f"    [{'OK ' if v else 'MISS'}] {k}")

    section("Comparison")
    print(f"    generic statuses:  {sum(ra.values())}/{len(ra)} behaviours present")
    print(f"    structured errors: {sum(rb.values())}/{len(rb)} behaviours present")
    if rb["kept the partial result (the 21% figure)"] and not ra["kept the partial result (the 21% figure)"]:
        note("The 21% figure survived into the briefing under Regime B and was lost "
             "under Regime A. That finding was successfully retrieved before the "
             "timeout — a generic status threw away real, paid-for work.")

    section("The two anti-patterns, named")
    print(
        "  C — returning an empty result marked SUCCESSFUL\n"
        "      The coordinator reports 'no evidence found for music' when the truth is\n"
        "      'we never looked'. The error is not merely hidden; it has been converted\n"
        "      into a false finding that propagates into the deliverable.\n\n"
        "  D — terminating the whole workflow on one failure\n"
        "      The film agent succeeded. The writing agent completed a valid search.\n"
        "      Killing the run discards both and delivers nothing, when a briefing with\n"
        "      an annotated gap would have been useful.\n\n"
        "  B — retry locally, then return a generic status\n"
        "      The local retry is CORRECT — transient failures should be handled where\n"
        "      they occur. The mistake is discarding the context on the way out. Do\n"
        "      both: recover locally, and propagate what you could not fix WITH the\n"
        "      partial results and what you attempted."
    )

    section("Coverage annotation in the final report")
    print(
        "  The last step, and the easiest to skip: the synthesis output must state\n"
        "  which topic areas are well-supported and which have gaps.\n\n"
        "    Well-supported: film/VFX (2 independent trade sources, 2025)\n"
        "    Partial:        music — library music only; live and touring work not\n"
        "                    covered, union-report index unreachable\n"
        "    No data:        long-form fiction publishing — searched, nothing indexed\n\n"
        "  Without that section a reader cannot distinguish 'AI has no measurable\n"
        "  effect on fiction publishing' from 'we did not find out'. Those are opposite\n"
        "  claims and an unannotated report renders them identically."
    )

    takeaway(
        "Propagate failure_type + attempted + partial_results + alternatives.",
        "Recover locally for transient failures; propagate only what you couldn't fix.",
        "Local retry is right; collapsing to 'search unavailable' afterwards is wrong (B).",
        "Never mark a failure as an empty success (C) — it becomes a false finding.",
        "Never kill the workflow over one subagent (D) — annotate the gap and proceed.",
        "Access failure != valid empty result, at the coordinator layer too.",
        "The final report needs an explicit coverage section, or gaps are invisible.",
    )


if __name__ == "__main__":
    main()
