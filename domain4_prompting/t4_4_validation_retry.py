"""
Task 4.4 — Validation, retry, and feedback loops for extraction quality.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain4_prompting/t4_4_validation_retry.py

THE PATTERN
-----------
Retry-with-error-feedback: on a validation failure, send a follow-up containing
    (a) the original document,
    (b) the failed extraction, and
    (c) the SPECIFIC validation errors.
Not "that was wrong, try again" — the specific errors are what make the retry
converge instead of resampling.

THE LIMIT OF RETRY — this is the exam item people miss
------------------------------------------------------
Retries fix FORMAT and STRUCTURAL errors. They cannot fix ABSENT INFORMATION. If
the PO number lives in a purchase order you never supplied, no number of retries
will produce it, and each one costs money while raising the odds the model
eventually fabricates something to make the error go away.

So before retrying, classify the failure:
    format / structure    -> retry with the specific error   (converges)
    information absent    -> do NOT retry                     (escalate, or accept null)

SEMANTIC vs SYNTAX (carried over from Task 4.3)
-----------------------------------------------
Tool use with a schema removes syntax errors. Everything caught in this file is
SEMANTIC: values that do not sum, a date in the wrong field, a total that
contradicts its line items. Those need explicit validators.

SELF-CORRECTION BY SCHEMA DESIGN
--------------------------------
Extract `calculated_total` alongside `stated_total` and a `conflict_detected`
boolean, and the discrepancy surfaces in the extraction itself rather than
needing a separate pass.

FEEDBACK LOOPS
--------------
Add a `detected_pattern` field to every finding. When a human dismisses one, you
then know WHICH code construct produced the false positive, and can analyse
dismissal patterns systematically instead of re-reading transcripts.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

# ---------------------------------------------------------------------------
DOC_INCONSISTENT = """\
                 NORTHWIND SUPPLY CO
               invoice no.  NW-2291-B
                  dated 3rd Sept 2025

  Ergonomic chair AX-2      1 @ 1,200.00     1,200.00
  Delivery & assembly                          340.00
  Extended warranty                             95.00
                                   TOTAL   USD 1,735.00
Remit within thirty days.
"""

# The PO number is referenced but its VALUE lives in a document we never supply.
DOC_MISSING_INFO = """\
                 NORTHWIND SUPPLY CO
               invoice no.  NW-3410-A
                  dated 11 Oct 2025

  Standing desk, model SD-9   2 @ 640.00      1,280.00
                                   TOTAL   USD 1,280.00

Issued against the purchase order referenced in our agreement of 4 August;
see that document for the PO number and the agreed net terms.
"""


class LineItem(BaseModel):
    description: str
    amount_usd: float


class Invoice(BaseModel):
    invoice_number: str
    invoice_date: str = Field(description="ISO 8601 YYYY-MM-DD")
    total_usd: float
    line_items: list[LineItem]
    purchase_order_number: str | None = None
    payment_terms_days: int | None = None

    @field_validator("invoice_date")
    @classmethod
    def iso_date(cls, v):
        import re
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError(
                f"invoice_date must be ISO 8601 YYYY-MM-DD; got {v!r}. "
                "Convert the source format (e.g. '3rd Sept 2025' -> '2025-09-03')."
            )
        return v

    @model_validator(mode="after")
    def totals_reconcile(self):
        # A SEMANTIC check. The JSON is valid and schema-compliant either way.
        s = round(sum(i.amount_usd for i in self.line_items), 2)
        if abs(s - self.total_usd) > 0.01:
            raise ValueError(
                f"line items sum to {s} but total_usd is {self.total_usd}. "
                "Either a line item is missing/misread, or the document itself is "
                "internally inconsistent. If the document is inconsistent, keep the "
                "STATED total and list every line item you can actually see."
            )
        return self


TOOL = {
    "name": "extract_invoice",
    "description": "Extract structured fields from an invoice.",
    "input_schema": {
        "type": "object",
        "properties": {
            "invoice_number": {"type": "string"},
            "invoice_date": {"type": "string", "description": "ISO 8601 YYYY-MM-DD"},
            "total_usd": {"type": "number"},
            "line_items": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"description": {"type": "string"},
                                         "amount_usd": {"type": "number"}},
                          "required": ["description", "amount_usd"]},
            },
            "purchase_order_number": {
                "type": ["string", "null"],
                "description": "Null if the document does not state one. Do not infer.",
            },
            "payment_terms_days": {
                "type": ["integer", "null"],
                "description": "Null if not stated. 'thirty days' -> 30.",
            },
        },
        "required": ["invoice_number", "invoice_date", "total_usd", "line_items"],
    },
}


def call_extract(c, messages):
    r = c.messages.create(
        model=MODEL, max_tokens=8000, tools=[TOOL],
        tool_choice={"type": "tool", "name": "extract_invoice"},
        system="Extract the invoice fields. Follow every field description exactly.",
        messages=messages,
    )
    calls = [b for b in r.content if b.type == "tool_use"]
    return (calls[0].input if calls else None), r


def validate(payload):
    """Return (ok, errors: list[str])."""
    try:
        Invoice(**payload)
        return True, []
    except ValidationError as exc:
        return False, [
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
            for e in exc.errors()
        ]


def extract_with_retry(c, doc, max_retries=2, label=""):
    """
    The retry-with-error-feedback loop.

    Returns (payload, attempts, final_errors).
    """
    messages = [{"role": "user", "content": doc}]
    payload, errors = None, []

    for attempt in range(1, max_retries + 2):
        payload, response = call_extract(c, messages)
        if payload is None:
            return None, attempt, ["no tool call returned"]

        ok, errors = validate(payload)
        print(f"    attempt {attempt}: {'VALID' if ok else 'INVALID'}"
              f"{'' if ok else '  ' + errors[0][:100]}")
        if ok:
            return payload, attempt, []

        if attempt > max_retries:
            break

        # The three ingredients. Note (b) and (c) — the failed extraction and the
        # SPECIFIC errors. Without them this is just resampling.
        messages = [
            {"role": "user", "content": doc},                                  # (a)
            {"role": "assistant", "content": response.content},                # (b)
            {"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": next(b.id for b in response.content if b.type == "tool_use"),
                "content": json.dumps({
                    "validation_failed": True,
                    "errors": errors,                                          # (c)
                    "instruction": "Correct ONLY the fields named in errors. Keep "
                                   "every other field as you extracted it. If the "
                                   "required information is genuinely not present in "
                                   "the document, set the field to null and say so.",
                }),
                "is_error": True,
            }]},
        ]

    return payload, attempt, errors


def main():
    c = client()
    banner("Validation, retry, and feedback loops", "Task 4.4")

    # -- 1. Retry that converges --------------------------------------------
    section("1. A format/structure failure — retry converges")
    print("  Document has a non-ISO date ('3rd Sept 2025') and line items that do not\n"
          "  sum to the stated total (1200+340+95 = 1635, stated 1735).")
    payload, attempts, errs = extract_with_retry(c, DOC_INCONSISTENT)
    if payload:
        show("Final extraction", json.dumps(payload, indent=2)[:700])
    print(f"  attempts: {attempts}   remaining errors: {errs or 'none'}")
    if errs:
        note("Still failing — and that is the RIGHT outcome here. The document really "
             "is internally inconsistent: no extraction can make 1635 equal 1735. The "
             "validator is telling you about the SOURCE, not about the model. Route "
             "this to human review rather than retrying it to death.")
    else:
        note("Converged. The date normalised because the error message said exactly "
             "what was wrong and how to fix it — that specificity is what makes a "
             "retry converge rather than resample.")

    # -- 2. Retry that cannot converge --------------------------------------
    section("2. An information-absent failure — retry is futile")
    bad("Retrying for a PO number that is not in the document")
    print("  The invoice REFERENCES a purchase order but its number lives in another\n"
          "  document we never supplied.")

    strict_tool = json.loads(json.dumps(TOOL))
    strict_tool["input_schema"]["required"].append("purchase_order_number")
    strict_tool["input_schema"]["properties"]["purchase_order_number"] = {
        "type": "string", "description": "The purchase order number."
    }

    messages = [{"role": "user", "content": DOC_MISSING_INFO}]
    for attempt in range(1, 4):
        r = c.messages.create(
            model=MODEL, max_tokens=4000, tools=[strict_tool],
            tool_choice={"type": "tool", "name": "extract_invoice"},
            system="Extract the invoice fields.", messages=messages,
        )
        calls = [b for b in r.content if b.type == "tool_use"]
        po = calls[0].input.get("purchase_order_number") if calls else None
        print(f"    attempt {attempt}: purchase_order_number = {po!r}")
        messages = [
            {"role": "user", "content": DOC_MISSING_INFO},
            {"role": "assistant", "content": r.content},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": calls[0].id,
                "content": json.dumps({"validation_failed": True,
                                       "errors": ["purchase_order_number is required"]}),
                "is_error": True,
            }]},
        ]
    note("Three attempts, three fabricated or placeholder values, and the information "
         "was never in the document. Each retry costs tokens and increases the chance "
         "the model produces something plausible-looking that a downstream system will "
         "trust. This is the exam's point about the LIMITS of retry.")

    good("The correct handling: nullable field, no retry, route for human review")
    payload2, attempts2, errs2 = extract_with_retry(c, DOC_MISSING_INFO)
    if payload2:
        print(f"    purchase_order_number: {payload2.get('purchase_order_number')!r}")
        print(f"    payment_terms_days:    {payload2.get('payment_terms_days')!r}")
    note("null is the honest answer, it validates, and it is distinguishable from a "
         "real value. The pipeline can route null PO numbers to a human without "
         "guessing which of the extracted strings were invented.")

    section("Classifying a validation failure BEFORE retrying")
    print(
        "    RETRYABLE (retry with the specific error):\n"
        "      - wrong date/number format\n"
        "      - a field placed under the wrong key\n"
        "      - a missing array element that IS visible in the document\n"
        "      - schema-shape violations\n\n"
        "    NOT RETRYABLE (stop; escalate or accept null):\n"
        "      - the information only exists in a document you did not supply\n"
        "      - the source document is internally inconsistent\n"
        "      - the source is illegible or truncated\n\n"
        "    A retry loop with no such classification burns budget on cases that\n"
        "    cannot converge, and its worst outcome is not failure — it is eventual\n"
        "    fabricated success."
    )

    section("Feedback loops: detected_pattern")
    print(
        "  Add a `detected_pattern` field to every structured finding, naming the code\n"
        "  construct that triggered it:\n\n"
        '      {"issue": "...", "severity": "major",\n'
        '       "detected_pattern": "float_arithmetic_on_currency"}\n\n'
        "  When developers dismiss findings, you can then aggregate by pattern:\n\n"
        "      unchecked_dict_access      dismissed 47/51  ->  92% FP, disable & rewrite\n"
        "      float_arithmetic_on_money  dismissed  2/38  ->   5% FP, keep\n\n"
        "  Without the field you know your overall false-positive rate and nothing\n"
        "  about which rule is causing it — so you cannot act on it. See the CI schema\n"
        "  in domain3_claude_code/t3_6_ci_pipeline.py, which carries this field."
    )

    takeaway(
        "Retry payload = original document + failed extraction + SPECIFIC errors.",
        "Classify before retrying: format/structure converges, absent information never will.",
        "A retry loop's worst outcome is fabricated success, not failure.",
        "Nullable fields + no retry + human review is the correct absent-info handling.",
        "Schema-level checks (calculated vs stated total) catch SEMANTIC errors early.",
        "detected_pattern turns 'we have false positives' into 'THIS rule is at 92% FP'.",
    )


if __name__ == "__main__":
    main()
