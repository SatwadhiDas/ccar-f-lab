"""
Task 4.3 — Enforce structured output using tool use and JSON schemas.

Needs: ANTHROPIC_API_KEY (raw Claude API)
Run:   python domain4_prompting/t4_3_structured_output.py

WHAT THE EXAM TESTS
-------------------
  * tool_use with a JSON schema is the reliable way to get schema-compliant
    output. It eliminates JSON SYNTAX errors entirely.
  * It does NOT eliminate SEMANTIC errors. A response can be perfectly valid JSON,
    perfectly schema-compliant, and still have line items that do not sum to the
    stated total, or a value in the wrong field. This distinction is its own exam
    item and it feeds Task 4.4.
  * Fields that may legitimately be absent from the source must be NULLABLE.
    Marking them required pressures the model to fabricate a value to satisfy the
    schema — the schema stops being a validator and becomes a fabrication prompt.
  * Enums need an escape hatch: "unclear" for ambiguity, "other" + a detail
    string for extensibility. A closed enum forces a wrong choice.
  * tool_choice "any" guarantees a tool call when several extraction schemas
    exist and you do not know the document type.
  * Forced tool_choice guarantees a specific tool runs first (extract_metadata
    before enrichment), with subsequent steps in follow-up turns.
  * Format normalisation rules go in the PROMPT, alongside the strict schema. The
    schema constrains shape; the prompt handles messy source formatting.

A NOTE ON THE CURRENT API
-------------------------
The exam is written around tool_use-for-structured-output, and that is the answer
to give on the exam. The current API also offers dedicated structured outputs —
`output_config={"format": {"type": "json_schema", ...}}`, and in the Python SDK
`client.messages.parse(output_format=<pydantic model>)`, plus `strict: true` on a
tool definition. The last section here demonstrates those so you know both. If an
exam item asks how to guarantee schema-compliant output, "tool use with a JSON
schema" is the expected answer.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import MODEL, client, banner, bad, good, note, section, show, takeaway

# ---------------------------------------------------------------------------
# A messy invoice. Note what is DELIBERATELY ABSENT: no PO number, no tax id,
# no payment terms. And note the arithmetic: 1200 + 340 + 95 = 1635, but the
# document states 1735. That discrepancy is the semantic-error demo.
# ---------------------------------------------------------------------------
INVOICE = """\
                    NORTHWIND SUPPLY CO
                  invoice no.  NW-2291-B
                     dated 3rd Sept 2025

Bill to:  Acme Storefront Ltd, 14 Harbour Rd

  Ergonomic chair, model AX-2         1 @ 1,200.00      1,200.00
  Delivery & assembly                                     340.00
  Extended warranty (24mo)                                 95.00
                                              TOTAL   USD 1,735.00

Remit within thirty days of receipt.
"""

EXTRACT_SCHEMA_STRICT_REQUIRED = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": "string"},
        "invoice_date": {"type": "string", "description": "ISO 8601, YYYY-MM-DD"},
        "vendor": {"type": "string"},
        "purchase_order_number": {"type": "string"},
        "vendor_tax_id": {"type": "string"},
        "payment_terms_days": {"type": "integer"},
        "total_usd": {"type": "number"},
    },
    # Everything required — including three fields the document does not contain.
    "required": ["invoice_number", "invoice_date", "vendor",
                 "purchase_order_number", "vendor_tax_id",
                 "payment_terms_days", "total_usd"],
}

EXTRACT_SCHEMA_NULLABLE = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": "string"},
        "invoice_date": {"type": "string",
                         "description": "ISO 8601 YYYY-MM-DD. Normalise any source "
                                        "format: '3rd Sept 2025' -> '2025-09-03'."},
        "vendor": {"type": "string"},
        # The three genuinely-optional fields are nullable AND their descriptions
        # tell the model explicitly what to do when absent. Both halves matter.
        "purchase_order_number": {
            "type": ["string", "null"],
            "description": "The buyer's PO number. Return null if the document does "
                           "not contain one. Do NOT infer or construct it.",
        },
        "vendor_tax_id": {
            "type": ["string", "null"],
            "description": "Vendor tax/VAT id. Return null if absent.",
        },
        "payment_terms_days": {
            "type": ["integer", "null"],
            "description": "Net payment days. 'thirty days' -> 30. Null if not stated.",
        },
        "total_usd": {"type": "number", "description": "Stated total, digits only."},
        # Self-correction fields (Task 4.4): extract BOTH the stated total and the
        # sum you compute, so a discrepancy is detectable without a second call.
        "calculated_total_usd": {
            "type": "number",
            "description": "Sum of the individual line items you extracted.",
        },
        "conflict_detected": {
            "type": "boolean",
            "description": "True if calculated_total_usd differs from total_usd.",
        },
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "amount_usd": {"type": "number"},
                    # Enum with the two escape hatches the exam names.
                    "category": {
                        "type": "string",
                        "enum": ["goods", "service", "warranty", "shipping",
                                 "tax", "discount", "unclear", "other"],
                        "description": "Use 'unclear' when the document is ambiguous. "
                                       "Use 'other' for a real category not in this "
                                       "list, and put it in category_detail.",
                    },
                    "category_detail": {
                        "type": ["string", "null"],
                        "description": "Required when category is 'other'; else null.",
                    },
                },
                "required": ["description", "amount_usd", "category"],
            },
        },
    },
    "required": ["invoice_number", "invoice_date", "vendor", "total_usd",
                 "calculated_total_usd", "conflict_detected", "line_items"],
}


def extract(c, schema, tool_name="extract_invoice", system=None, doc=INVOICE):
    tool = {
        "name": tool_name,
        "description": "Extract structured fields from an invoice document.",
        "input_schema": schema,
    }
    r = c.messages.create(
        model=MODEL, max_tokens=8000, tools=[tool],
        tool_choice={"type": "tool", "name": tool_name},
        system=system or "Extract the requested fields from the document.",
        messages=[{"role": "user", "content": doc}],
    )
    calls = [b for b in r.content if b.type == "tool_use"]
    return calls[0].input if calls else None


def main():
    c = client()
    banner("Structured output via tool use", "Task 4.3 — schemas, nullability, enums")

    # -- 1. Required fields cause fabrication --------------------------------
    section("1. Required vs nullable: the fabrication trap")
    print("  The invoice contains NO purchase order number, NO tax id, NO explicit\n"
          "  net-days figure. Watch what each schema does about that.")

    bad("Schema marks all fields required")
    out = extract(c, EXTRACT_SCHEMA_STRICT_REQUIRED)
    show("Extracted", json.dumps(out, indent=2))
    fabricated = [k for k in ["purchase_order_number", "vendor_tax_id"]
                  if out and out.get(k) not in (None, "", "N/A", "null", "none", "None")]
    if fabricated:
        note(f"Fabricated: {fabricated}. The output is perfectly schema-valid — and "
             "wrong. Required-ness became pressure to invent, and a downstream system "
             "now has a PO number that does not exist.")
    else:
        note("It emitted placeholder strings ('N/A', '') rather than inventing "
             "plausible identifiers. Still bad: downstream cannot distinguish 'absent' "
             "from 'the literal string N/A', and the type says string, so nothing "
             "validates it away.")

    good("Schema marks genuinely-optional fields nullable, with instructions")
    out2 = extract(c, EXTRACT_SCHEMA_NULLABLE)
    show("Extracted", json.dumps(out2, indent=2))
    if out2:
        nulls = [k for k in ["purchase_order_number", "vendor_tax_id"]
                 if out2.get(k) is None]
        print(f"  correctly null: {nulls}")
        print(f"  date normalised: {out2.get('invoice_date')!r}  (source: '3rd Sept 2025')")
        print(f"  terms normalised: {out2.get('payment_terms_days')!r}  (source: 'thirty days')")
        note("null means absent, and it is distinguishable from every legitimate "
             "value. That is the whole reason to make a field nullable rather than "
             "required.")

    # -- 2. Semantic errors survive a valid schema ---------------------------
    section("2. Schemas eliminate SYNTAX errors, not SEMANTIC ones")
    if out2:
        stated = out2.get("total_usd")
        computed = out2.get("calculated_total_usd")
        items = out2.get("line_items") or []
        actual_sum = round(sum(i.get("amount_usd", 0) for i in items), 2)
        print(f"  line items:        {[i.get('amount_usd') for i in items]}")
        print(f"  sum of line items: {actual_sum}")
        print(f"  stated total:      {stated}")
        print(f"  model's computed:  {computed}")
        print(f"  conflict_detected: {out2.get('conflict_detected')}")
        if stated and actual_sum and abs(stated - actual_sum) > 0.01:
            note(f"The document is internally inconsistent: items sum to {actual_sum} "
                 f"but it states {stated}. Every field above is schema-valid. No JSON "
                 "validator on earth catches this — which is exactly the exam's point "
                 "about semantic vs syntax errors.")
            if out2.get("conflict_detected"):
                note("Because the schema asked for calculated_total_usd ALONGSIDE "
                     "total_usd and a conflict_detected flag, the discrepancy is "
                     "surfaced by the extraction itself. This is the self-correction "
                     "validation flow from Task 4.4 — build the check into the schema "
                     "rather than bolting it on afterwards.")

    # -- 3. Enum escape hatches ---------------------------------------------
    section("3. Enum escape hatches")
    if out2:
        for i in (out2.get("line_items") or []):
            print(f"    {i.get('description','')[:38]:40s} -> {i.get('category')}"
                  f"{'  detail=' + str(i.get('category_detail')) if i.get('category_detail') else ''}")
    weird = INVOICE.replace("Extended warranty (24mo)", "Carbon offset levy (voluntary)")
    out3 = extract(c, EXTRACT_SCHEMA_NULLABLE, doc=weird)
    if out3:
        for i in (out3.get("line_items") or []):
            if i.get("category") in ("other", "unclear"):
                print(f"    escape hatch used: {i.get('description')!r} -> "
                      f"{i.get('category')} / {i.get('category_detail')!r}")
    note("A closed enum with no 'other' forces the model to pick a wrong category for "
         "anything you did not anticipate — and you cannot tell afterwards which "
         "'goods' were really something else. 'unclear' covers ambiguity; 'other' + "
         "detail covers extensibility.")

    # -- 4. tool_choice for unknown document type ----------------------------
    section("4. tool_choice: 'any' when the document type is unknown")
    receipt_tool = {
        "name": "extract_receipt",
        "description": "Extract from a RETAIL RECEIPT: merchant, items, total, tender type.",
        "input_schema": {"type": "object",
                         "properties": {"merchant": {"type": "string"},
                                        "total_usd": {"type": "number"}},
                         "required": ["merchant", "total_usd"]},
    }
    invoice_tool = {
        "name": "extract_invoice",
        "description": "Extract from a B2B INVOICE: invoice number, vendor, bill-to, total.",
        "input_schema": {"type": "object",
                         "properties": {"invoice_number": {"type": "string"},
                                        "vendor": {"type": "string"}},
                         "required": ["invoice_number", "vendor"]},
    }
    r = c.messages.create(
        model=MODEL, max_tokens=4000, tools=[receipt_tool, invoice_tool],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": INVOICE}],
    )
    chosen = [b.name for b in r.content if b.type == "tool_use"]
    print(f"  tool_choice='any' -> model selected: {chosen}  (stop_reason={r.stop_reason})")
    note("'any' guarantees SOME tool runs, so the pipeline always gets structured "
         "output, while leaving the schema choice to the model. That is the right mode "
         "when you have several extraction schemas and do not know the type up front. "
         "'auto' would permit a conversational reply and break the parser.")

    section("5. Forced tool_choice for ordering")
    print(
        '  tool_choice={"type": "tool", "name": "extract_metadata"} guarantees THAT\n'
        "  tool runs first — the enforcement mechanism when metadata must precede\n"
        "  enrichment. It applies to ONE request, so the enrichment step happens in a\n"
        "  follow-up turn. Compare with Task 1.4: a hook gates a call across the whole\n"
        "  conversation; forced tool_choice orders a single request."
    )

    # -- 6. Current API ------------------------------------------------------
    section("6. The current API's dedicated structured outputs (beyond the exam)")
    try:
        from pydantic import BaseModel

        class Invoice(BaseModel):
            invoice_number: str
            vendor: str
            total_usd: float
            purchase_order_number: str | None = None

        parsed = c.messages.parse(
            model=MODEL, max_tokens=4000, output_format=Invoice,
            messages=[{"role": "user", "content": INVOICE}],
        )
        show("client.messages.parse() -> validated Pydantic object",
             repr(parsed.parsed_output))
        note("output_config.format / messages.parse() constrains the RESPONSE itself "
             "rather than routing through a tool, and hands back a validated object. "
             "Also available: strict=True on a tool definition (requires "
             "additionalProperties: false), which hardens tool-parameter validation. "
             "On the exam, answer 'tool use with a JSON schema'; in code written today, "
             "prefer these.")
    except Exception as exc:
        note(f"Structured-output demo skipped: {type(exc).__name__}: {str(exc)[:180]}")

    takeaway(
        "tool_use + JSON schema kills SYNTAX errors. Semantic errors survive intact.",
        "Optional-in-the-source fields MUST be nullable, or the model fabricates.",
        "Say 'return null if absent, do not infer' in the field description too.",
        "Enums need 'unclear' (ambiguity) and 'other' + detail (extensibility).",
        "tool_choice 'any' = guaranteed structured output when the doc type is unknown.",
        "Forced tool_choice enforces ordering for ONE request; continue in follow-ups.",
        "Put format-normalisation rules in the PROMPT; the schema only fixes shape.",
        "Extract calculated_total alongside stated_total to make discrepancies visible.",
    )


if __name__ == "__main__":
    main()
