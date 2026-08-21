"""
Task 2.3 — Distribute tools across agents and configure tool choice.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain2_tools_mcp/t2_3_tool_distribution.py

TWO SEPARATE IDEAS THAT SHARE ONE TASK STATEMENT
------------------------------------------------
1. SCOPED TOOL ACCESS. Giving an agent 18 tools instead of the 4-5 its role needs
   degrades selection reliability, because every extra tool adds a discrimination
   the model has to get right. Worse, agents with tools outside their
   specialisation MISUSE them — the exam's example is a synthesis agent that
   starts doing its own web searches instead of synthesising.

   The fix is not "fewer tools globally". It is per-role tool sets, plus narrow
   cross-role tools for genuinely high-frequency needs. Exam Sample Question 9:
   the synthesis agent gets a scoped verify_fact for the 85% of verifications
   that are simple lookups, while complex ones still route through the
   coordinator. That is least privilege, not convenience.

2. tool_choice. Three modes, and the exam tests knowing which does what:

     {"type": "auto"}                  model decides whether to use a tool at all
     {"type": "any"}                   model MUST call some tool (no bare prose)
     {"type": "tool", "name": "..."}   model MUST call that specific tool

   "any" is the answer when you need a structured result and cannot tolerate a
   conversational reply. Forced selection is the answer when a specific tool must
   run FIRST — e.g. extract_metadata before any enrichment step — and you then
   handle subsequent steps in follow-up turns.

Also covered: replacing a generic tool with a constrained one (fetch_url ->
load_document that validates the URL is a document).
"""

import sys
import os
import json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of


def t(name, desc, props=("query",)):
    return {
        "name": name, "description": desc,
        "input_schema": {"type": "object",
                         "properties": {p: {"type": "string"} for p in props},
                         "required": [props[0]]},
    }


# ---------------------------------------------------------------------------
# The bloated toolset: everything every agent in the system might ever need.
# 18 tools, several of which overlap in ways a synthesis agent cannot resolve.
# ---------------------------------------------------------------------------
KITCHEN_SINK = [
    t("web_search", "Search the web."),
    t("web_search_news", "Search news sources."),
    t("web_search_academic", "Search academic papers."),
    t("fetch_url", "Fetch the contents of any URL."),
    t("load_document", "Load a document."),
    t("extract_data_points", "Extract fields from a document.", ("path",)),
    t("summarize_content", "Summarize a document.", ("path",)),
    t("verify_claim_against_source", "Verify a claim against a document.", ("claim",)),
    t("verify_fact", "Quickly verify a simple fact such as a date, name, or statistic."),
    t("translate_text", "Translate text."),
    t("detect_language", "Detect the language of text."),
    t("format_citation", "Format a citation."),
    t("check_plagiarism", "Check text for plagiarism."),
    t("generate_chart", "Generate a chart from data."),
    t("export_pdf", "Export content to PDF."),
    t("send_email", "Send an email."),
    t("schedule_task", "Schedule a task."),
    t("log_event", "Log an event."),
]

# The synthesis agent's actual job: combine findings it is GIVEN into a report.
# It needs almost nothing. One scoped cross-role tool covers the common case.
SYNTHESIS_SCOPED = [
    t("verify_fact",
      "Verify one simple, self-contained fact — a date, a name, a published "
      "statistic — against a quick reference lookup. Returns confirmed / "
      "contradicted / unknown with a source. "
      "BOUNDARY: this handles simple fact-checks only. For anything needing "
      "multi-source research or interpretation, do NOT attempt it yourself — say "
      "you need the coordinator to task the research agent."),
    t("format_citation", "Format a citation in the requested style.", ("source",)),
]

SYNTHESIS_SYSTEM = (
    "You are the SYNTHESIS agent in a multi-agent research pipeline. Your job is to "
    "combine findings that are given to you into a cited report. You do not conduct "
    "research. If you need information you were not given, say so."
)

FINDINGS_PROMPT = """\
Synthesise these findings into a two-sentence summary.

<findings>
- Session-musician bookings fell 21% YoY. (Musicians Union Quarterly, 2025-10-04)
- 34% of illustrators reported lost commissions. (Illustrators Guild, 2025-03-11)
</findings>

Before you write it, confirm that the Musicians Union figure was published in 2025,
and also work out what the equivalent trend looks like across film-scoring work in
Europe, which is not in the findings above.
"""


def tools_called(c, tools, system, prompt, tool_choice=None):
    kwargs = {"tool_choice": tool_choice} if tool_choice else {}
    r = c.messages.create(model=MODEL, max_tokens=4000, system=system, tools=tools,
                          messages=[{"role": "user", "content": prompt}], **kwargs)
    return [b.name for b in r.content if b.type == "tool_use"], text_of(r), r.stop_reason


def main():
    c = client()
    banner("Tool distribution and tool_choice", "Task 2.3")

    # -- 1. Scoping --------------------------------------------------------
    section("1. Scoped tool access")
    print("  The synthesis agent is asked to do its job, plus one thing outside its role\n"
          "  (research European film-scoring trends, which it was given no data for).")

    bad(f"Synthesis agent given the full {len(KITCHEN_SINK)}-tool set")
    used_all = Counter()
    for _ in range(3):
        calls, _, _ = tools_called(c, KITCHEN_SINK, SYNTHESIS_SYSTEM, FINDINGS_PROMPT)
        used_all.update(calls)
        print(f"    called: {calls}")
    off_role = {k: v for k, v in used_all.items() if k.startswith("web_search") or k == "fetch_url"}
    if off_role:
        note(f"Reached for research tools outside its specialisation: {off_role}. This is "
             "the exam's 'synthesis agent attempting web searches'. It is not "
             "disobedience — the tool was there, and the request implied a gap.")
    else:
        note("Stayed in role this run. The reliability cost of 18 tools is still real: "
             "every request pays their schema tokens, and the model must discriminate "
             "among three near-identical web_search variants on every call.")

    good("Synthesis agent given 2 scoped tools (one cross-role: verify_fact)")
    for _ in range(3):
        calls, text, _ = tools_called(c, SYNTHESIS_SCOPED, SYNTHESIS_SYSTEM, FINDINGS_PROMPT)
        print(f"    called: {calls}")
    show("Agent's response", text[:600])
    note("The 85% case (confirm a publication date) is handled locally by verify_fact. "
         "The out-of-scope research request has no tool to satisfy it, so the agent "
         "surfaces the gap instead of quietly half-doing it. That is the desired "
         "behaviour — the coordinator is the one who decides to task a researcher.")
    print(f"\n  schema cost: {len(KITCHEN_SINK)} tools vs {len(SYNTHESIS_SCOPED)}, on EVERY request in the loop.")

    # -- 2. Constrained replacements ---------------------------------------
    section("2. Replacing a generic tool with a constrained one")
    print(
        "  fetch_url('any URL')  ->  load_document(url)\n"
        "  The replacement validates that the URL points at a document, rejects\n"
        "  everything else with a validation error, and says so in its description.\n"
        "  Generic tools are attractive nuisances: fetch_url is reachable from every\n"
        "  request, so it becomes the agent's universal escape hatch — including for\n"
        "  jobs a purpose-built tool would have done correctly."
    )

    # -- 3. tool_choice ----------------------------------------------------
    section("3. tool_choice modes")
    extract = [
        t("extract_metadata",
          "Extract document metadata: title, author, publication date, document type. "
          "Must run before any enrichment step.", ("path",)),
        t("enrich_with_citations",
          "Add citation records to an already-extracted document. Requires metadata.", ("path",)),
    ]
    q = "Process ./q3-report.pdf for me."

    bad('tool_choice = {"type": "auto"} when you REQUIRE a structured result')
    calls, text, sr = tools_called(c, extract, "You process documents.", q,
                                   {"type": "auto"})
    print(f"    tools called: {calls}   stop_reason={sr}")
    if not calls:
        note("The model answered conversationally instead of calling a tool. With 'auto' "
             "that is always a legal outcome, and any downstream parser expecting "
             "structured output just broke.")
    else:
        note("It happened to call a tool. 'auto' does not GUARANTEE it — which is the "
             "whole reason 'any' exists.")

    good('tool_choice = {"type": "any"} — the model must call some tool')
    calls, _, sr = tools_called(c, extract, "You process documents.", q, {"type": "any"})
    print(f"    tools called: {calls}   stop_reason={sr}")
    note("Guarantees a tool call, model still picks which. This is the answer when you "
         "have several extraction schemas and do not know the document type up front.")

    good('tool_choice = {"type": "tool", "name": "extract_metadata"} — forced')
    calls, _, sr = tools_called(c, extract, "You process documents.", q,
                                {"type": "tool", "name": "extract_metadata"})
    print(f"    tools called: {calls}   stop_reason={sr}")
    note("Guarantees THAT tool runs first. Use it to enforce an ordering prerequisite "
         "in a single-turn pipeline; handle the enrichment step in the follow-up turn, "
         "since forcing applies to this request only.")

    print(
        "\n  Summary:\n"
        '    auto              may return prose. Fine for chat, wrong for a pipeline.\n'
        '    any               guarantees a tool call; model chooses which.\n'
        '    {"type":"tool"}   guarantees a specific tool; use for ordering prerequisites.\n'
        "    disable_parallel_tool_use: true  can be added to any of them to cap at one call."
    )

    takeaway(
        "Scope tools per role. 18 tools where 4 belong degrades selection and invites misuse.",
        "Agents with off-role tools use them — a synthesis agent will start searching.",
        "Scoped cross-role tools (verify_fact) cover the common case; complex cases route back.",
        "Replace generic tools (fetch_url) with constrained ones (load_document) that validate.",
        "auto = may return text; any = must call something; {'type':'tool'} = must call THAT.",
        "Forced selection enforces ordering for ONE request — continue in follow-up turns.",
    )


if __name__ == "__main__":
    main()
