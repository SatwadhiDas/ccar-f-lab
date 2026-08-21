"""
Task 3.6 — Integrate Claude Code into CI/CD pipelines.

Needs: your existing Claude Code login (uses the bundled `claude` CLI directly).
Run:   python domain3_claude_code/t3_6_ci_pipeline.py

This module shells out to the actual CLI rather than using the SDK, because the
exam tests the CLI FLAGS.

SAMPLE QUESTION 10
------------------
"Your pipeline runs `claude \"Analyze this pull request...\"` but the job hangs
indefinitely. Logs indicate Claude Code is waiting for interactive input."

  A. Add the -p flag.                             <-- correct
  B. Set CLAUDE_HEADLESS=true.                    (no such env var)
  C. Redirect stdin from /dev/null.               (a Unix workaround, not the fix)
  D. Add --batch.                                 (no such flag)

`claude` with no flags starts an INTERACTIVE session. In CI there is no terminal
to interact with, so it blocks until the job times out. `-p` / `--print` processes
the prompt, writes the result to stdout, and exits.

C deserves a moment: `< /dev/null` is not crazy — it does prevent a read from
blocking forever. But it is treating a symptom. The command is still in
interactive mode; you have just removed its input. Prefer the documented flag.

THE OTHER CI FLAGS
------------------
  --output-format json    machine-parseable envelope instead of prose
  --json-schema <schema>  constrain the result to your schema, so the pipeline can
                          post structured findings as inline PR comments

CI DESIGN POINTS THE EXAM ALSO TESTS
------------------------------------
  * CLAUDE.md is how you give CI-invoked Claude Code its project context —
    testing standards, fixture conventions, review criteria. This is the lever
    that turns low-value generated tests into useful ones.
  * Re-running a review after new commits: include the PRIOR findings in context
    and instruct Claude to report only new or still-unaddressed issues, or you
    will post the same comment on every push.
  * Generating tests: put the EXISTING test files in context so it does not
    propose scenarios the suite already covers.
  * SESSION CONTEXT ISOLATION: the same session that generated the code is worse
    at reviewing it than a fresh instance, because it still holds the reasoning
    that produced the code and is unlikely to question its own decisions.
"""

import sys
import os
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.join(HERE, "example_project")

# The bundled CLI that ships with claude-agent-sdk. In a real pipeline this is
# whatever `claude` resolves to on PATH.
try:
    import claude_agent_sdk
    CLI = os.path.join(os.path.dirname(claude_agent_sdk.__file__), "_bundled", "claude")
except Exception:
    CLI = "claude"
if not os.path.exists(CLI):
    CLI = "claude"

DIFF = '''\
--- a/src/api/payments.py
+++ b/src/api/payments.py
@@
 async def post_payment(request):
-    return {"ok": True}
+    amount = float(request["amount_dollars"])
+    total = amount * 1.0725
+    user = request["user_id"]
+    rows = db.execute("SELECT * FROM cards WHERE user_id = '" + user + "'")
+    return {"ok": True, "charged": round(total, 2)}
'''

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line_hint": {"type": "string"},
                    "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
                    "category": {"type": "string",
                                 "enum": ["bug", "security", "money", "other"]},
                    "issue": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                    # Task 4.4: recording WHICH construct triggered the finding lets you
                    # analyse dismissal patterns later instead of guessing at them.
                    "detected_pattern": {"type": "string"},
                },
                "required": ["file", "severity", "category", "issue",
                             "suggested_fix", "detected_pattern"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

REVIEW_PROMPT = f"""\
Review this diff. Report bugs, security issues, and incorrect money handling.
Skip formatting and naming preferences.

For each finding set detected_pattern to the code construct that triggered it
(e.g. "float_arithmetic_on_currency", "string_concatenation_in_sql").

{DIFF}
"""


def run_cli(args, timeout=300, stdin_input=None):
    try:
        proc = subprocess.run(
            [CLI] + args, capture_output=True, text=True, timeout=timeout,
            cwd=PROJECT, input=stdin_input,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return None, "", f"TIMED OUT after {timeout}s"


def main():
    banner("Claude Code in CI/CD", "Task 3.6 — this is exam Sample Question 10")
    print(f"  CLI: {CLI}")
    print(f"  cwd: {os.path.relpath(PROJECT)}  (so CLAUDE.md is picked up)")

    # -- 1. -p ---------------------------------------------------------------
    section("1. Non-interactive mode")
    bad("claude \"<prompt>\"   — no -p")
    print("  Not executed here: without a TTY this either blocks until the CI job's\n"
          "  timeout or falls back in a way that hides the real bug. That indefinite\n"
          "  hang IS the symptom in Sample Question 10.")

    good("claude -p \"<prompt>\"")
    rc, out, err = run_cli(["-p", "Reply with exactly: CI_OK"])
    print(f"  exit={rc}  stdout={out.strip()[:80]!r}")
    note("-p / --print processes the prompt, writes to stdout, exits. That is the "
         "documented non-interactive mode. CLAUDE_HEADLESS and --batch do not exist; "
         "`< /dev/null` treats the symptom rather than the cause.")

    # -- 2. --output-format json --------------------------------------------
    section("2. Machine-parseable output")
    rc, out, err = run_cli(["-p", "--output-format", "json", "Reply with exactly: CI_OK"])
    print(f"  exit={rc}")
    try:
        envelope = json.loads(out)
        print(f"  parsed envelope keys: {sorted(envelope)[:10]}")
        print(f"  result field: {str(envelope.get('result'))[:60]!r}")
        for k in ["total_cost_usd", "num_turns", "session_id", "is_error"]:
            if k in envelope:
                print(f"  {k}: {envelope[k]}")
        note("The envelope carries cost, turn count and session id alongside the "
             "result — everything a pipeline needs for budgeting and for correlating "
             "a failure back to a session.")
    except json.JSONDecodeError:
        print(f"  raw stdout: {out[:300]}")

    # -- 3. --json-schema ----------------------------------------------------
    section("3. Structured findings with --json-schema")
    good("claude -p --output-format json --json-schema '<schema>'")
    rc, out, err = run_cli(
        ["-p", "--output-format", "json", "--json-schema", json.dumps(FINDINGS_SCHEMA),
         REVIEW_PROMPT],
        timeout=420,
    )
    print(f"  exit={rc}")
    findings = []
    try:
        envelope = json.loads(out)
        result = envelope.get("result")
        payload = json.loads(result) if isinstance(result, str) else result
        findings = (payload or {}).get("findings", [])
    except Exception as exc:
        print(f"  could not parse: {exc}")
        show("stdout", out[:600])
        if err.strip():
            show("stderr", err[:400])

    if findings:
        print(f"  {len(findings)} structured finding(s):\n")
        for f in findings:
            print(f"    [{f.get('severity','?'):8s}] {f.get('category','?'):9s} "
                  f"{f.get('issue','')[:64]}")
            print(f"               pattern: {f.get('detected_pattern')}")
        print(
            "\n  This is directly postable as inline PR comments — no regex over prose,\n"
            "  no 'the model changed its heading format and broke the parser' on a\n"
            "  Friday. The schema is the contract between the model and the pipeline."
        )
        cats = {f.get("category") for f in findings}
        if "security" in cats and "money" in cats:
            note("It caught both the SQL string concatenation and the float arithmetic "
                 "on currency. The float rule comes from example_project/CLAUDE.md — "
                 "that is CLAUDE.md supplying project context to a CI invocation.")

    # -- 4. Design points ----------------------------------------------------
    section("4. CI design points")
    print(
        "  RE-RUNNING AFTER NEW COMMITS\n"
        "    Include the prior findings in context and instruct: 'report only new or\n"
        "    still-unaddressed issues.' Without it, every push re-posts the same\n"
        "    comments, developers learn to ignore the bot, and the tool is dead.\n\n"
        "  GENERATING TESTS\n"
        "    Put the EXISTING test files in context so it does not re-propose covered\n"
        "    scenarios. Then document, in CLAUDE.md, what a valuable test looks like\n"
        "    here and which fixtures exist — see example_project/standards/\n"
        "    testing-standards.md. Without that, you get volume: getter tests, mock\n"
        "    call-count assertions, and three variants of the happy path.\n\n"
        "  SESSION CONTEXT ISOLATION\n"
        "    Do NOT have the session that wrote the code review the code. It still\n"
        "    holds the reasoning that produced it and is measurably less likely to\n"
        "    question its own decisions. Spawn a SEPARATE instance with no prior\n"
        "    context — the exam is explicit that this beats both self-review\n"
        "    instructions and extended thinking (Task 4.6).\n\n"
        "  A minimal GitHub Actions step:\n\n"
        "      - name: Claude review\n"
        "        run: |\n"
        "          claude -p \\\n"
        "            --output-format json \\\n"
        "            --json-schema \"$(cat .github/review-schema.json)\" \\\n"
        "            \"$(git diff origin/main...HEAD)\" > findings.json\n"
        "          python .github/post_comments.py findings.json\n"
    )

    takeaway(
        "-p / --print is THE non-interactive flag. CLAUDE_HEADLESS and --batch don't exist.",
        "--output-format json + --json-schema = parseable findings for inline PR comments.",
        "CLAUDE.md supplies project context (standards, fixtures, criteria) to CI runs.",
        "Re-runs must receive prior findings + 'only new or unaddressed' or they spam.",
        "Test generation must receive existing tests or it duplicates coverage.",
        "Never let the generating session review its own code — use a fresh instance.",
    )


if __name__ == "__main__":
    main()
