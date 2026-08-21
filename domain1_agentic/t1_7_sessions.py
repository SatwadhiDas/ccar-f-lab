"""
Task 1.7 — Manage session state, resumption, and forking.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain1_agentic/t1_7_sessions.py

WHAT THE EXAM TESTS
-------------------
  resume        -> continue a specific prior conversation. CLI: --resume <id>.
                   SDK: ClaudeAgentOptions(resume=session_id).
  fork_session  -> branch from a shared analysis baseline so two divergent
                   approaches can be explored without contaminating each other.
                   SDK: ClaudeAgentOptions(resume=id, fork_session=True).
  stale results -> when the files changed since the prior session, resuming with
                   stale tool results is WORSE than starting fresh with an
                   injected structured summary.

The decision rule the exam wants:

    prior context mostly still valid   -> resume
    prior tool results now stale       -> start fresh + inject a summary
    same baseline, divergent options   -> fork

And the refinement: if only a couple of files changed, you do not have to choose
between "resume blind" and "start over". Resume and TELL the agent exactly what
changed, so it re-reads those files and keeps everything else. Targeted
re-analysis beats full re-exploration.

This script does all four against a real temporary workspace.
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
    ResultMessage,
)

WORKSPACE = None

FILE_V1 = '''\
# billing.py  (version 1)
RETRY_LIMIT = 3

def charge(card, amount_usd):
    """Charge a card. Retries up to RETRY_LIMIT times on transient failures."""
    for attempt in range(RETRY_LIMIT):
        ok = _gateway_charge(card, amount_usd)
        if ok:
            return {"status": "charged", "attempts": attempt + 1}
    return {"status": "failed", "attempts": RETRY_LIMIT}

def _gateway_charge(card, amount_usd):
    raise NotImplementedError
'''

FILE_V2 = '''\
# billing.py  (version 2 — rewritten since the last session)
IDEMPOTENCY_TTL_SECONDS = 900

def charge(card, amount_usd, idempotency_key):
    """Charge a card exactly once. Retry logic was REMOVED and replaced by
    idempotency-key deduplication at the gateway boundary."""
    if _seen(idempotency_key):
        return {"status": "duplicate_suppressed"}
    return _gateway_charge(card, amount_usd, idempotency_key)

def _seen(key): ...
def _gateway_charge(card, amount_usd, idempotency_key): ...
'''


async def run(prompt: str, *, resume=None, fork=False, cwd=None, max_turns=6,
              tools=("Read", "Grep", "Glob")):
    """Run one agent turn; return (text, session_id)."""
    options = ClaudeAgentOptions(
        system_prompt=(
            "You are a code analysis agent. Be concise — three sentences maximum "
            "unless asked for more."
        ),
        allowed_tools=list(tools),
        cwd=cwd or WORKSPACE,
        resume=resume,
        fork_session=fork,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
    )
    text, session_id = [], None
    async for message in stream_messages(prompt, options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text.append(block.text)
        elif isinstance(message, ResultMessage):
            session_id = getattr(message, "session_id", None)
    return "\n".join(text).strip(), session_id


async def main():
    global WORKSPACE
    WORKSPACE = tempfile.mkdtemp(prefix="ccar-session-")
    billing = os.path.join(WORKSPACE, "billing.py")
    with open(billing, "w") as f:
        f.write(FILE_V1)

    banner("Session resumption and forking",
           "Task 1.7 — resume, fork_session, and the stale-results decision")
    print(f"  workspace: {WORKSPACE}")

    # -- 1. Baseline session ------------------------------------------------
    section("1. Establish a baseline session")
    baseline_text, baseline_id = await run(
        "Read billing.py and summarise how it handles payment failure. "
        "Name the specific constant it uses."
    )
    show("Baseline analysis", baseline_text)
    print(f"  session_id: {baseline_id}")

    if not baseline_id:
        note("No session_id returned — cannot demonstrate resume/fork. Stopping.")
        return

    # -- 2. Resume ----------------------------------------------------------
    section("2. Resume that session (context should carry over)")
    good("ClaudeAgentOptions(resume=<session_id>)")
    resumed_text, _ = await run(
        "Without reading any files again, what did you just tell me the retry "
        "constant was called and what was its value?",
        resume=baseline_id,
    )
    show("Resumed answer", resumed_text)
    remembered = "RETRY_LIMIT" in resumed_text
    print(f"  carried prior context: {'YES' if remembered else 'NO'}")
    note("Resume continues one specific named conversation. In the CLI this is "
         "`claude --resume <session-name>`, which is how you keep a long "
         "investigation alive across work sessions.")

    # -- 3. Fork ------------------------------------------------------------
    section("3. Fork the baseline into two divergent branches")
    good("ClaudeAgentOptions(resume=<id>, fork_session=True) — twice")
    branch_a, id_a = await run(
        "Building on your analysis: propose approach A — keep retries but add "
        "exponential backoff. Two sentences. Do not consider any other approach.",
        resume=baseline_id, fork=True,
    )
    branch_b, id_b = await run(
        "Building on your analysis: propose approach B — remove retries entirely "
        "and use idempotency keys. Two sentences. Do not consider any other approach.",
        resume=baseline_id, fork=True,
    )
    show("Branch A (backoff)", branch_a)
    show("Branch B (idempotency)", branch_b)
    print(f"  baseline: {baseline_id}")
    print(f"  branch A: {id_a}")
    print(f"  branch B: {id_b}")
    distinct = len({baseline_id, id_a, id_b}) == 3
    print(f"  three distinct sessions: {'YES' if distinct else 'NO'}")
    note("Both branches inherited the SAME baseline analysis, so you are not paying "
         "to re-derive it twice, and neither branch can see the other's reasoning. "
         "That isolation is the point — without it, whichever approach you explored "
         "first anchors the second.")

    # -- 4. Stale results ---------------------------------------------------
    section("4. The file changes underneath a session")
    with open(billing, "w") as f:
        f.write(FILE_V2)
    print("  billing.py has been rewritten: retries removed, idempotency keys added.")

    def describes_v2(text: str) -> bool:
        """
        Detect whether the answer reflects the CURRENT file.

        Deliberately keyed on identifiers that exist only in v2. A naive substring
        check for "idempotency" gives a false positive on v1 answers, because a
        correct description of v1 says "there is NO idempotency key" — the word is
        present, the meaning is inverted. Worth internalising generally: when you
        grade model output by keyword, negation is the first thing that breaks it.
        """
        low = text.lower()
        return "idempotency_ttl_seconds" in low or "duplicate_suppressed" in low

    # 4a. The failure in its pure form: the agent answers from its cached view.
    bad("4a. Resuming and answering from context (agent has no reason to re-read)")
    stale_text, _ = await run(
        "From what you already know about billing.py, what is the retry limit and "
        "how does the module handle duplicate charges?",
        resume=baseline_id,
        tools=(),  # no file access: this is what relying on stale tool results looks like
    )
    show("Answer", stale_text)
    print(f"  describes the CURRENT file (v2): {'YES' if describes_v2(stale_text) else 'NO'}")
    note("Confidently wrong, and nothing errored. The cached read of version 1 is still "
         "sitting in the transcript, and the agent has no signal that the world moved.")

    # 4b. The same resume, with file access. Often self-corrects — say so honestly.
    section("4b. The same blind resume, but with Read access")
    recheck_text, _ = await run(
        "What is the retry limit in billing.py, and how does the module handle "
        "duplicate charges?",
        resume=baseline_id,
    )
    show("Answer", recheck_text)
    selfcorrected = describes_v2(recheck_text)
    print(f"  re-read the file unprompted: {'YES' if selfcorrected else 'NO'}")
    if selfcorrected:
        note("The agent re-read on its own this time. That is good behaviour — and it is "
             "exactly what makes stale context dangerous in production: the failure is "
             "INTERMITTENT. It depends on whether the model happens to doubt its cache, "
             "which you cannot rely on and cannot see when it goes wrong.")
    else:
        note("It answered from cache even with file access available — the failure mode "
             "in 4a, reproduced under realistic conditions.")

    good("4c. Resuming WITH an explicit statement of what changed")
    informed_text, _ = await run(
        "Note: billing.py has been rewritten since your last read. Re-read that file "
        "before answering — your cached view of it is stale. Everything else you "
        "analysed is unchanged. Now: what is the retry limit, and how are duplicate "
        "charges handled?",
        resume=baseline_id,
    )
    show("Answer after targeted re-read", informed_text)
    print(f"  picked up the rewrite: {'YES' if describes_v2(informed_text) else 'NO'}")
    note("Targeted re-analysis: the agent re-read the one file you named and kept the "
         "rest of its context. Cheaper than starting over, and — unlike 4b — correct "
         "by construction rather than by luck.")

    section("The decision rule")
    print(
        "  resume                      prior context is MOSTLY still valid\n"
        "  resume + 'X changed, re-read it'  a few known files moved (targeted re-analysis)\n"
        "  fork_session                one shared baseline, several divergent options\n"
        "  fresh session + injected summary  prior TOOL RESULTS are broadly stale\n\n"
        "  That last row is the one people get wrong. When most of the cached reads no\n"
        "  longer reflect reality, resuming drags the whole stale transcript along with\n"
        "  it and the agent cannot tell which parts still hold. Starting fresh with a\n"
        "  hand-written structured summary of the durable conclusions is more reliable\n"
        "  than resuming and hoping the agent re-verifies the right things."
    )

    takeaway(
        "resume = continue one named conversation (--resume / options.resume).",
        "fork_session = branch a shared baseline into isolated parallel explorations.",
        "Stale tool results fail SILENTLY as confident answers about a file that changed.",
        "Tell a resumed session exactly which files moved — targeted re-read beats re-exploration.",
        "Broadly stale context: start fresh with an injected summary, don't resume.",
    )

    shutil.rmtree(WORKSPACE, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
