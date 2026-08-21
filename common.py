"""
Shared plumbing for the CCAR-F lab.

Every script in this repo imports from here so that model choice, credential
handling, and output formatting are consistent across all 30 exercises.

Two different credentials are in play, and it matters which one a script needs:

  * Domains 2, 4, 5 use the raw Claude API (`anthropic` SDK).
    These need ANTHROPIC_API_KEY (or an `ant auth login` profile).

  * Domains 1, 3 use the Claude Agent SDK (`claude_agent_sdk`), which drives the
    bundled Claude Code CLI. Those inherit your existing Claude Code login and
    usually run with no extra setup.

Run `python check_setup.py` to see which of the two you currently have.
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------
# An `export ANTHROPIC_API_KEY=...` typed in one terminal does not reach a script
# launched from another, which is a reliable way to lose twenty minutes. Keeping
# the key in ./.env (git-ignored) makes it work from any shell, any editor, and
# any CI runner. No python-dotenv dependency — the format is four lines to parse.
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        # A real environment variable always wins over the file.
        os.environ.setdefault(key, value)


_load_dotenv()

# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------
# claude-opus-5 is the default because the exam is written against the current
# frontier model's behavior. Every script honours CCAR_MODEL, so you can run the
# whole lab against a cheaper model while you iterate:
#
#     CCAR_MODEL=claude-haiku-4-5 python domain4_prompting/t4_2_few_shot.py
#
# Caveat worth internalising for the exam: some exercises (notably the
# false-positive and escalation-calibration ones) are demonstrating a *judgment*
# difference. On a smaller model the "bad prompt" and "good prompt" outputs
# diverge more dramatically, which actually makes the lesson clearer.
MODEL = os.environ.get("CCAR_MODEL", "claude-opus-5")

# A deliberately small model for the "cheap subagent" exercises in Domain 5.
CHEAP_MODEL = os.environ.get("CCAR_CHEAP_MODEL", "claude-haiku-4-5")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
def client():
    """Return an Anthropic client, failing with a useful message if unauthenticated."""
    import anthropic

    try:
        return anthropic.Anthropic()
    except TypeError as exc:  # SDK raises TypeError when no credential resolves
        die(
            "No Claude API credential found.\n\n"
            "The raw-API exercises (domains 2, 4, 5) need one of:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  or:  ant auth login\n\n"
            "The Agent SDK exercises (domains 1, 3) do NOT need this — they use\n"
            "your existing Claude Code login.\n\n"
            f"SDK said: {exc}"
        )


def die(msg: str) -> None:
    print(f"\n\033[31m{msg}\033[0m\n", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Output formatting — keeps 30 scripts readable without a framework
# ---------------------------------------------------------------------------
_BOLD, _DIM, _RED, _GREEN, _YELLOW, _CYAN, _OFF = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m",
)


def banner(title: str, task_statement: str = "") -> None:
    print(f"\n{_BOLD}{_CYAN}{'=' * 78}{_OFF}")
    print(f"{_BOLD}{_CYAN}  {title}{_OFF}")
    if task_statement:
        print(f"{_DIM}  Exam objective: {task_statement}{_OFF}")
    print(f"{_BOLD}{_CYAN}{'=' * 78}{_OFF}")


def section(label: str) -> None:
    print(f"\n{_BOLD}--- {label} {'-' * max(0, 70 - len(label))}{_OFF}")


def bad(label: str) -> None:
    """Header for the anti-pattern half of an exercise."""
    print(f"\n{_RED}{_BOLD}[ANTI-PATTERN] {label}{_OFF}")


def good(label: str) -> None:
    """Header for the correct-pattern half of an exercise."""
    print(f"\n{_GREEN}{_BOLD}[CORRECT] {label}{_OFF}")


def note(msg: str) -> None:
    print(f"{_YELLOW}  ! {msg}{_OFF}")


def wrap(text: str, indent: str = "    ") -> str:
    return "\n".join(
        textwrap.fill(line, width=96, initial_indent=indent, subsequent_indent=indent)
        if line.strip()
        else ""
        for line in str(text).splitlines()
    )


def show(label: str, value) -> None:
    print(f"{_DIM}{label}:{_OFF}")
    print(wrap(value))


def takeaway(*lines: str) -> None:
    """The one thing to remember walking into the exam."""
    print(f"\n{_BOLD}{_GREEN}  EXAM TAKEAWAY{_OFF}")
    for line in lines:
        print(f"{_GREEN}  → {line}{_OFF}")
    print()


# ---------------------------------------------------------------------------
# Usage / cost accounting
# ---------------------------------------------------------------------------
def usage_line(response) -> str:
    """One-line token summary. Useful for the context-management exercises."""
    u = response.usage
    parts = [f"in={u.input_tokens}", f"out={u.output_tokens}"]
    if getattr(u, "cache_read_input_tokens", 0):
        parts.append(f"cache_read={u.cache_read_input_tokens}")
    if getattr(u, "cache_creation_input_tokens", 0):
        parts.append(f"cache_write={u.cache_creation_input_tokens}")
    return "  ".join(parts)


def text_of(response) -> str:
    """
    Extract text blocks from a response.

    Note the guard on block.type: `response.content[0].text` blows up whenever the
    first block is a thinking block, which is the default on claude-opus-5. This
    is a real exam-adjacent trap — always narrow by type.
    """
    return "\n".join(b.text for b in response.content if b.type == "text")


def tool_calls_of(response):
    """Return the tool_use blocks from a response."""
    return [b for b in response.content if b.type == "tool_use"]


# ---------------------------------------------------------------------------
# Agent SDK resilience
# ---------------------------------------------------------------------------
async def stream_messages(prompt, options):
    """
    Iterate `claude_agent_sdk.query()`, tolerating terminal transport errors.

    The Agent SDK occasionally raises mid-stream — most commonly
    `Exception: Claude Code returned an error result: success`, and also on
    `Reached maximum number of turns`. Both surface as a hard exception that
    kills the whole script, discarding every message already collected.

    For a teaching lab that is the wrong trade: a run that produced four of five
    sections is far more useful than a traceback. This wrapper yields everything
    that did arrive, prints a one-line warning, and lets the caller carry on with
    partial results.

    That is also, not coincidentally, the exam's own lesson about error
    propagation (Task 5.3): do not discard successful work because a later step
    failed, and make the degradation VISIBLE rather than silent.
    """
    from claude_agent_sdk import query as _query

    try:
        async for message in _query(prompt=prompt, options=options):
            yield message
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        note(f"Agent SDK stream ended early ({type(exc).__name__}: "
             f"{str(exc)[:120]}). Continuing with partial results.")
