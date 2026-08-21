"""
Task 3.4 — Plan mode vs direct execution.
Task 3.5 — Iterative refinement techniques.

Needs: your existing Claude Code login (Agent SDK). No API key required.
Run:   python domain3_claude_code/t3_4_plan_vs_direct.py

PLAN MODE — SAMPLE QUESTION 5
-----------------------------
"Restructure the team's monolithic application into microservices... changes
across dozens of files and requires decisions about service boundaries."

  A. Plan mode.                                        <-- correct
  B. Direct execution, let boundaries emerge.
  C. Direct execution with comprehensive upfront instructions.
  D. Start direct, switch to plan mode if complexity appears.

D is the interesting distractor. It sounds prudent — "escalate when needed" — but
the complexity is STATED IN THE REQUIREMENTS. It is not something that might
emerge; you already know. Choosing D means deliberately discovering, at cost,
something the prompt already told you.

C fails for a different reason: it presumes you already know the right structure.
You cannot write comprehensive upfront instructions for service boundaries you
have not yet explored.

THE DECISION RULE
-----------------
  Plan mode      large-scale change, multiple valid approaches, architectural
                 decisions, multi-file modification, expensive rework if wrong
  Direct         well-scoped and well-understood: a single-file bug fix with a
                 clear stack trace, adding one validation conditional

And the combination the exam explicitly endorses: plan mode for INVESTIGATION,
then direct execution for IMPLEMENTATION of the approved plan.

ITERATIVE REFINEMENT (Task 3.5)
-------------------------------
  Concrete input/output examples   the most effective fix when a prose spec is
                                   being interpreted inconsistently
  Test-driven iteration            write the suite first, then iterate by feeding
                                   back failures
  Interview pattern                have Claude ask YOU questions first, to surface
                                   considerations you had not thought of
  Batch vs sequential              interacting problems -> one detailed message;
                                   independent problems -> fix sequentially
"""

import sys
import os
import shutil
import asyncio
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import banner, good, bad, note, section, show, takeaway, stream_messages

from claude_agent_sdk import (
    query, ClaudeAgentOptions, AssistantMessage, TextBlock, ToolUseBlock,
)

WORKSPACE = None

BUGGY = '''\
def parse_expiry(value):
    """Parse an MM/YY card expiry into (month, year)."""
    month, year = value.split("/")
    return int(month), 2000 + int(year)
'''

# A monolith with genuinely tangled concerns, so the plan-mode exercise has
# something real to reason about. The entanglement is deliberate: catalog reaches
# into payment internals, notifications imports from both, and shared/models.py
# is a god-module every layer depends on. Those are exactly the facts that decide
# where the service boundaries can go — and exactly what you cannot know before
# exploring, which is the point of the exercise.
MONOLITH = {
    "app/shared/models.py": '''\
"""Every layer imports from here. This is the hard part of any split."""
class User: ...
class Order:
    def __init__(self): self.items, self.payment_ref, self.notify_prefs = [], None, {}
class Product: ...
class PaymentIntent: ...
''',
    "app/payment/gateway.py": '''\
from app.shared.models import Order, PaymentIntent

RETRY_LIMIT = 3

def charge(order: Order, amount_cents: int):
    intent = PaymentIntent()
    return _post("/charge", {"order": order, "amount": amount_cents, "intent": intent})

def refund(order: Order, amount_cents: int):
    return _post("/refund", {"order": order, "amount": amount_cents})

def _post(path, body): ...
''',
    "app/payment/ledger.py": '''\
from app.shared.models import Order

def record(order: Order, amount_cents: int, kind: str): ...
def balance_for(order: Order) -> int: ...
''',
    "app/catalog/pricing.py": '''\
from app.shared.models import Product
# TANGLE: catalog reaches directly into a payment internal to decide display price.
from app.payment.gateway import RETRY_LIMIT
from app.payment.ledger import balance_for

def display_price(product: Product, order=None) -> int:
    credit = balance_for(order) if order else 0
    return max(0, product.base_price_cents - credit)
''',
    "app/catalog/search.py": '''\
from app.shared.models import Product

def search(q: str) -> list[Product]: ...
def facets(q: str) -> dict: ...
''',
    "app/notifications/dispatch.py": '''\
# TANGLE: notifications imports from BOTH other domains.
from app.payment.gateway import charge
from app.catalog.pricing import display_price
from app.shared.models import Order

def on_order_placed(order: Order): ...
def on_payment_failed(order: Order): ...
def send(template: str, to: str, ctx: dict): ...
''',
    "app/notifications/templates.py": '''\
TEMPLATES = {"order_placed": "...", "payment_failed": "...", "refunded": "..."}
''',
    "app/api/routes.py": '''\
from app.payment.gateway import charge, refund
from app.catalog.pricing import display_price
from app.catalog.search import search
from app.notifications.dispatch import on_order_placed

def post_checkout(req): ...
def get_search(req): ...
def post_refund(req): ...
''',
    "tests/test_checkout.py": "def test_checkout(): ...\n",
    "tests/test_pricing.py": "def test_display_price(): ...\n",
}


async def run(prompt, *, permission_mode="bypassPermissions", tools=("Read", "Edit", "Write", "Grep", "Glob")):
    options = ClaudeAgentOptions(
        system_prompt="You are a senior engineer working in this repository.",
        allowed_tools=list(tools),
        cwd=WORKSPACE,
        permission_mode=permission_mode,
        max_turns=30,
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
    global WORKSPACE
    WORKSPACE = tempfile.mkdtemp(prefix="ccar-plan-")
    with open(os.path.join(WORKSPACE, "expiry.py"), "w") as f:
        f.write(BUGGY)
    for rel, content in MONOLITH.items():
        path = os.path.join(WORKSPACE, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    banner("Plan mode vs direct execution", "Task 3.4 / 3.5 — this is Sample Question 5")
    print(f"  workspace: {WORKSPACE}")

    # -- 1. Direct execution is correct here --------------------------------
    section("1. A well-scoped change — direct execution")
    good("Single file, clear failure, one obvious fix")
    answer, calls = await run(
        "expiry.py crashes with ValueError on the input '3/28' (single-digit month "
        "with no leading zero) and on '12/2028'. Fix parse_expiry to handle both. "
        "Make the edit."
    )
    print(f"  tools used: {calls}")
    with open(os.path.join(WORKSPACE, "expiry.py")) as f:
        after = f.read()
    print(f"  file modified: {'YES' if after != BUGGY else 'NO'}")
    show("Result", answer[:500])
    note("Scope is clear, the failure is known, and there is one reasonable fix. "
         "Planning here is pure overhead — you would be writing a plan for work you "
         "could have finished in the time it took to write the plan.")

    # -- 2. Plan mode for the architectural case ----------------------------
    section("2. An architectural change — plan mode")
    good('permission_mode="plan" — explore and design, change nothing')
    # Snapshot the SOURCE files so we can measure what actually changed on disk.
    # Counting Write/Edit *call attempts* is the wrong measurement: an attempt that
    # plan mode refuses still shows up as a call, and the agent may legitimately
    # write a plan document somewhere outside the source tree. What matters is
    # whether app/ was modified.
    def snapshot():
        out = {}
        for rel in MONOLITH:
            path = os.path.join(WORKSPACE, rel)
            if os.path.exists(path):
                with open(path) as fh:
                    out[rel] = fh.read()
        return out

    before = snapshot()
    plan_answer, plan_calls = await run(
        "We want to split the app/ package into separate payment, catalog, and "
        "notification services. Explore the actual import graph, work out where the "
        "service boundaries can go given the coupling you find, and outline a "
        "migration sequence. Consider more than one option for the shared models.",
        permission_mode="plan",
    )
    after_snap = snapshot()
    changed = [rel for rel in before if before[rel] != after_snap.get(rel)]
    attempted = [c for c in plan_calls if c in ("Edit", "Write", "NotebookEdit")]
    print(f"  tools used: {plan_calls}")
    print(f"  mutating calls attempted: {len(attempted)}")
    print(f"  SOURCE FILES ACTUALLY CHANGED: {len(changed)}  {changed or ''}")
    if attempted and not changed:
        note("A write was attempted and no source file changed — plan mode refused it. "
             "This is why you measure the filesystem, not the call log: the attempt is "
             "visible in the trace either way.")
    show("Plan (truncated)", plan_answer[:900])
    note("Plan mode lets the agent explore the codebase freely while refusing to "
         "modify anything, so you can evaluate the approach before any of it is "
         "committed to. The value is not the plan document — it is that a wrong "
         "approach costs a conversation instead of a revert.")

    section("Why the distractors fail (Sample Question 5)")
    print(
        "  B. Direct execution, letting boundaries emerge\n"
        "     Dependencies surface LATE. By the time you learn that catalog reaches\n"
        "     into payment internals, you have already split them the wrong way.\n\n"
        "  C. Direct execution with comprehensive upfront instructions\n"
        "     Presumes you already know the right structure. If you knew the service\n"
        "     boundaries you would not be asking for this work.\n\n"
        "  D. Start direct, switch to plan mode if complexity appears\n"
        "     The complexity is IN THE REQUIREMENTS — 'dozens of files', 'decisions\n"
        "     about service boundaries'. Waiting for it to 'appear' means paying for\n"
        "     the discovery of something you were already told.\n\n"
        "  The endorsed combination: plan mode to investigate and agree the approach,\n"
        "  then direct execution to implement the approved plan."
    )

    section("The Explore subagent")
    print(
        "  Multi-phase work has a second problem plan mode does not solve: discovery\n"
        "  output is VERBOSE. Dozens of Greps and Reads, most of whose content you do\n"
        "  not need once you have the conclusion.\n\n"
        "  The Explore subagent runs that discovery in an isolated context and returns\n"
        "  only a summary, so the main conversation keeps its window for the work. Same\n"
        "  instinct as `context: fork` on a skill (t3_config_hierarchy) and subagent\n"
        "  delegation for exploration (t5_4) — three surfaces, one idea: keep verbose\n"
        "  intermediate output out of the context you are reasoning in."
    )

    # -- 3. Iterative refinement -------------------------------------------
    section("3. Iterative refinement (Task 3.5)")

    bad("Prose specification, interpreted inconsistently")
    prose_answer, _ = await run(
        "Write a function `normalize_phone(s)` that cleans up messy phone numbers "
        "into a standard format. Just show the code and two example outputs.",
        tools=(),
    )
    show("What 'standard format' produced", prose_answer[:450])
    note("'Standard format' is doing all the work in that sentence, and it means "
         "something different to everyone. E.164? Hyphenated? Country code retained "
         "or stripped? The model has to pick, and it will pick differently next time.")

    good("The same request with 2-3 concrete input/output examples")
    example_answer, _ = await run(
        "Write a function `normalize_phone(s)`. Here is exactly what it must do:\n\n"
        '  normalize_phone("(415) 555-0142")     -> "+14155550142"\n'
        '  normalize_phone("415.555.0142 x22")   -> "+14155550142x22"\n'
        '  normalize_phone("+44 20 7946 0958")   -> "+442079460958"\n'
        '  normalize_phone("nonsense")           -> None\n\n'
        "Show the code and confirm each example.",
        tools=(),
    )
    show("Result", example_answer[:600])
    note("Country code retained, extension preserved with an 'x', unparseable input "
         "returns None instead of raising — three decisions the prose version left "
         "open, all settled by four lines of examples. The exam's claim is that "
         "concrete input/output pairs are the MOST effective technique when prose is "
         "producing inconsistent results, and this is why.")

    print(
        "\n  The other three refinement techniques:\n\n"
        "  TEST-DRIVEN ITERATION — write the suite first (expected behaviour, edge\n"
        "    cases, performance), then iterate by pasting failures back. The tests are\n"
        "    an unambiguous spec that cannot be reinterpreted between turns.\n\n"
        "  INTERVIEW PATTERN — 'before implementing, ask me questions about anything\n"
        "    underspecified.' Surfaces the considerations you did not think to state:\n"
        "    cache invalidation strategy, failure modes, concurrency assumptions. Most\n"
        "    valuable in a domain you do not know well, where you cannot yet tell what\n"
        "    the important questions are.\n\n"
        "  BATCH vs SEQUENTIAL — if fixes INTERACT (changing the retry policy changes\n"
        "    what the timeout should be), put them in ONE detailed message so they are\n"
        "    resolved together. If they are INDEPENDENT, go one at a time so you can\n"
        "    attribute each regression to its cause."
    )

    takeaway(
        "Plan mode: large scale, multiple valid approaches, architectural, multi-file.",
        "Direct: well-scoped and understood — single-file fix with a clear stack trace.",
        "Stated complexity is not 'emergent' complexity. Don't wait to discover it. (D)",
        "Plan to investigate, then direct to implement the approved plan.",
        "Explore subagent isolates verbose discovery so the main context survives.",
        "Prose spec interpreted inconsistently -> give 2-3 concrete input/output examples.",
        "Interacting fixes: one message. Independent fixes: sequential.",
    )

    shutil.rmtree(WORKSPACE, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
