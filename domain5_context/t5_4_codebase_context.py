"""
Task 5.4 — Manage context effectively in large codebase exploration.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain5_context/t5_4_codebase_context.py

THE FOUR TECHNIQUES
-------------------
1. SUBAGENT DELEGATION — spawn a subagent to answer one specific question ("find
   all the test files", "trace the refund flow dependencies"). The subagent burns
   its own context on the verbose exploration; the main agent gets a summary and
   keeps its window for coordination.

2. SCRATCHPAD FILES — have the agent write key findings to a file as it goes, and
   consult that file later. This counteracts context degradation: in extended
   sessions models start giving inconsistent answers and referring vaguely to
   "typical patterns" instead of the specific classes they found an hour ago. The
   file does not degrade.

3. PHASE SUMMARIES — before moving to a new exploration phase, summarise the
   current one and inject that summary into the next phase's initial context,
   rather than carrying the whole transcript forward.

4. CRASH RECOVERY MANIFESTS — each agent exports its state to a known location;
   on resume the coordinator loads a manifest and re-injects it. Without this a
   crashed multi-hour exploration restarts from zero.

Plus /compact, which reduces context usage during an extended session when the
window fills with verbose discovery output.

WHY THIS ISN'T JUST "SAVE TOKENS"
---------------------------------
Context degradation is a CORRECTNESS problem, not only a cost one. The symptom
the exam names — the model referencing "typical patterns" rather than the
specific classes it discovered earlier — is the model losing its grip on findings
that are technically still in the transcript. Persisting them externally is what
makes long explorations reliable.
"""

import sys
import os
import shutil
import asyncio
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway, stream_messages

from claude_agent_sdk import (
    query, ClaudeAgentOptions, AgentDefinition,
    AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
)

WORKSPACE = None

# The exam says "the Task tool". The current SDK's canonical name for it is
# "Agent", with "Task" kept as a backward-compatible alias. Match both, or a
# trace that filters on "Task" alone reports zero delegations on a run that
# delegated correctly.
SPAWN_TOOL_NAMES = ("Task", "Agent")

# A codebase big enough that reading it all is visibly wasteful.
MODULES = ["auth", "billing", "catalog", "checkout", "inventory",
           "notifications", "reporting", "search", "shipping", "users"]


def build_workspace():
    root = tempfile.mkdtemp(prefix="ccar-explore-")
    for m in MODULES:
        d = os.path.join(root, "src", m)
        os.makedirs(d, exist_ok=True)
        for i in range(4):
            with open(os.path.join(d, f"{m}_{i}.py"), "w") as f:
                f.write(f'"""{m} module part {i}."""\n\n')
                f.write("\n".join(
                    f"def {m}_op_{i}_{j}(payload):\n"
                    f"    '''Handles {m} operation {i}.{j}.'''\n"
                    f"    return process_{m}(payload, step={j})\n"
                    for j in range(6)))
        os.makedirs(os.path.join(root, "tests", m), exist_ok=True)
        with open(os.path.join(root, "tests", m, f"test_{m}.py"), "w") as f:
            f.write(f"def test_{m}(): ...\n")

    # The one thing worth finding, buried deep.
    with open(os.path.join(root, "src", "billing", "billing_3.py"), "a") as f:
        f.write(
            "\n\nREFUND_CEILING_USD = 500  # SENTINEL: the refund approval ceiling\n"
            "def issue_refund(order, amount):\n"
            "    if amount > REFUND_CEILING_USD:\n"
            "        return escalate_for_approval(order, amount)\n"
            "    return post_credit(order, amount)\n"
        )
    return root


EXPLORER = AgentDefinition(
    description=(
        "Explores the codebase to answer ONE specific question. Give it a precise "
        "question and it returns a short structured answer. Its file reads stay in "
        "its own context, not yours."
    ),
    prompt=(
        "You answer exactly the one question you are given by exploring the "
        "codebase. Search and read as much as you need. Then return ONLY a short "
        "structured answer: the finding, the file:line where you found it, and "
        "anything adjacent that matters. Never paste file contents — the caller "
        "delegated to you precisely so those bytes stay out of their context."
    ),
    tools=["Read", "Grep", "Glob"],
    model="sonnet",
)


async def run(prompt, *, agents=None, allowed_tools=("Read", "Grep", "Glob"),
              system=None, max_turns=20):
    options = ClaudeAgentOptions(
        system_prompt=system or "You are a code exploration agent.",
        allowed_tools=list(allowed_tools),
        agents=agents,
        cwd=WORKSPACE,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
    )
    text, calls, cost = [], [], None
    async for message in stream_messages(prompt, options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    calls.append(block.name)
        elif isinstance(message, ResultMessage):
            cost = getattr(message, "total_cost_usd", None)
    return "\n".join(text).strip(), calls, cost


async def main():
    global WORKSPACE
    WORKSPACE = build_workspace()
    n_files = sum(len(f) for _, _, f in os.walk(WORKSPACE))

    banner("Large codebase exploration", "Task 5.4 — delegation, scratchpads, manifests")
    print(f"  workspace: {WORKSPACE}  ({n_files} files across {len(MODULES)} modules)")

    question = ("What is the refund approval ceiling in this codebase, where is it "
                "defined, and what happens when a refund exceeds it?")

    # -- 1. Direct exploration ---------------------------------------------
    section("1. Direct exploration — everything lands in the main context")
    bad("Main agent reads the codebase itself")
    a1, calls1, cost1 = await run(question)
    reads1 = calls1.count("Read")
    print(f"    tool calls: {len(calls1)} total ({reads1} Read, "
          f"{calls1.count('Grep')} Grep, {calls1.count('Glob')} Glob)")
    show("Answer", a1[:500])
    note(f"Every one of those {reads1} file reads is now in the main conversation and "
         "will be re-sent on every subsequent turn — including the ones that turned "
         "out to be irrelevant.")

    # -- 2. Delegated exploration -------------------------------------------
    section("2. Delegated exploration — verbose reads stay in the subagent")
    good("Main agent spawns an explorer subagent via the Task tool")
    a2, calls2, cost2 = await run(
        f"Use the explorer subagent to answer this, then report its finding: {question}",
        agents={"explorer": EXPLORER},
        allowed_tools=("Task", "Agent", "Read", "Grep", "Glob"),
        system=("You coordinate exploration. Delegate file-reading work to the "
                "explorer subagent rather than reading files yourself, so your own "
                "context stays free for coordination."),
    )
    tasks = sum(calls2.count(n) for n in SPAWN_TOOL_NAMES)
    reads2 = calls2.count("Read")
    print(f"    tool calls in MAIN context: {len(calls2)} "
          f"({tasks} spawn, {reads2} Read, {calls2.count('Grep')} Grep)")
    show("Answer", a2[:500])
    if tasks and reads2 < reads1:
        note(f"The main agent performed {reads2} reads instead of {reads1}. The "
             "exploration still happened — it happened somewhere else, and only the "
             "conclusion came back. That is the entire technique.")
    if cost1 and cost2:
        print(f"    cost: direct ${cost1:.4f}  |  delegated ${cost2:.4f}")
        note("Delegation is not always cheaper in total tokens — you pay for the "
             "subagent too. What it buys is main-context HEADROOM, which is what runs "
             "out first in a long multi-phase task.")

    # -- 3. Scratchpad -------------------------------------------------------
    section("3. Scratchpad files counteract context degradation")
    good("Agent records findings to a file as it explores")
    a3, calls3, _ = await run(
        "Explore the billing and checkout modules. As you go, append each key finding "
        "to FINDINGS.md in the working directory, one bullet per finding with the "
        "file:line. Then answer: what is the refund ceiling?",
        allowed_tools=("Read", "Grep", "Glob", "Write", "Edit"),
    )
    scratch = os.path.join(WORKSPACE, "FINDINGS.md")
    if os.path.exists(scratch):
        with open(scratch) as f:
            content = f.read()
        print(f"    FINDINGS.md written: {len(content.splitlines())} lines")
        show("Scratchpad contents", content[:600])
        note("This file survives compaction, summarisation, a new session, and the "
             "model losing the thread. Later phases consult it instead of relying on a "
             "transcript that is degrading.")
    else:
        note("No scratchpad written this run — re-run, or make the instruction more "
             "explicit about writing before answering.")

    # -- 4. Manifests --------------------------------------------------------
    section("4. Crash recovery manifests")
    manifest = {
        "run_id": "explore-2025-08-14-01",
        "phase": 2,
        "phases_complete": [
            {"phase": 1, "goal": "map module structure",
             "summary": f"{len(MODULES)} modules; billing and checkout are the only "
                        "ones touching money",
             "artifacts": ["FINDINGS.md"]},
        ],
        "agents": {
            "explorer": {"status": "idle", "last_question": "refund ceiling",
                         "state_file": "state/explorer.json"},
        },
        "open_questions": ["does inventory reserve before or after payment capture?"],
    }
    os.makedirs(os.path.join(WORKSPACE, "state"), exist_ok=True)
    import json
    with open(os.path.join(WORKSPACE, "state", "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    show("state/manifest.json", json.dumps(manifest, indent=2))
    print(
        "\n  On resume the coordinator loads this and injects it into each agent's\n"
        "  initial prompt. Recovery costs one file read instead of re-running phase 1.\n"
        "  Note the shape: completed phases are SUMMARISED, not replayed. A manifest\n"
        "  that stores the full transcript recreates the problem it exists to solve."
    )

    # -- 5. /compact ---------------------------------------------------------
    section("5. /compact")
    print(
        "  In an interactive Claude Code session, /compact condenses the conversation\n"
        "  when the window has filled with verbose discovery output. It is the manual\n"
        "  lever for the same problem the other four techniques address structurally.\n\n"
        "  Prefer the structural fixes: /compact is lossy and you do not control what\n"
        "  it drops. A scratchpad file and a phase summary are lossy in ways you CHOSE."
    )

    section("Which technique for which symptom")
    print(
        "    verbose exploration filling the window   -> delegate to a subagent\n"
        "    inconsistent answers late in a session   -> scratchpad file\n"
        "    moving between exploration phases        -> summarise, inject, drop transcript\n"
        "    long run that might crash                -> state manifests\n"
        "    already full, mid-session                -> /compact (last resort)"
    )

    takeaway(
        "Delegate verbose exploration; keep the main context for coordination.",
        "Context degradation is a CORRECTNESS problem, not just a cost problem.",
        "Symptom to recognise: vague 'typical patterns' instead of specific findings.",
        "Scratchpad files persist findings across context boundaries and sessions.",
        "Summarise each phase and inject the summary; don't carry the transcript.",
        "Manifests make a crashed multi-hour exploration resumable in one file read.",
        "/compact is the manual last resort, and you don't choose what it drops.",
    )

    shutil.rmtree(WORKSPACE, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
