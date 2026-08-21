"""
A real stdio MCP server for the Domain 2 exercises.

Run standalone (it will just wait on stdin — that is correct):
    python domain2_tools_mcp/mcp_server/support_server.py

It is normally launched as a subprocess by an MCP client. See ../.mcp.json for the
project-scoped configuration, and ../t2_4_mcp_integration.py for a client that
connects to it.

WHY THIS SERVER EXPOSES BOTH TOOLS AND RESOURCES
------------------------------------------------
The exam distinguishes them, and the distinction is easy to lose:

  TOOLS      are ACTIONS the agent chooses to invoke. Each call is a round trip
             and its result lands in the context window.

  RESOURCES  are CONTENT CATALOGUES the client can surface to the agent without
             an exploratory tool call. The exam's examples: issue summaries,
             documentation hierarchies, database schemas.

The failure mode resources fix: an agent that must call list_tables, then
describe_table eight times, just to learn the shape of a database before it can
ask a single real question. That is eight round trips and eight results in
context, all of it structural rather than substantive. Exposing the schema as a
resource gives the agent visibility up front.

Note also the deliberately verbose tool descriptions. The exam calls this out
directly: if an MCP tool's description is thin, the agent will prefer a built-in
tool (Grep, Read) that it understands better, even when your MCP tool is more
capable. Description quality is an adoption problem, not just a routing one.
"""

import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("support")

# ---------------------------------------------------------------------------
# Fake backend
# ---------------------------------------------------------------------------
TICKETS = {
    "TK-1001": {"id": "TK-1001", "customer_id": "CUST-4417", "subject": "Chair arrived damaged",
                "status": "open", "priority": "high", "opened": "2025-08-02"},
    "TK-1002": {"id": "TK-1002", "customer_id": "CUST-4417", "subject": "Refund not received",
                "status": "open", "priority": "urgent", "opened": "2025-08-09"},
    "TK-0917": {"id": "TK-0917", "customer_id": "CUST-9002", "subject": "Address change",
                "status": "closed", "priority": "low", "opened": "2025-06-11"},
}

SCHEMA = {
    "tickets": {
        "columns": {
            "id": "TEXT PRIMARY KEY (format TK-####)",
            "customer_id": "TEXT (format CUST-####, FK -> customers.id)",
            "subject": "TEXT",
            "status": "TEXT ENUM('open','pending','closed')",
            "priority": "TEXT ENUM('low','normal','high','urgent')",
            "opened": "DATE",
        },
        "indexes": ["customer_id", "status"],
        "row_count": 41_882,
    },
    "customers": {
        "columns": {
            "id": "TEXT PRIMARY KEY (format CUST-####)",
            "email": "TEXT UNIQUE",
            "tier": "TEXT ENUM('standard','silver','gold')",
        },
        "row_count": 12_004,
    },
}


# ---------------------------------------------------------------------------
# TOOLS — actions
# ---------------------------------------------------------------------------
@mcp.tool()
def find_tickets(customer_id: str, status: str = "any") -> str:
    """Find support tickets belonging to one customer.

    Searches the tickets table by customer_id and optionally filters by status.
    Returns a JSON array of ticket records: id, subject, status, priority, opened.

    Accepts: customer_id in CUST-#### form. status is one of
    open / pending / closed / any (default any).

    Use this for: "what tickets does CUST-4417 have open?", "has this customer
    contacted us before?", "show me their support history".

    Edge cases: an unknown customer_id returns an empty array with
    status "ok" — that is a successful search with no matches, NOT an error.
    A backend failure returns an object with isError set instead.

    BOUNDARY: this searches by CUSTOMER. To fetch one known ticket by its id,
    use get_ticket, which is cheaper and returns the full body.
    """
    matches = [t for t in TICKETS.values() if t["customer_id"] == customer_id]
    if status != "any":
        matches = [t for t in matches if t["status"] == status]
    # Note the shape: a successful empty search is not an error (Task 2.2).
    return json.dumps({"status": "ok", "matches": matches, "searched": len(TICKETS)})


@mcp.tool()
def get_ticket(ticket_id: str) -> str:
    """Fetch one support ticket by its exact id.

    Returns the full ticket record. Accepts a ticket id in TK-#### form.

    Use this for: "what's in TK-1001?", "show me ticket 1002".

    Edge cases: an unknown id returns a structured validation error with
    isRetryable false — confirm the id rather than retrying.

    BOUNDARY: resolves one KNOWN id. To discover which tickets exist for a
    customer, use find_tickets.
    """
    t = TICKETS.get(ticket_id)
    if not t:
        return json.dumps({
            "isError": True, "errorCategory": "validation", "isRetryable": False,
            "message": f"No ticket with id {ticket_id!r}. Confirm the ticket number.",
        })
    return json.dumps(t)


# ---------------------------------------------------------------------------
# RESOURCES — content catalogues
# ---------------------------------------------------------------------------
@mcp.resource("schema://support")
def support_schema() -> str:
    """The support database schema: tables, columns, types, indexes, row counts.

    Exposed as a resource rather than a tool precisely because it is reference
    content, not an action. The agent can consult it to write a correct query on
    the first attempt instead of discovering the shape through trial and error.
    """
    return json.dumps(SCHEMA, indent=2)


@mcp.resource("catalog://open-tickets")
def open_ticket_catalog() -> str:
    """A compact index of currently-open tickets: id, customer, subject, priority.

    This is the "issue summaries" case from the exam. The agent gets visibility
    into what exists without calling find_tickets once per customer to find out.
    """
    return json.dumps(
        [{"id": t["id"], "customer_id": t["customer_id"],
          "subject": t["subject"], "priority": t["priority"]}
         for t in TICKETS.values() if t["status"] == "open"],
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()
