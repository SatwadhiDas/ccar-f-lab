"""
Task 1.2 — Orchestrate multi-agent systems with coordinator-subagent patterns.
Task 1.3 — Configure subagent invocation, context passing, and spawning.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain1_agentic/t1_2_coordinator_subagents.py

WHAT THE EXAM TESTS
-------------------
1. The Task tool is the spawn mechanism, and `allowedTools` on the COORDINATOR
   must include "Task" or it physically cannot delegate. In the Python SDK that
   is `ClaudeAgentOptions(allowed_tools=[..., "Task"])`.

   ^ That is the exam's answer and what you should select. See the SPAWN_TOOL_NAMES
   note below for how the current SDK actually behaves — the tool has been renamed
   to "Agent" with "Task" as an alias, and programmatically-defined subagents do
   not strictly require the allowlist entry. Know the exam answer; know the drift.

2. Subagents run in ISOLATED context. They do not inherit the coordinator's
   conversation history, and they do not share memory between invocations. Any
   finding a subagent needs must be written into its prompt.

3. Hub-and-spoke: every subagent-to-subagent message routes through the
   coordinator. Subagents never talk to each other. That is what buys you
   observability, consistent error handling, and controlled information flow.

4. Parallel spawning means emitting MULTIPLE Task calls in a SINGLE coordinator
   response — not one per turn across several turns.

5. Sample Question 7 in the exam guide: reports covering only visual arts came
   from the COORDINATOR decomposing "creative industries" too narrowly. The
   subagents each executed correctly. Blame the decomposition, not the workers.

6. Coordinator prompts should specify goals and quality criteria, not
   step-by-step procedure, so subagents can adapt.

This script builds a research coordinator with three specialised subagents and
prints the delegation trace so you can watch the hub-and-spoke pattern happen.
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway, MODEL, stream_messages

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AgentDefinition,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ResultMessage,
)

# ---------------------------------------------------------------------------
# API DRIFT — worth knowing, and verified against the installed SDK.
#
# The exam guide says "the Task tool" and "allowedTools must include 'Task'".
# In the current SDK the spawn tool's canonical name is "Agent"; "Task" is kept
# as a backward-compatible ALIAS, so a `Task` call still routes to the same tool.
# Two practical consequences:
#
#   * If you instrument a trace by matching block.name == "Task", you will record
#     ZERO delegations on a run that delegated perfectly well. That is a
#     monitoring bug that looks exactly like a broken coordinator.
#   * Programmatic agents passed via ClaudeAgentOptions(agents={...}) are sent in
#     the initialize request, so no allowed_tools entry is strictly required to
#     enable spawning. Listing it still matters when you are running with a
#     restrictive allowlist, and the parameterised form "Agent(researcher)"
#     narrows WHICH subagent_types may be used.
#
# On the exam, answer "Task" — that is what the guide tests. In code, match both.
SPAWN_TOOL_NAMES = ("Task", "Agent")


# ---------------------------------------------------------------------------
# Subagent definitions
# ---------------------------------------------------------------------------
# Note the field names: AgentDefinition uses camelCase for `disallowedTools`,
# `mcpServers`, `maxTurns` — a detail the exam is fond of. `tools` is the
# allowlist for THIS subagent, and it is how you implement Task 2.3's scoped
# tool access: give each subagent only what its role needs.
#
# Crucially, none of these subagents gets "Task". One level of delegation only —
# the coordinator delegates, workers do not.
SUBAGENTS = {
    "web-researcher": AgentDefinition(
        description=(
            "Searches the web for a single, well-scoped sub-question and reports "
            "findings with a source URL for every claim. Spawn several in parallel, "
            "one per distinct subtopic. Give it the exact question and the source "
            "types you want covered."
        ),
        prompt=(
            "You research exactly the one question you are given. Search, read, and "
            "report concise findings. For EVERY claim, output a structured entry with: "
            "claim, evidence excerpt, source URL, and publication date. Never merge "
            "claims from different sources into one entry — downstream agents need the "
            "claim-to-source mapping preserved. If you cannot find a source for a "
            "claim, say so explicitly rather than dropping it."
        ),
        tools=["WebSearch", "WebFetch"],  # scoped: no file writes, no Task
        model="sonnet",
    ),
    "doc-analyst": AgentDefinition(
        description=(
            "Analyses documents already on disk and extracts structured data points. "
            "Give it explicit file paths and the fields to extract. Does not search "
            "the web."
        ),
        prompt=(
            "You analyse the specific documents you are pointed at. Extract the "
            "requested data points as structured entries with the document name and "
            "page/section for each. If two documents give conflicting values, report "
            "BOTH with their sources and flag the conflict — do not silently pick one."
        ),
        tools=["Read", "Grep", "Glob"],
        model="sonnet",
    ),
    "synthesizer": AgentDefinition(
        description=(
            "Combines findings from other agents into a cited report. Give it the "
            "complete findings in its prompt — it cannot see other agents' work. "
            "Has a scoped verify_fact capability for simple checks only."
        ),
        prompt=(
            "You synthesise findings that are provided to you in full in your prompt. "
            "You cannot see any other agent's conversation. Preserve every "
            "claim-to-source mapping you are given. Structure the output with an "
            "explicit separation between well-established findings and contested ones. "
            "Where sources conflict, present both values with attribution rather than "
            "choosing. Flag any topic area where you received no findings as a "
            "coverage gap."
        ),
        # Scoped cross-role tool (exam Sample Question 9): the synthesis agent gets a
        # narrow WebFetch for cheap fact-checks (the 85% case) rather than the full
        # search toolset, so complex verification still routes back through the
        # coordinator. This is least-privilege, not convenience.
        tools=["WebFetch"],
        model="sonnet",
    ),
}


COORDINATOR_PROMPT_GOOD = """\
You are a research coordinator. You decompose a research topic, delegate to
specialist subagents, and assemble their findings.

DECOMPOSITION
Before delegating, enumerate the full breadth of the topic. A topic like
"creative industries" spans music, writing, film, visual art, design, games, and
performance — decomposing it into three visual-art subtopics would silently drop
most of the domain. State your subtopic list and justify that it covers the
topic before you spawn anything.

DELEGATION
- Partition scope so subagents do not duplicate each other. Assign each a
  distinct subtopic AND distinct source types.
- Spawn subagents in PARALLEL: emit all of your Task calls in a single response,
  not one per turn.
- Each subagent has isolated context and can see nothing you have done. Put every
  fact it needs directly in its prompt.
- Route everything through yourself. Subagents never communicate with each other.

QUALITY BAR (not a procedure — adapt how you meet it)
- Every claim in the final report carries a source.
- Conflicting figures from credible sources are reported with both values and
  attribution, never silently reconciled.
- After synthesis, evaluate the result for coverage gaps. If a subtopic came back
  thin, re-delegate with a targeted follow-up query and re-synthesise. Iterate
  until coverage is sufficient.
"""

COORDINATOR_PROMPT_BAD = """\
You are a research coordinator. Follow these steps exactly:
STEP 1: Call the web-researcher subagent.
STEP 2: Call the doc-analyst subagent.
STEP 3: Call the synthesizer subagent.
STEP 4: Return the synthesizer's output.
"""


async def run_coordinator(prompt: str, system_prompt: str, label: str):
    """Run one coordinator turn and print the delegation trace."""
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        agents=SUBAGENTS,
        # THE line the exam asks about. Without "Task" in allowed_tools the
        # coordinator has no spawn mechanism and will silently do the work itself.
        allowed_tools=["Task", "Agent", "WebSearch", "WebFetch", "Read", "Grep", "Glob"],
        max_turns=8,
        permission_mode="bypassPermissions",  # unattended demo
    )

    spawns = []          # (subagent_type, prompt_prefix)
    parallel_batches = []  # how many Task calls appeared in each single response
    final_text = []

    async for message in stream_messages(prompt, options):
        if isinstance(message, AssistantMessage):
            task_calls_this_turn = 0
            for block in message.content:
                if isinstance(block, ToolUseBlock) and block.name in SPAWN_TOOL_NAMES:
                    task_calls_this_turn += 1
                    spawns.append(
                        (
                            block.input.get("subagent_type", "?"),
                            str(block.input.get("prompt", ""))[:150].replace("\n", " "),
                        )
                    )
                elif isinstance(block, TextBlock):
                    final_text.append(block.text)
            if task_calls_this_turn:
                parallel_batches.append(task_calls_this_turn)
        elif isinstance(message, ResultMessage):
            cost = getattr(message, "total_cost_usd", None)
            if cost:
                print(f"    [{label}] session cost: ${cost:.4f}")

    return spawns, parallel_batches, "\n".join(final_text)


async def main():
    banner(
        "Coordinator / subagent orchestration",
        "Tasks 1.2 & 1.3 — hub-and-spoke, isolated context, parallel Task calls",
    )

    topic = (
        "Research the impact of AI on creative industries. Produce a short, cited "
        "briefing. Delegate the research; do not do it all yourself."
    )

    good("Coordinator prompted with goals + quality criteria")
    spawns, batches, text = await run_coordinator(
        topic, COORDINATOR_PROMPT_GOOD, "good"
    )

    section("Delegation trace (hub-and-spoke)")
    if not spawns:
        note("No spawn calls (Task/Agent) were emitted this run. Re-run — routing "
             "varies. If it NEVER delegates, check that the coordinator can reach the "
             "spawn tool and that the request is big enough to be worth splitting.")
    for i, (agent_type, prompt_head) in enumerate(spawns, 1):
        print(f"  {i}. coordinator --spawn--> {agent_type}")
        print(f"       prompt begins: {prompt_head!r}")

    section("Parallelism check")
    if batches:
        print(f"  spawn calls per coordinator response: {batches}")
        if max(batches) > 1:
            note(f"A single response emitted {max(batches)} spawn calls — this is the "
                 "parallel spawn the exam asks about. Subagents run concurrently.")
        else:
            note("Every response emitted one spawn call, i.e. sequential spawning. "
                 "Latency is the sum of subagent runtimes rather than the max.")

    section("Coverage check (Sample Question 7)")
    covered = {
        k: k in text.lower()
        for k in ["music", "writing", "film", "visual", "design", "game"]
    }
    print(f"  Subdomains referenced in the coordinator's output: {covered}")
    missing = [k for k, v in covered.items() if not v]
    if missing:
        note(f"Thin on: {', '.join(missing)}. If the final report is systematically "
             "missing subdomains while every subagent succeeded, the root cause is the "
             "COORDINATOR'S DECOMPOSITION — not the search agent, not the analyst, and "
             "not the synthesizer. That is the exam's answer.")

    show("Coordinator output (truncated)", text[:1200])

    bad("Coordinator prompted with a fixed step-by-step pipeline")
    print(
        "  The COORDINATOR_PROMPT_BAD constant in this file always routes through the\n"
        "  full pipeline regardless of the query. Two failures the exam cares about:\n"
        "    - A simple factual query still pays for three subagent round trips.\n"
        "    - Subagents cannot adapt, because they were handed a procedure rather\n"
        "      than a goal and a quality bar.\n"
        "  The fix is dynamic selection: the coordinator analyses the query and chooses\n"
        "  which subagents to invoke."
    )

    takeaway(
        "allowed_tools must include 'Task' or the coordinator cannot spawn at all.",
        "Subagents inherit NOTHING. Put every needed finding in the subagent's prompt.",
        "Parallel = multiple Task calls in ONE response, not one per turn.",
        "All routing through the coordinator; subagents never talk to each other.",
        "Systematic coverage gaps with healthy subagents == bad coordinator decomposition.",
        "Prompt coordinators with goals + quality criteria, not STEP 1 / STEP 2 / STEP 3.",
    )


if __name__ == "__main__":
    asyncio.run(main())
