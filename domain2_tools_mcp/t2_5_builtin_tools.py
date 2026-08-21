"""
Task 2.5 — Select and apply built-in tools (Read, Write, Edit, Bash, Grep, Glob).
Task 5.4 — Building codebase understanding incrementally.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain2_tools_mcp/t2_5_builtin_tools.py

THE SELECTION RULES
-------------------
  Grep   search file CONTENTS for a pattern — function names, error strings,
         import statements. "Who calls charge()?"
  Glob   match file PATHS by name pattern — "**/*.test.tsx", "src/**/*.py".
         "Where are the test files?"
  Read   load a whole file.
  Write  replace a whole file.
  Edit   targeted change via UNIQUE text matching.

The pairing that trips people up: Grep is content, Glob is path. A question that
sounds like "find the tests" is a Glob question; "find the callers" is a Grep
question. Reaching for Bash + `find`/`grep` instead is a smell — you lose the
structured results and the permission surface.

THE EDIT FALLBACK, WHICH IS ITS OWN EXAM ITEM
---------------------------------------------
Edit requires its target text to be UNIQUE in the file. When the same snippet
appears three times, Edit fails rather than guessing. The documented fallback is
Read the whole file, then Write it back with the change applied. This script
plants a genuinely non-unique string and lets you watch the failure and the
recovery.

INCREMENTAL EXPLORATION (Task 5.4)
----------------------------------
Do NOT read every file up front — that fills the context window with material
you mostly do not need and leaves no room for reasoning. Start with Grep to find
entry points, then Read to follow imports and trace the flow. To trace usage
across wrapper modules: first find all the exported names, then search for each
name.
"""

import sys
import os
import shutil
import asyncio
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway, stream_messages

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

WORKSPACE = None

# ---------------------------------------------------------------------------
# A small codebase with: an entry point, a wrapper module, and a repeated string
# that Edit cannot disambiguate.
# ---------------------------------------------------------------------------
TREE = {
    "src/api/routes.py": '''\
from src.billing.gateway import charge
from src.billing.wrappers import safe_charge

def post_payment(req):
    return charge(req["card"], req["amount"])

def post_payment_v2(req):
    return safe_charge(req["card"], req["amount"])
''',
    "src/billing/gateway.py": '''\
TIMEOUT = 30

def charge(card, amount):
    """Charge a card."""
    return _post("/charge", {"card": card, "amount": amount})

def refund(card, amount):
    """Refund a card."""
    return _post("/refund", {"card": card, "amount": amount})

def _post(path, body):
    # NOTE: this exact line appears three times in this file on purpose.
    log.info("calling gateway")
    return {"ok": True, "path": path}

def health():
    log.info("calling gateway")
    return {"ok": True}

def ping():
    log.info("calling gateway")
    return True
''',
    "src/billing/wrappers.py": '''\
from src.billing.gateway import charge

def safe_charge(card, amount):
    """Wrapper that re-exports charge under a different name."""
    return charge(card, amount)
''',
    "src/reports/monthly.py": '''\
from src.billing.wrappers import safe_charge

def rerun_failed(rows):
    return [safe_charge(r["card"], r["amount"]) for r in rows]
''',
    "tests/api/test_routes.py": "def test_post_payment(): ...\n",
    "tests/billing/test_gateway.py": "def test_charge(): ...\n",
    "tests/billing/test_wrappers.py": "def test_safe_charge(): ...\n",
}


def build_workspace() -> str:
    root = tempfile.mkdtemp(prefix="ccar-tools-")
    for rel, content in TREE.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    return root


async def run(prompt: str, tools, system="You are a code exploration agent. Be concise."):
    options = ClaudeAgentOptions(
        system_prompt=system,
        allowed_tools=list(tools),
        # Bash is explicitly denied. Without this the agent reaches for `find` and
        # `grep` out of habit, which muddies the Grep-vs-Glob comparison — and is
        # itself the anti-pattern this exercise is about: shelling out loses the
        # structured results and the permission surface the dedicated tools give you.
        disallowed_tools=["Bash"],
        cwd=WORKSPACE,
        max_turns=14,
        permission_mode="bypassPermissions",
    )
    text, calls, errors = [], [], []
    async for message in stream_messages(prompt, options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    calls.append((block.name, block.input))
        # Tool results arrive as UserMessage content; capture failures.
        for block in getattr(message, "content", []) or []:
            if isinstance(block, ToolResultBlock) and getattr(block, "is_error", False):
                errors.append(str(block.content)[:200])
    return "\n".join(text).strip(), calls, errors


async def main():
    global WORKSPACE
    WORKSPACE = build_workspace()

    banner("Built-in tool selection", "Task 2.5 / 5.4 — Grep vs Glob, and the Edit fallback")
    print(f"  workspace: {WORKSPACE}")

    # -- 1. Grep vs Glob ----------------------------------------------------
    section("1. Grep is for contents, Glob is for paths")

    _, calls_grep, _ = await run(
        "Find every call site of the charge() function in this codebase. List the files.",
        ["Grep", "Glob", "Read"],
    )
    used = [n for n, _ in calls_grep]
    print(f"  'find every call site of charge()' -> {used}")
    note("A CONTENT question. Grep is the right first move; Glob cannot see inside files.")

    _, calls_glob, _ = await run(
        "List every test file in this repository. Do not read their contents.",
        ["Grep", "Glob", "Read"],
    )
    used2 = [n for n, _ in calls_glob]
    print(f"  'list every test file'            -> {used2}")
    note("A PATH question. Glob matches tests/**/*.py directly; grepping for 'def test_' "
         "would work by accident and miss any test file that happens to be empty.")

    # -- 2. Tracing through a wrapper ---------------------------------------
    section("2. Tracing usage across a wrapper module (the two-step search)")
    answer, calls_trace, _ = await run(
        "charge() is re-exported through a wrapper module under a different name. "
        "Find every place the charge functionality is ultimately used, including "
        "through wrappers. Explain how you found them.",
        ["Grep", "Glob", "Read"],
    )
    print(f"  tool calls: {[n for n, _ in calls_trace]}")
    show("Answer", answer[:800])
    found_indirect = "monthly" in answer or "rerun_failed" in answer
    print(f"  found the indirect user (reports/monthly.py): {'YES' if found_indirect else 'NO'}")
    note("A single grep for 'charge' misses src/reports/monthly.py, which only ever "
         "says safe_charge. The exam's technique: first identify all exported names "
         "(charge, safe_charge), THEN search for each one.")

    # -- 3. Edit's uniqueness requirement -----------------------------------
    section("3. Edit requires unique anchor text")
    print('  src/billing/gateway.py contains log.info("calling gateway") three times.')

    bad("Editing a string that appears three times")
    answer_e, calls_e, errors_e = await run(
        'In src/billing/gateway.py, change the FIRST log.info("calling gateway") — the '
        'one inside _post — to log.info("calling gateway: %s", path). Leave the other '
        'two occurrences alone. Use the Edit tool.',
        ["Read", "Edit", "Write", "Grep"],
    )
    edit_calls = [n for n, _ in calls_e if n == "Edit"]
    print(f"  tool calls: {[n for n, _ in calls_e]}")
    if errors_e:
        print("  tool errors observed:")
        for e in errors_e[:2]:
            print(f"    {e}")
        note("Edit refused because the anchor text is ambiguous. This is a FEATURE — "
             "silently editing one of three identical lines would be a coin flip.")
    else:
        note("No hard error surfaced. A capable agent usually widens the anchor to "
             "include surrounding lines, which is the other correct recovery: make the "
             "match unique by including more context.")

    with open(os.path.join(WORKSPACE, "src/billing/gateway.py")) as f:
        after = f.read()
    changed = after.count('log.info("calling gateway: %s", path)')
    untouched = after.count('log.info("calling gateway")')
    print(f"  result: {changed} line(s) changed, {untouched} left untouched "
          f"(expected 1 and 2)")
    show("Recovery strategy the agent described", answer_e[:600])

    print(
        "\n  The two documented recoveries when Edit cannot find a unique match:\n"
        "    a. Widen the anchor — include the surrounding lines so the match is unique.\n"
        "    b. Read the whole file, then Write it back with the change applied.\n"
        "  (b) is the exam's stated fallback. It costs a full file round trip, which is\n"
        "  why (a) is worth trying first on large files."
    )

    # -- 4. Incremental exploration -----------------------------------------
    section("4. Incremental exploration beats reading everything")
    print(
        "  Anti-pattern: Glob '**/*.py' then Read all of them, then start reasoning.\n"
        "  On a real repository that exhausts the context window before any thinking\n"
        "  happens, and most of what you loaded was irrelevant.\n\n"
        "  Correct: Grep for the entry point -> Read that one file -> follow its imports\n"
        "  -> Read only what the trace actually reaches. You end up with a narrow,\n"
        "  relevant slice instead of a broad, mostly-noise one.\n\n"
        "  Domain 5 extends this: when the exploration output itself is verbose, push it\n"
        "  into a subagent and keep only the summary in the main context (t5_4)."
    )

    takeaway(
        "Grep = file CONTENTS. Glob = file PATHS. 'Find callers' vs 'find test files'.",
        "Edit needs a UNIQUE anchor. Non-unique -> widen the anchor, or Read + Write.",
        "Edit refusing to guess is correct behaviour, not a limitation.",
        "Trace through wrappers in two steps: find exported names, then search each name.",
        "Explore incrementally from an entry point. Never bulk-Read a codebase up front.",
    )

    shutil.rmtree(WORKSPACE, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
