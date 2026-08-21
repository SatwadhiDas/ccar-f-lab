"""
Verify both credential paths before running the lab.

    python check_setup.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MODEL, banner, good, bad, note, section  # noqa: E402


def check_raw_api():
    section("Raw Claude API  (needed by domains 2, 4, 5)")
    try:
        import anthropic
    except ImportError:
        bad("`anthropic` not installed")
        print("    pip install -r requirements.txt")
        return False

    if not os.environ.get("ANTHROPIC_API_KEY"):
        bad("ANTHROPIC_API_KEY not found")
        print("    Fix (persists across shells and editors):")
        print("      cp .env.example .env && edit .env")
        print("    Or, for this shell only:")
        print("      export ANTHROPIC_API_KEY=sk-ant-...")
        print("    Or use an OAuth profile:  ant auth login")
        return False

    try:
        c = anthropic.Anthropic()
        r = c.messages.create(model=MODEL, max_tokens=16,
                              messages=[{"role": "user", "content": "Reply with: OK"}])
        good(f"live — {r.model}  ({r.usage.input_tokens} in / {r.usage.output_tokens} out)")
        return True
    except Exception as exc:
        bad(f"{type(exc).__name__}: {str(exc)[:220]}")
        return False


def check_agent_sdk():
    section("Claude Agent SDK  (needed by domains 1, 3)")
    try:
        import anyio
        from claude_agent_sdk import (query, ClaudeAgentOptions,
                                      AssistantMessage, TextBlock)
    except ImportError as exc:
        bad(f"claude-agent-sdk not importable: {exc}")
        return False

    async def probe():
        opts = ClaudeAgentOptions(tools=[], max_turns=1,
                                  system_prompt="Answer in one word.")
        out = []
        async for m in query(prompt="Say OK.", options=opts):
            if isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, TextBlock):
                        out.append(b.text)
        return " ".join(out).strip()

    try:
        good(f"live — agent replied {anyio.run(probe)[:40]!r}")
        note("This path uses your existing Claude Code login, not ANTHROPIC_API_KEY.")
        return True
    except Exception as exc:
        bad(f"{type(exc).__name__}: {str(exec) if False else str(exc)[:220]}")
        print("    Fix: log in to Claude Code on this machine.")
        return False


if __name__ == "__main__":
    banner("CCAR-F lab setup check", f"model: {MODEL}")
    a = check_raw_api()
    b = check_agent_sdk()
    print()
    if a and b:
        good("Both credential paths live. Every exercise will run.")
    elif b:
        note("Agent SDK works: domains 1 and 3 will run now.")
        note("Add ANTHROPIC_API_KEY to .env to unlock domains 2, 4 and 5.")
    elif a:
        note("Raw API works: domains 2, 4 and 5 will run now.")
        note("Log in to Claude Code to unlock domains 1 and 3.")
    else:
        bad("Neither path is configured yet.")
    print()
