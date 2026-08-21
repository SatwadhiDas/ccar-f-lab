"""
Task 1.5 — Agent SDK hooks for tool call interception and data normalization.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain1_agentic/t1_5_hooks.py

THE TWO HOOK PATTERNS THE EXAM NAMES
------------------------------------
1. PreToolUse  — intercept an OUTGOING tool call and block it when it violates a
                 business rule (the exam's example: refunds over $500), then
                 redirect to an alternative workflow such as human escalation.

2. PostToolUse — intercept an INCOMING tool result and transform it before the
                 model ever sees it. The exam's example: normalising
                 heterogeneous date formats (Unix epoch, ISO 8601, numeric status
                 codes) coming from different MCP tools.

The distinction the exam keeps returning to is deterministic vs probabilistic.
"Never issue a refund over $500" in the system prompt is a request. A PreToolUse
hook that returns permissionDecision="deny" is a guarantee. When the business
rule has financial or compliance consequences, you need the guarantee.

This script wires three backend tools with deliberately inconsistent output
formats, attaches both hooks, and prints exactly what the hook saw and what it
handed onward.
"""

import sys
import os
import json
import asyncio
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway, stream_messages

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    HookMatcher,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

REFUND_LIMIT_USD = 500.0

# Everything the hooks observe is recorded here so the run is inspectable.
TRACE: list[str] = []


# ---------------------------------------------------------------------------
# Three tools, three different houses' idea of how to represent a timestamp.
# This is the realistic case: each MCP server was written by a different team.
# ---------------------------------------------------------------------------
@tool("get_order", "Retrieve an order. Returns a Unix epoch timestamp for the order date.",
      {"order_id": str})
async def get_order(args):
    return {"content": [{"type": "text", "text": json.dumps({
        "order_id": args["order_id"],
        "amount_usd": 1395.00,
        "ordered_at": 1753747200,          # Unix epoch seconds
        "status_code": 3,                  # numeric status code
    })}]}


@tool("get_shipment", "Retrieve shipment info. Returns an ISO 8601 timestamp.",
      {"order_id": str})
async def get_shipment(args):
    return {"content": [{"type": "text", "text": json.dumps({
        "order_id": args["order_id"],
        "shipped_at": "2025-07-30T14:22:05Z",   # ISO 8601
        "status_code": 7,
    })}]}


@tool("process_refund", "Issue a refund for an order. Financial operation.",
      {"order_id": str, "amount_usd": float})
async def process_refund(args):
    # If this body executes, the money moved. The PreToolUse hook exists so that
    # an over-limit call never reaches this line.
    TRACE.append(f"!! process_refund BODY EXECUTED for ${args['amount_usd']}")
    return {"content": [{"type": "text", "text": json.dumps({
        "refund_id": "RF-90211", "amount_usd": args["amount_usd"], "status": "issued",
    })}]}


BACKEND = create_sdk_mcp_server(
    name="billing", version="1.0.0", tools=[get_order, get_shipment, process_refund]
)

STATUS_CODES = {3: "delivered", 7: "in_transit", 9: "returned"}


# ---------------------------------------------------------------------------
# HOOK 1 — PreToolUse: deterministic policy enforcement
# ---------------------------------------------------------------------------
async def refund_ceiling_hook(input_data, tool_use_id, context):
    """
    Blocks refunds above the policy ceiling before the tool body runs.

    Returning permissionDecision="deny" with a reason does two useful things:
      * the tool never executes (the guarantee), and
      * the reason string is surfaced to the model, so it can redirect to the
        escalation workflow rather than simply failing.

    That second part is what the exam means by "redirect to alternative
    workflows" — a bare denial leaves the agent stuck.
    """
    tool_name = input_data.get("tool_name", "")
    if not tool_name.endswith("process_refund"):
        return {}

    amount = float(input_data.get("tool_input", {}).get("amount_usd") or 0)
    TRACE.append(f"PreToolUse saw {tool_name} amount_usd={amount}")

    if amount > REFUND_LIMIT_USD:
        TRACE.append(f"PreToolUse DENIED (${amount} > ${REFUND_LIMIT_USD})")
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Policy: refunds above ${REFUND_LIMIT_USD:,.0f} require human "
                    f"approval. This request was ${amount:,.2f}. Do not retry the "
                    f"refund. Instead, tell the customer their refund needs "
                    f"supervisor approval and that you are escalating it, and "
                    f"summarise the case for the human agent."
                ),
            }
        }

    TRACE.append(f"PreToolUse ALLOWED (${amount} <= ${REFUND_LIMIT_USD})")
    return {}


# ---------------------------------------------------------------------------
# HOOK 2 — PostToolUse: normalise heterogeneous formats
# ---------------------------------------------------------------------------
def _normalize(payload: dict) -> dict:
    """Coerce every timestamp to ISO 8601 UTC and every status code to a label."""
    out = dict(payload)
    for key in list(out):
        if key.endswith("_at"):
            v = out[key]
            if isinstance(v, (int, float)):
                out[key] = datetime.fromtimestamp(v, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if key == "status_code":
            out["status"] = STATUS_CODES.get(out[key], f"unknown_{out[key]}")
    return out


async def normalize_results_hook(input_data, tool_use_id, context):
    """
    Rewrites tool output before the model reads it.

    Why this belongs in a hook rather than in a prompt: asking the model to
    "interpret epoch timestamps as dates" works most of the time, and the times it
    doesn't you get a silently wrong date in a customer-facing answer. Conversion
    is pure, deterministic code — so make it deterministic code.

    PAYLOAD SHAPE — worth knowing, and worth verifying yourself rather than
    guessing. For an MCP tool, `input_data["tool_response"]` is the content-block
    LIST directly:

        [{"type": "text", "text": "{\\"ordered_at\\": 1753747200, ...}"}]

    not a dict with a "content" key. `updatedMCPToolOutput` must be handed back in
    that same list shape. Return a dict there instead and the CLI throws
    "e.reduce is not a function" while measuring the payload — the tool call fails
    and the model is told nothing useful. Built-in (non-MCP) tools use
    `updatedToolOutput` instead, which takes a plain value.
    """
    tool_name = input_data.get("tool_name", "")
    raw = input_data.get("tool_response")

    is_mcp = tool_name.startswith("mcp__")
    payload = None
    try:
        if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "text" in raw[0]:
            payload = json.loads(raw[0]["text"])          # MCP tool result
        elif isinstance(raw, dict) and "content" in raw:
            payload = json.loads(raw["content"][0]["text"])
        elif isinstance(raw, str):
            payload = json.loads(raw)
        elif isinstance(raw, dict):
            payload = raw
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}
    if not any(k.endswith("_at") or k == "status_code" for k in payload):
        return {}

    normalized = _normalize(payload)
    TRACE.append(f"PostToolUse normalized {tool_name}:")
    TRACE.append(f"    before -> {json.dumps(payload)}")
    TRACE.append(f"    after  -> {json.dumps(normalized)}")

    blocks = [{"type": "text", "text": json.dumps(normalized)}]
    key = "updatedMCPToolOutput" if is_mcp else "updatedToolOutput"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            key: blocks if is_mcp else json.dumps(normalized),
        }
    }


# ---------------------------------------------------------------------------
async def run(prompt: str, with_hooks: bool):
    TRACE.clear()
    options = ClaudeAgentOptions(
        system_prompt=(
            "You are a billing support agent. Use the billing tools to answer. "
            "Report dates in a human-readable form and state the order status. "
            "Refunds over $500 require human approval."  # prompt-level rule ONLY
        ),
        mcp_servers={"billing": BACKEND},
        strict_mcp_config=True,  # ignore any globally-configured servers; keep the demo hermetic
        allowed_tools=[
            "mcp__billing__get_order",
            "mcp__billing__get_shipment",
            "mcp__billing__process_refund",
        ],
        hooks=(
            {
                "PreToolUse": [HookMatcher(hooks=[refund_ceiling_hook])],
                "PostToolUse": [HookMatcher(hooks=[normalize_results_hook])],
            }
            if with_hooks
            else None
        ),
        max_turns=8,
        permission_mode="bypassPermissions",
    )

    text, calls = [], []
    async for message in stream_messages(prompt, options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    calls.append((block.name, block.input))
    return "\n".join(text).strip(), calls


async def main():
    banner("Hooks: interception and normalization",
           "Task 1.5 — PreToolUse policy gates, PostToolUse data normalization")

    # -- PostToolUse -------------------------------------------------------
    section("PostToolUse — normalising heterogeneous tool output")
    print("  get_order returns   ordered_at=1753747200   (Unix epoch), status_code=3")
    print("  get_shipment returns shipped_at='2025-07-30T14:22:05Z' (ISO), status_code=7")

    bad("No hook — the model is handed the raw formats")
    answer_raw, _ = await run(
        "For order ORD-88213: when was it ordered, when did it ship, and what is its status?",
        with_hooks=False,
    )
    show("Agent's answer", answer_raw[:700])
    leaked_raw = "1753747200" in answer_raw or "status_code" in answer_raw
    note("Raw epoch or status_code surfaced in the answer: "
         f"{'YES — the model is doing format archaeology in front of the customer.' if leaked_raw else 'not this run, but it has to guess the code mapping either way.'}")

    good("With the normalization hook attached")
    answer, calls = await run(
        "For order ORD-88213: when was it ordered, when did it ship, and what is its status?",
        with_hooks=True,
    )
    for line in TRACE:
        if line.startswith(("PostToolUse", "    before", "    after")):
            print(f"  {line}")
    show("Agent's answer", answer[:800])

    leaked = "1753747200" in answer or "status_code" in answer
    print(f"  raw epoch / status_code present in the answer: {'YES' if leaked else 'NO'}")
    if not leaked:
        note("The model never saw the epoch integer or the bare status code — the hook "
             "replaced the tool result before it reached the context. No format guessing "
             "was possible, which is the whole point.")
    else:
        note("Something still leaked through. Check that the hook's parse branch matched "
             "the tool_response shape — see the PAYLOAD SHAPE note on the hook.")

    # -- PreToolUse --------------------------------------------------------
    section("PreToolUse — enforcing the refund ceiling")
    refund_ask = (
        "Customer wants a full refund on order ORD-88213. Look up the order and "
        "process the refund for the full amount."
    )

    bad("Prompt-level rule only ('Refunds over $500 require human approval')")
    answer_np, calls_np = await run(refund_ask, with_hooks=False)
    attempted = [(n, i) for n, i in calls_np if n.endswith("process_refund")]
    executed = [t for t in TRACE if "BODY EXECUTED" in t]
    print(f"  process_refund calls attempted: {len(attempted)}")
    for n, i in attempted:
        print(f"    {n}({i})")
    if executed:
        note("The refund tool body RAN. $1,395 moved on a $500 policy limit, with the "
             "rule stated in the system prompt. This is the probabilistic failure the "
             "exam is describing — and it is silent.")
    else:
        note("The model complied this time. It often will. 'Often' is not a control: "
             "you cannot show an auditor a system prompt as evidence of a spend limit.")
    show("Agent's answer", answer_np[:600])

    good("With the PreToolUse hook attached")
    answer_h, calls_h = await run(refund_ask, with_hooks=True)
    for line in [t for t in TRACE if t.startswith("PreToolUse")]:
        print(f"  {line}")
    executed_h = [t for t in TRACE if "BODY EXECUTED" in t]
    print(f"  refund tool body executed: {'YES' if executed_h else 'NO'}")
    show("Agent's answer", answer_h[:800])
    if not executed_h:
        note("Denied before execution. Note the agent did not simply error out — the "
             "permissionDecisionReason told it what to do instead, so it redirected to "
             "the escalation path. A bare 'denied' would have stranded it.")

    takeaway(
        "PreToolUse intercepts OUTGOING calls: block policy violations before execution.",
        "PostToolUse intercepts INCOMING results: normalize formats before the model reads them.",
        "Return permissionDecision='deny' PLUS a reason that names the alternative workflow.",
        "Hooks are deterministic; system-prompt rules are probabilistic. Money needs deterministic.",
        "Deterministic transforms (epoch->ISO, code->label) belong in code, never in a prompt.",
    )


if __name__ == "__main__":
    asyncio.run(main())
