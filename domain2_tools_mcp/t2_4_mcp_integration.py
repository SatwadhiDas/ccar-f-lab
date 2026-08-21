"""
Task 2.4 — Integrate MCP servers into Claude Code and agent workflows.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain2_tools_mcp/t2_4_mcp_integration.py

WHAT THE EXAM TESTS
-------------------
1. SCOPING. Two config locations, and the exam asks you to pick correctly:

     .mcp.json          project-scoped. Committed to the repo. Shared team tooling.
                        Every teammate gets it on clone/pull.
     ~/.claude.json     user-scoped. Personal machine only. Never shared.
                        Personal or experimental servers.

   The diagnostic form of this question: "a new team member isn't getting the
   integration" -> it was configured user-scoped instead of project-scoped.

2. ENVIRONMENT VARIABLE EXPANSION. `${GITHUB_TOKEN}` in .mcp.json lets you commit
   the config without committing the secret. This is what makes project scope
   viable at all — otherwise sharing the config would mean sharing credentials.

3. SIMULTANEOUS AVAILABILITY. Tools from ALL configured servers are discovered at
   connection time and are available to the agent at once. Project and user
   scoped servers coexist; you do not pick one.

4. RESOURCES vs TOOLS. Resources expose content catalogues (issue summaries, doc
   hierarchies, database schemas) so the agent has visibility WITHOUT burning
   exploratory tool calls.

5. DESCRIPTION QUALITY AS AN ADOPTION PROBLEM. If your MCP tool's description is
   thin, the agent falls back to a built-in tool it understands better — Grep
   instead of your purpose-built search. The fix is a fuller description, not a
   louder system prompt.

6. BUILD vs ADOPT. For standard integrations (Jira, GitHub, Sentry) use an
   existing community server. Reserve custom servers for team-specific workflows
   nobody else could have written.

This script launches the real stdio server in ./mcp_server/support_server.py and
drives it through the Agent SDK.
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway, stream_messages

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "mcp_server", "support_server.py")
PYTHON = sys.executable

# The same shape you would write into .mcp.json, expressed in Python.
# Note `env`: real deployments pass credentials through here, sourced from the
# environment rather than hard-coded — see .mcp.json in this directory.
SUPPORT_SERVER = {
    "type": "stdio",
    "command": PYTHON,
    "args": [SERVER],
    "env": {
        # Demonstrates the pattern. os.environ.get keeps the secret out of the file,
        # exactly as ${SUPPORT_API_TOKEN} does inside .mcp.json.
        "SUPPORT_API_TOKEN": os.environ.get("SUPPORT_API_TOKEN", "dev-placeholder"),
    },
}


async def run(prompt: str, allowed_tools, extra_system=""):
    options = ClaudeAgentOptions(
        system_prompt=("You are a support operations assistant. " + extra_system).strip(),
        mcp_servers={"support": SUPPORT_SERVER},
        # strict_mcp_config=True ignores servers configured in .mcp.json and
        # ~/.claude.json and uses ONLY the ones passed here.
        #
        # Without it the exercise is not hermetic: your own globally-configured
        # servers get discovered too, and the agent will happily answer the
        # question using a Postgres server you forgot you had connected. That is
        # point 3 of this exercise demonstrating itself — every configured server
        # is live at once, whether or not you were thinking about it.
        strict_mcp_config=True,
        allowed_tools=allowed_tools,
        max_turns=8,
        permission_mode="bypassPermissions",
        cwd=HERE,
    )
    text, calls = [], []
    async for message in stream_messages(prompt, options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    calls.append(block.name)
    return "\n".join(text).strip(), calls


async def main():
    banner("MCP server integration", "Task 2.4 — scoping, env expansion, resources")

    # -- 1. Connect and use --------------------------------------------------
    section("1. Connecting to a project-scoped stdio server")
    print(f"  launching: {PYTHON} {os.path.relpath(SERVER, os.path.dirname(HERE))}")
    answer, calls = await run(
        "What open support tickets does customer CUST-4417 have, and which is most urgent?",
        allowed_tools=["mcp__support__find_tickets", "mcp__support__get_ticket"],
    )
    print(f"  tools called: {calls}")
    show("Answer", answer[:700])
    note("MCP tool names are namespaced as mcp__<server>__<tool>. That prefix is how "
         "you allowlist per-server in allowed_tools, and how you tell an MCP tool from "
         "a built-in one when reading a trace.")

    # -- 2. Resources vs exploratory tool calls ------------------------------
    section("2. Resources reduce exploratory tool calls")
    bad("Tools only — the agent must discover the data shape by probing")
    a1, c1 = await run(
        "I need to write a query that finds all urgent open tickets. What columns are "
        "available on the tickets table and what values can status take?",
        allowed_tools=["mcp__support__find_tickets", "mcp__support__get_ticket"],
    )
    print(f"  tool calls: {len(c1)} -> {c1}")
    show("Answer", a1[:500])
    note("With no schema resource, the only way to learn the shape is to call tools and "
         "infer it from whatever records come back — round trips that produce structural "
         "knowledge, not answers, and that fill context on the way.")

    good("Resource exposed — schema://support is available up front")
    a2, c2 = await run(
        "I need to write a query that finds all urgent open tickets. Consult the "
        "support schema resource for the exact columns and the allowed status values.",
        allowed_tools=["mcp__support__find_tickets", "mcp__support__get_ticket",
                       "ReadMcpResourceTool", "ListMcpResourcesTool"],
    )
    print(f"  tool calls: {len(c2)} -> {c2}")
    show("Answer", a2[:700])
    got_enum = "pending" in a2  # only present in the schema resource
    print(f"  reported the exact status enum from the schema: {'YES' if got_enum else 'NO'}")
    if got_enum:
        note("It named 'pending' — a value that appears in NO ticket record in the "
             "fixture. It could only have come from the schema resource. That is the "
             "difference between reading a catalogue and inferring from samples.")

    # -- 3. Config scoping ---------------------------------------------------
    section("3. Config scoping — the diagnostic question")
    print(
        "  .mcp.json  (project, committed)      -> everyone on the team gets it\n"
        "  ~/.claude.json (user, never shared)  -> only you\n\n"
        "  Symptom: 'the new hire's agent can't see our Jira tools.'\n"
        "  Cause:   somebody configured the server user-scoped.\n"
        "  Fix:     move it to .mcp.json and commit it.\n\n"
        "  Same shape as the CLAUDE.md hierarchy question in Domain 3 — if a teammate\n"
        "  is missing configuration, ask WHICH SCOPE it lives in first.\n\n"
        "  Both scopes are active at once. Tools from every configured server are\n"
        "  discovered at connection time and offered to the agent simultaneously, so a\n"
        "  personal experimental server and the shared team servers coexist."
    )
    cfg = os.path.join(HERE, ".mcp.json")
    if os.path.exists(cfg):
        with open(cfg) as f:
            show("./domain2_tools_mcp/.mcp.json", f.read())
        note("${SUPPORT_API_TOKEN} and ${GITHUB_TOKEN} are expanded at load time. The "
             "config is safe to commit; the secrets stay in the environment.")

    # -- 4. Adoption ---------------------------------------------------------
    section("4. Description quality is an adoption problem")
    print(
        "  Give the agent both Grep and a thinly-described MCP search tool, and it will\n"
        "  reach for Grep — it knows exactly what Grep does. Your tool loses by default.\n\n"
        "  The fix is in find_tickets' docstring in mcp_server/support_server.py: it\n"
        "  states what is searched, what comes back, which formats are accepted, which\n"
        "  queries should route to it, how empty results differ from errors, and where\n"
        "  the boundary with get_ticket lies. That is what earns the call.\n\n"
        "  BUILD vs ADOPT: Jira, GitHub, Sentry, Postgres all have maintained community\n"
        "  servers. Write a custom server for the workflow that is specific to your team\n"
        "  — the thing no community server could know about."
    )

    takeaway(
        ".mcp.json = project/shared/committed. ~/.claude.json = user/personal/never shared.",
        "'Teammate isn't getting it' -> it was configured user-scoped. Move to project.",
        "${ENV_VAR} expansion is what makes committing the config safe.",
        "All configured servers are discovered at connect time and available simultaneously.",
        "Resources = content catalogues (schemas, issue lists) that kill exploratory calls.",
        "Thin MCP descriptions lose to built-ins like Grep. Write them properly.",
        "Adopt community servers for standard integrations; build only what is team-specific.",
    )


if __name__ == "__main__":
    asyncio.run(main())
