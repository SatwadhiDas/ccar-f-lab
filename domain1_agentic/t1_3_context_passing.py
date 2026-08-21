"""
Task 1.3 — Subagent context passing (the isolation property, proven).
Task 5.6 — Preserving provenance across a handoff.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain1_agentic/t1_3_context_passing.py

THE CLAIM THE EXAM MAKES
------------------------
"Subagent context must be explicitly provided in the prompt — subagents do not
automatically inherit parent context or share memory between invocations."

That sentence is easy to nod along to and easy to get wrong under exam pressure,
because a coordinator that says "summarise the findings above" *looks* like it
works. This script runs the same subagent twice against the same request:

  Run A: prompt refers to context the subagent cannot see.
  Run B: prompt carries the findings inline, as structured claim/source/date
         entries.

Run A does not error. It produces confident, ungrounded prose — the worst
failure mode, because nothing in your telemetry flags it.

THE SECOND HALF: structured handoff
-----------------------------------
When you do pass context, pass it as STRUCTURED data that separates content from
metadata (source URL, document name, page number, publication date). Flatten the
findings into prose and the synthesis step has nothing left to cite with — this
is exactly how attribution gets lost in multi-agent pipelines (Task 5.6), and
why two figures from different years get reported as a contradiction rather than
as a time series.
"""

import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway, stream_messages

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
)

# ---------------------------------------------------------------------------
# Findings that a hypothetical upstream research subagent produced.
#
# Structured, not prose. Each entry keeps the claim separable from its metadata.
# This is the shape that survives a handoff.
# ---------------------------------------------------------------------------
FINDINGS = [
    {
        "claim": "Roughly 34% of surveyed illustrators reported losing commissions to generative tools.",
        "evidence": "34% of respondents (n=1,204) reported at least one commission lost to AI-generated alternatives.",
        "source": "Illustrators Guild Annual Survey",
        "source_url": "https://example.org/guild-survey-2025",
        "published": "2025-03-11",
    },
    {
        "claim": "Roughly 12% of surveyed illustrators reported losing commissions to generative tools.",
        "evidence": "12% cited AI as a direct cause of reduced commission volume.",
        "source": "National Arts Council Labour Report",
        "source_url": "https://example.org/nac-labour-2023",
        "published": "2023-09-02",
    },
    {
        "claim": "Session-musician bookings for library music fell 21% year over year.",
        "evidence": "Library-music session bookings declined 21% YoY, attributed in part to generative audio tools.",
        "source": "Musicians Union Quarterly",
        "source_url": "https://example.org/mu-q3-2025",
        "published": "2025-10-04",
    },
]

SYNTH_SYSTEM = (
    "You are a synthesis agent. You can see ONLY what is in this prompt — you have "
    "no access to any other agent's conversation, no shared memory, and no ability "
    "to search. Write a two-paragraph briefing. Cite a source for every figure. If "
    "two sources give different numbers for the same quantity, report BOTH with "
    "attribution and dates rather than choosing one. If you were given no data, say "
    "so plainly instead of writing from general knowledge."
)


async def run_subagent(prompt: str) -> str:
    """A minimal isolated agent — no tools, so it can only use what it is handed."""
    options = ClaudeAgentOptions(
        system_prompt=SYNTH_SYSTEM,
        tools=[],  # no tools: forces the point that its only input is the prompt
        max_turns=1,
        permission_mode="bypassPermissions",
    )
    out = []
    async for message in stream_messages(prompt, options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    out.append(block.text)
    return "\n".join(out).strip()


def structured_context_block(findings) -> str:
    """
    Render findings so content and metadata stay separable.

    JSON is used here rather than prose precisely because the downstream agent must
    be able to tell the claim apart from the URL and the date. That separation is
    what makes correct citation and correct temporal handling possible.
    """
    return json.dumps(findings, indent=2)


async def main():
    banner(
        "Subagent context isolation and structured handoff",
        "Task 1.3 — explicit context passing; Task 5.6 — provenance",
    )

    request = "Summarise what the research found about AI's effect on creative work."

    # -- Run A: assumes inheritance ----------------------------------------
    bad("Prompt refers to context the subagent cannot see")
    prompt_a = (
        f"{request}\n\n"
        "Use the findings from the web research agent and the document analyst "
        "above, and the figures we discussed earlier in this session."
    )
    show("Subagent prompt", prompt_a)
    answer_a = await run_subagent(prompt_a)
    show("Subagent output", answer_a[:900])
    note("No error was raised. Check whether the numbers above appear anywhere in "
         "FINDINGS — if the agent produced figures at all, it invented them, because "
         "it was handed none.")

    # -- Run B: context passed inline, structured --------------------------
    good("Prompt carries the findings inline as structured entries")
    prompt_b = (
        f"{request}\n\n"
        "Here are the complete findings from the upstream agents. This is everything "
        "you have.\n\n"
        "<findings>\n" + structured_context_block(FINDINGS) + "\n</findings>"
    )
    answer_b = await run_subagent(prompt_b)
    show("Subagent output", answer_b[:1400])

    section("Provenance checks on Run B")
    checks = {
        "cites the Guild survey": "guild" in answer_b.lower(),
        "cites the Arts Council report": "arts council" in answer_b.lower()
                                          or "national arts" in answer_b.lower(),
        "reports BOTH 34% and 12% rather than picking one":
            "34" in answer_b and "12" in answer_b,
        "surfaces the dates (2023 vs 2025) that explain the gap":
            "2023" in answer_b and "2025" in answer_b,
    }
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'MISS'}] {label}")

    if checks["reports BOTH 34% and 12% rather than picking one"]:
        note("The conflicting figures were preserved with attribution — the correct "
             "behaviour. Arbitrarily selecting one value is the exam's wrong answer.")
    if checks["surfaces the dates (2023 vs 2025) that explain the gap"]:
        note("Publication dates were carried through, so a two-year change reads as a "
             "trend rather than as a contradiction. This is why the exam insists "
             "subagents include dates in structured output.")

    section("What the flattened alternative would have cost you")
    print(
        "  Had the upstream agent handed over prose —\n"
        '     "surveys found between 12% and 34% of illustrators lost commissions"\n'
        "  — the synthesis agent would have had no way to attribute either figure, no\n"
        "  dates to reconcile them with, and no URL to cite. The information is not\n"
        "  recoverable downstream. Attribution is lost at the point of summarisation,\n"
        "  which is why the structure has to survive every hop, not just the last one."
    )

    takeaway(
        "Subagents inherit no history and no memory. Everything goes in the prompt.",
        "Missing context fails SILENTLY as confident invention — not as an error.",
        "Pass structured entries (claim / evidence / source / date), never flattened prose.",
        "Conflicting credible sources: report both with attribution; never pick one.",
        "Require publication dates or temporal differences masquerade as contradictions.",
    )


if __name__ == "__main__":
    asyncio.run(main())
