"""
Task 1.6 — Task decomposition strategies (prompt chaining vs adaptive).
Task 4.6 — Multi-pass review architectures (the per-file + integration split).

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain1_agentic/t1_6_task_decomposition.py

THIS IS SAMPLE QUESTION 12
--------------------------
"A pull request modifies 14 files... Your single-pass review analyzing all files
together produces inconsistent results: detailed feedback for some files but
superficial comments for others, obvious bugs missed, and contradictory
feedback... How should you restructure the review?"

  A. Split into focused passes: analyse each file individually for local issues,
     then run a separate integration-focused pass.        <-- correct
  B. Make developers submit smaller PRs.
  C. Switch to a bigger context window.
  D. Run three passes and only flag issues appearing in 2 of 3.

The trap is C. A larger context window solves *capacity*; the failure here is
*attention dilution* — quality of attention per file drops as file count rises,
even when everything fits comfortably. D is worse than it looks: requiring
consensus SUPPRESSES real bugs, because a subtle bug is exactly the kind that
only one pass catches.

This script plants fourteen known bugs across fourteen files — thirteen local, one
visible only across a file boundary — matching the exam's stated PR size, and runs
both review architectures against them so you can compare recall rather than take
the claim on faith.

WHEN TO USE WHICH DECOMPOSITION
-------------------------------
  Prompt chaining (fixed pipeline)  -> predictable, enumerable aspects.
                                       "Review each file, then check integration."
  Dynamic decomposition (adaptive)  -> open-ended investigation where the next
                                       subtask depends on what you just found.
                                       "Add comprehensive tests to a legacy
                                       codebase": map structure, find high-impact
                                       areas, then plan as dependencies surface.
"""

import sys
import os
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway, text_of

# ---------------------------------------------------------------------------
# The fixture: 14 files, 14 planted bugs.
# BUG-8 is the cross-file one — orders.py calls apply_discount(qty, price) while
# pricing.py defines apply_discount(price, qty). Neither file is wrong alone.
# ---------------------------------------------------------------------------
FILES = {
    "inventory.py": '''
def reserve(stock, requested):
    """Reserve units from stock. Returns units actually reserved."""
    if requested > stock:          # BUG-1: should be >=; reserving all stock
        return 0                   # leaves the item at 0 without marking OOS
    return requested
''',
    "pricing.py": '''
def apply_discount(price, qty):
    """Apply a bulk discount. Signature is (price, qty)."""
    if qty > 10:
        return price * 0.9
    return price

def to_cents(amount):
    return int(amount * 100)       # BUG-2: truncates; 19.99*100 == 1998.9999 -> 1998
''',
    "cart.py": '''
def subtotal(items):
    total = 0
    for i in items:
        total += i["price"] * i["qty"]
    return round(total, 2)

def remove(items, sku):
    for idx, i in enumerate(items):
        if i["sku"] == sku:
            items.pop(idx)         # BUG-3: mutating while iterating
    return items
''',
    "tax.py": '''
RATES = {"CA": 0.0725, "NY": 0.04, "OR": 0.0}

def tax_for(state, subtotal):
    return subtotal * RATES[state]   # BUG-4: KeyError on unknown state
''',
    "shipping.py": '''
def cost(weight_kg, express=False):
    base = 5.0 + weight_kg * 1.2
    if express:
        base *= 2
    return base

def eta_days(distance_km):
    return distance_km / 0            # BUG-5: ZeroDivisionError, always
''',
    "orders.py": '''
import pricing, inventory

def place(item, stock):
    reserved = inventory.reserve(stock, item["qty"])
    # BUG-8 (CROSS-FILE): pricing.apply_discount is defined as (price, qty)
    # but is called here as (qty, price). Both files are internally consistent.
    unit = pricing.apply_discount(item["qty"], item["price"])
    return {"reserved": reserved, "unit_price": unit}
''',
    "auth.py": '''
import hashlib

def check(password, stored_hash):
    h = hashlib.md5(password.encode()).hexdigest()   # BUG-6: MD5 for passwords
    return h == stored_hash
''',
    "refunds.py": '''
def eligible(order):
    days = order["days_since_delivery"]
    return days < 30 or order["status"] == "damaged"   # BUG-7: `or` lets a
                                                       # 400-day-old damaged item
                                                       # through unconditionally
''',
}

# Six more files, matching the exam's "14 files" premise. The bugs here are
# deliberately subtler than the first seven — the kind that survive a skim. If
# attention dilution is real, this is the band where it shows: each one is
# individually findable, but finding all fourteen in a single pass requires
# sustained attention across the whole set.
FILES.update({
    "session.py": '''
import secrets, time

TTL = 3600

def new_token():
    return secrets.token_hex(16)

def is_valid(token, issued_at):
    # BUG-9: no constant-time comparison anywhere this is used, and the TTL
    # check uses < rather than <=, so a token is valid for TTL+1 seconds.
    return time.time() - issued_at < TTL

def revoke(store, token):
    if token in store:
        del store[token]
    # BUG-9b: silently succeeds for unknown tokens, so a caller cannot tell
    # "revoked" from "was never issued".
''',
    "pagination.py": '''
def page(items, page_num, per_page=20):
    # BUG-10: page_num is 1-indexed by the API contract but used 0-indexed here,
    # so page 1 silently skips the first 20 items.
    start = page_num * per_page
    return items[start:start + per_page]
''',
    "retry.py": '''
import time

def with_retry(fn, attempts=3, delay=1):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(delay)
    # BUG-11: swallows the exception type and re-raises a generic one, losing
    # the original traceback and making transient vs permanent indistinguishable.
    raise RuntimeError("all retries failed")
''',
    "csv_export.py": '''
def to_csv(rows):
    out = []
    for r in rows:
        # BUG-12: no escaping. A value containing a comma or a quote corrupts
        # every downstream column on that row.
        out.append(",".join(str(v) for v in r.values()))
    return "\\n".join(out)
''',
    "cache.py": '''
_CACHE = {}

def memoize(fn):
    def wrapper(*args, **kwargs):
        # BUG-13: kwargs are ignored in the cache key, so f(x, flag=True) and
        # f(x, flag=False) collide and return each other's results.
        key = (fn.__name__, args)
        if key not in _CACHE:
            _CACHE[key] = fn(*args, **kwargs)
        return _CACHE[key]
    return wrapper
''',
    "webhook.py": '''
import hashlib

def verify(payload, signature, secret):
    expected = hashlib.sha256(secret.encode() + payload).hexdigest()
    # BUG-14: == on a signature is a timing oracle. Use hmac.compare_digest.
    return expected == signature
''',
})

PLANTED = {
    "BUG-1": ("inventory.py", "off-by-one / boundary in reserve()", ["reserve", "off-by-one", ">=", "boundary", "equal"]),
    "BUG-2": ("pricing.py", "to_cents truncates float, loses a cent", ["to_cents", "truncat", "float", "round", "cent"]),
    "BUG-3": ("cart.py", "mutating list while iterating in remove()", ["mutat", "iterat", "pop", "while looping", "modify"]),
    "BUG-4": ("tax.py", "KeyError for unknown state", ["keyerror", "unknown state", "missing state", "get(", "raise"]),
    "BUG-5": ("shipping.py", "division by zero in eta_days", ["zerodivision", "divide by zero", "division by zero", "/ 0"]),
    "BUG-6": ("auth.py", "MD5 used for password hashing", ["md5", "password hash", "bcrypt", "insecure hash", "argon"]),
    "BUG-7": ("refunds.py", "`or` short-circuits the 30-day window", ["or ", "short-circuit", "precedence", "and", "30"]),
    "BUG-8": ("orders.py <-> pricing.py", "CROSS-FILE: apply_discount args swapped",
              ["swap", "argument order", "arg order", "reversed", "qty, price", "price, qty", "signature"]),
    "BUG-9": ("session.py", "TTL boundary: < instead of <=", ["ttl", "boundary", "<=", "off-by-one second", "expiry"]),
    "BUG-10": ("pagination.py", "1-indexed page used 0-indexed", ["page_num", "1-index", "0-index", "off-by-one", "skips"]),
    "BUG-11": ("retry.py", "swallows exception type/traceback", ["swallow", "traceback", "original exception", "runtimeerror", "loses"]),
    "BUG-12": ("csv_export.py", "no CSV escaping", ["escap", "csv inject", "quote", "comma", "delimiter"]),
    "BUG-13": ("cache.py", "kwargs ignored in cache key", ["kwargs", "cache key", "collide", "collision"]),
    "BUG-14": ("webhook.py", "signature compared with ==, timing oracle",
               ["timing", "compare_digest", "constant-time", "constant time", "hmac"]),
}

REVIEW_CRITERIA = """\
You are reviewing a pull request. Report every defect you find.

Report: logic errors, boundary/off-by-one errors, unhandled exceptions, security
issues, and incorrect cross-module usage.
Skip: formatting, naming preferences, missing type hints, and docstring style.

For each finding output one line in exactly this form:
FINDING | <file> | <one-sentence description>

Do not filter by severity or confidence — a later pass does that. Coverage is
your job here.
"""


def render(files: dict) -> str:
    return "\n".join(f"=== {name} ===\n{src}" for name, src in files.items())


def ask(c, prompt: str) -> str:
    r = c.messages.create(
        model=MODEL, max_tokens=16000, system=REVIEW_CRITERIA,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(r)


def score(findings_text: str) -> dict:
    """Match reported findings against the planted bug list by keyword."""
    low = findings_text.lower()
    return {
        bug_id: any(k.lower() in low for k in keywords)
        for bug_id, (_f, _d, keywords) in PLANTED.items()
    }


def report(label: str, found: dict):
    hits = sum(found.values())
    print(f"\n  {label}: {hits}/{len(PLANTED)} planted bugs found")
    for bug_id, ok in found.items():
        f, desc, _ = PLANTED[bug_id]
        print(f"    [{'FOUND' if ok else ' MISS'}] {bug_id}  {f:26s} {desc}")
    return hits


# ---------------------------------------------------------------------------
def single_pass(c):
    """Everything in one prompt. The architecture the exam is asking you to fix."""
    return ask(c, "Review this pull request.\n\n" + render(FILES))


def chained_passes(c):
    """
    Prompt chaining: one focused local pass per file, then ONE integration pass.

    Two properties matter:
      * Each local pass sees one file, so attention is not spread across eight.
      * The integration pass is given only the module INTERFACES, not full
        bodies — it is looking for cross-file mismatches, and full bodies would
        just reintroduce the dilution problem at a different layer.
    """
    local = []
    for name, src in FILES.items():
        out = ask(
            c,
            f"Review this single file for defects local to it. Do not speculate "
            f"about other modules.\n\n=== {name} ===\n{src}",
        )
        local.append(out)
        n = len(re.findall(r"^FINDING", out, re.M))
        print(f"    local pass: {name:16s} -> {n} finding(s)")

    interfaces = "\n".join(
        f"=== {name} ===\n"
        + "\n".join(
            l for l in src.splitlines()
            if l.strip().startswith(("def ", "import ", "from ")) or "apply_discount" in l or "reserve(" in l
        )
        for name, src in FILES.items()
    )
    integration = ask(
        c,
        "This is a cross-file integration pass. Below are the function signatures "
        "and the call sites across the changed modules. Ignore issues local to a "
        "single function body — another pass covers those. Look ONLY for "
        "cross-module problems: argument order or arity mismatches between a "
        "definition and its call site, wrong types crossing a boundary, and "
        "contract violations.\n\n" + interfaces,
    )
    print(f"    integration pass -> {len(re.findall(r'^FINDING', integration, re.M))} finding(s)")
    return "\n".join(local) + "\n" + integration


def main():
    c = client()
    banner("Task decomposition for review",
           "Task 1.6 / 4.6 — this is exam Sample Question 12")
    note(f"{len(FILES)} files, {len(PLANTED)} planted bugs (13 local + 1 cross-file). Model: {MODEL}")

    bad("Architecture A — single pass over all 8 files at once")
    out_single = single_pass(c)
    found_single = score(out_single)
    hits_single = report("single pass", found_single)
    show("Raw findings (truncated)", out_single[:900])

    good("Architecture B — per-file local passes + one integration pass")
    out_chained = chained_passes(c)
    found_chained = score(out_chained)
    hits_chained = report("chained passes", found_chained)

    section("Comparison")
    print(f"  single pass:    {hits_single}/{len(PLANTED)}")
    print(f"  chained passes: {hits_chained}/{len(PLANTED)}")
    gained = [b for b in PLANTED if found_chained[b] and not found_single[b]]
    lost = [b for b in PLANTED if found_single[b] and not found_chained[b]]
    if gained:
        print(f"  recovered by splitting: {', '.join(gained)}")
    if lost:
        print(f"  lost by splitting:      {', '.join(lost)}")
    if found_chained.get("BUG-8") and not found_single.get("BUG-8"):
        note("BUG-8 is the cross-file argument swap. The dedicated integration pass "
             "caught it; the single pass diluted it across fourteen files. This is the "
             "exact split the exam is asking for.")

    if hits_single == hits_chained == len(PLANTED):
        note("Both architectures found everything. Read that honestly: at this fixture "
             "size a current frontier model does NOT exhibit the attention dilution the "
             "exam describes. The conclusion is not that the exam is wrong — it is that "
             "this fixture sits below the failure's threshold. Real PRs carry hundreds "
             "of lines per file, unfamiliar domain logic, and bugs nobody planted on "
             "purpose.")
        print(
            "\n  What the exam actually tests here is the DIAGNOSIS, and that part is\n"
            "  model-independent. Given the stated symptoms — inconsistent depth, missed\n"
            "  obvious bugs, and CONTRADICTORY feedback that flags a pattern in one file\n"
            "  while approving identical code in another — the cause is attention\n"
            "  dilution and the remedy is splitting the passes.\n\n"
            "  That third symptom is the giveaway, and it is worth carrying into the exam:\n"
            "  a reviewer with adequate attention per file does not both approve and\n"
            "  reject the same pattern in a single pass. When you see that in your own\n"
            "  logs, you are past the threshold this fixture is below.\n\n"
            "  Note also what a bigger context window (distractor C) would do here:\n"
            "  nothing. Everything already fit. And consensus voting (distractor D) would\n"
            "  have made recall WORSE by discarding findings caught on only one run."
        )
    print(
        f"\n  Cost note: the chained architecture made {len(FILES) + 1} calls instead of 1.\n"
        "  That is the real trade-off — you buy attention quality with tokens, and you\n"
        "  should only buy it when you have evidence of dilution."
    )

    section("Choosing a decomposition pattern")
    print(
        "  Prompt chaining (what we just did) fits work whose aspects you can enumerate\n"
        "  IN ADVANCE: per-file review + integration pass; extract, then validate, then\n"
        "  format. The pipeline is fixed because the shape of the work is known.\n\n"
        "  Dynamic decomposition fits open-ended investigation, where each step's output\n"
        "  determines the next step's subtasks. 'Add comprehensive tests to this legacy\n"
        "  codebase' cannot be pipelined up front — you map the structure, identify the\n"
        "  high-impact untested paths, then build a prioritised plan that keeps changing\n"
        "  as you discover dependencies.\n\n"
        "  Picking the wrong one is a real cost: a fixed pipeline on an open-ended task\n"
        "  investigates the wrong things thoroughly; dynamic decomposition on a\n"
        "  predictable task just burns planning tokens re-deriving a known structure."
    )

    takeaway(
        "Single-pass over many files fails from ATTENTION DILUTION, not capacity.",
        "A bigger context window does not fix attention quality. (Distractor C.)",
        "Requiring 2-of-3 consensus SUPPRESSES real bugs — subtle ones are caught once.",
        "Correct split: per-file local passes + a separate cross-file integration pass.",
        "Chaining for enumerable aspects; dynamic decomposition for open-ended investigation.",
    )


if __name__ == "__main__":
    main()
