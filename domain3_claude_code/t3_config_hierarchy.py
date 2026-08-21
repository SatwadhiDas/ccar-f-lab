"""
Task 3.1 — CLAUDE.md hierarchy, scoping, and modular organization.
Task 3.2 — Custom slash commands and skills.
Task 3.3 — Path-specific rules for conditional convention loading.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain3_claude_code/t3_config_hierarchy.py

The configuration itself lives in ./example_project/ — read those files, they are
the study material. This script verifies them and then proves the loading
behaviour with a live agent.

THE THREE-TIER HIERARCHY
------------------------
  ~/.claude/CLAUDE.md          USER level.      Your machine only. NOT shared.
  <repo>/CLAUDE.md             PROJECT level.   Committed. Everyone gets it.
  <repo>/sub/dir/CLAUDE.md     DIRECTORY level. Loads within that subtree.

The diagnostic question the exam asks: "a new team member isn't receiving the
instructions." The answer is essentially always that the instructions are
user-scoped and therefore never travelled with the repository. `/memory` is the
command that shows you which memory files are actually loaded — reach for it
whenever behaviour differs between two people or two sessions.

RULES vs DIRECTORY CLAUDE.md — Sample Question 6
------------------------------------------------
Test files sit next to the code they test, so they are scattered through every
directory. A directory-level CLAUDE.md is DIRECTORY-BOUND and cannot express
"every test file anywhere". A `.claude/rules/` file with
`paths: ["**/*.test.tsx"]` can, and it loads only when a matching file is being
edited — so it is both more expressive AND cheaper.

  Option B (one big CLAUDE.md with headed sections) relies on the model INFERRING
  which section applies. Explicit path matching beats inference.
  Option C (skills) requires invocation, which contradicts "automatically".
  Option D (per-directory CLAUDE.md) cannot span directories.

SKILLS vs CLAUDE.md
-------------------
  CLAUDE.md   always loaded, every request. Universal standards. You pay for it
              on every single interaction, which is why it must stay small.
  Skill       on-demand, task-specific workflows. Free until invoked.
"""

import sys
import os
import re
import asyncio
from pathlib import PurePath

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway, stream_messages

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.join(HERE, "example_project")


def parse_frontmatter(path):
    """Return (frontmatter_dict, body). Deliberately minimal — no yaml dependency."""
    with open(path) as f:
        text = f.read()
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    data = {}
    for line in fm.strip().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip('"\'') for x in v[1:-1].split(",") if x.strip()]
        data[k.strip()] = v
    return data, body


def _glob_regex(pattern: str) -> re.Pattern:
    """Fallback glob->regex with correct `**` semantics (Python < 3.13)."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"      # ** matches ZERO or more directories
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"         # a single * never crosses a path separator
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def path_matches(path: str, pattern: str) -> bool:
    """
    Does `path` match a rule's glob?

    Do NOT use fnmatch here. fnmatch has no concept of `**` and lets a plain `*`
    cross directory separators, so `src/api/**/*.py` fails to match
    `src/api/payments.py` (it demands at least one intermediate directory) while
    `**/*.test.tsx` fails to match a test file at the repo root. Both are wrong in
    the direction that makes path-scoped rules look broken when they are fine.

    PurePath.full_match (3.13+) implements the real semantics; the regex fallback
    reproduces them for older interpreters.
    """
    try:
        return PurePath(path).full_match(pattern)
    except AttributeError:
        return bool(_glob_regex(pattern).match(path))


async def ask_in_project(prompt: str, cwd: str) -> str:
    options = ClaudeAgentOptions(
        # setting_sources=["project"] makes the SDK load the repo's CLAUDE.md,
        # rules, commands and skills. Without it the agent starts with no project
        # configuration at all — which is itself worth knowing when an SDK-driven
        # agent mysteriously ignores your conventions.
        setting_sources=["project"],
        allowed_tools=["Read", "Grep", "Glob"],
        cwd=cwd,
        max_turns=4,
        permission_mode="bypassPermissions",
    )
    out = []
    async for message in stream_messages(prompt, options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    out.append(block.text)
    return "\n".join(out).strip()


async def main():
    banner("Claude Code configuration hierarchy",
           "Tasks 3.1 / 3.2 / 3.3 — CLAUDE.md, rules, commands, skills")
    print(f"  example project: {os.path.relpath(PROJECT)}")

    # -- 1. Hierarchy ------------------------------------------------------
    section("1. The three tiers, on disk")
    for label, rel in [
        ("PROJECT  (committed, shared)", "CLAUDE.md"),
        ("DIRECTORY (subtree only)", "src/api/CLAUDE.md"),
    ]:
        p = os.path.join(PROJECT, rel)
        print(f"  [{'OK' if os.path.exists(p) else '--'}] {label:32s} {rel}")
    print(f"  [--] USER     (your machine, NOT shared)  ~/.claude/CLAUDE.md")
    note("The user tier is the one that causes the exam's bug. Anything a teammate "
         "needs must be at project level or it does not travel with the repo.")

    # -- 2. @import --------------------------------------------------------
    section("2. @import keeps CLAUDE.md modular")
    with open(os.path.join(PROJECT, "CLAUDE.md")) as f:
        root = f.read()
    imports = re.findall(r"^@(\S+)", root, re.M)
    print(f"  root CLAUDE.md is {len(root.splitlines())} lines and imports: {imports}")
    for imp in imports:
        p = os.path.join(PROJECT, imp)
        print(f"    [{'OK' if os.path.exists(p) else 'MISSING'}] {imp}")
    note("Root CLAUDE.md is loaded on EVERY request, so its length is a per-request "
         "tax. @import lets each package pull in the standards its maintainers judge "
         "relevant instead of everyone carrying every rule.")

    # -- 3. Path-scoped rules ---------------------------------------------
    section("3. Path-scoped rules (Sample Question 6)")
    rules_dir = os.path.join(PROJECT, ".claude", "rules")
    rules = []
    for name in sorted(os.listdir(rules_dir)):
        fm, _ = parse_frontmatter(os.path.join(rules_dir, name))
        rules.append((name, fm.get("paths", [])))
        print(f"  {name:24s} paths: {fm.get('paths')}")

    print("\n  Which rules load for which file:")
    for target in [
        "src/components/Button.test.tsx",
        "src/api/payments.py",
        "terraform/main.tf",
        "tests/test_payments.py",
        "README.md",
    ]:
        loaded = [n for n, pats in rules
                  if any(path_matches(target, p) for p in (pats or []))]
        print(f"    {target:34s} -> {loaded or ['(none — no rule tokens spent)']}")

    note("Button.test.tsx and tests/test_payments.py sit in completely different "
         "directories and both match the testing rule. That is the capability a "
         "directory-level CLAUDE.md structurally cannot provide.")

    # -- 4. Commands -------------------------------------------------------
    section("4. Slash commands (Sample Question 4)")
    cmd = os.path.join(PROJECT, ".claude", "commands", "review.md")
    fm, _ = parse_frontmatter(cmd)
    print(f"  .claude/commands/review.md -> /review")
    print(f"    frontmatter: {fm}")
    print(
        "\n    .claude/commands/     project-scoped, version-controlled, everyone gets it\n"
        "    ~/.claude/commands/   personal, never shared\n"
        "    CLAUDE.md             project instructions — NOT a place to define commands\n"
        "    .claude/config.json   does not exist (the exam's invented distractor)"
    )

    # -- 5. Skills ---------------------------------------------------------
    section("5. Skills and their frontmatter")
    skills_dir = os.path.join(PROJECT, ".claude", "skills")
    for skill in sorted(os.listdir(skills_dir)):
        fm, _ = parse_frontmatter(os.path.join(skills_dir, skill, "SKILL.md"))
        print(f"  /{skill}")
        for key in ["context", "allowed-tools", "argument-hint"]:
            if key in fm:
                print(f"      {key:15s} {fm[key]}")
    print(
        "\n    context: fork    run in an isolated sub-agent so verbose or exploratory\n"
        "                     output never lands in the main conversation\n"
        "    allowed-tools    restrict tool access during the skill (read-only mapping,\n"
        "                     no destructive actions)\n"
        "    argument-hint    prompt the developer for the parameter when they invoke\n"
        "                     the skill bare\n\n"
        "    Personal variants go in ~/.claude/skills/ under a DIFFERENT NAME, so your\n"
        "    customisation does not shadow the team's version for everyone else."
    )

    # -- 6. Live check -----------------------------------------------------
    section("6. Live check — is the project configuration actually loading?")
    good("Agent running with cwd=example_project and setting_sources=['project']")
    answer = await ask_in_project(
        "Without reading any files: according to your project instructions, how must "
        "this codebase represent currency, and what is required to ship alongside every "
        "behavioural change? Answer in two short lines.",
        PROJECT,
    )
    show("Answer", answer)
    picked_up = "minor unit" in answer.lower() or "integer" in answer.lower()
    print(f"  root CLAUDE.md was in context: {'YES' if picked_up else 'NO'}")
    if not picked_up:
        note("If this says NO, check setting_sources — an SDK agent that omits it loads "
             "no project configuration at all, which looks exactly like a broken "
             "CLAUDE.md.")

    print(
        "\n  Diagnosing this interactively: run /memory inside a Claude Code session. It\n"
        "  lists every memory file currently loaded, which is how you tell 'my rule is\n"
        "  wrong' apart from 'my rule was never loaded'. Inconsistent behaviour across\n"
        "  sessions or teammates is nearly always the second one."
    )

    takeaway(
        "user (~/.claude) = private; project (repo CLAUDE.md) = shared; directory = subtree.",
        "Teammate missing instructions -> they were user-scoped. Move to project level.",
        "@import keeps the always-loaded root file small; the detail lives in imports.",
        ".claude/rules/ + paths globs = conventions by FILE TYPE across directories.",
        "Directory CLAUDE.md is directory-bound and cannot span scattered test files.",
        ".claude/commands/ = shared slash commands. ~/.claude/commands/ = personal.",
        "Skill frontmatter: context: fork (isolate), allowed-tools (restrict), argument-hint.",
        "CLAUDE.md = always loaded universal standards. Skills = on-demand workflows.",
        "/memory shows which files actually loaded. Use it before debugging the content.",
    )


if __name__ == "__main__":
    asyncio.run(main())
