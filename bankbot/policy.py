"""Level 3 enforcement: a deterministic policy layer that sits between the LLM
and the tools. The model may *request* any tool call; this code decides
allow/deny *before* anything executes, using rules only — never the model's
judgement. This is the "tool-execution control" the LinkedIn post argues for.

Two tools are guarded:
  - query_db(sql):   parsed with sqlglot; allowed only if it is a single
                     read-only SELECT and every table it touches is public.
  - read_file(path): allowed only if the resolved path is inside public_docs/.

Anything else is denied. Fail closed: if we can't prove a request is safe,
we refuse it.
"""
from __future__ import annotations

import os
from pathlib import Path

import services

# ---- The allowlist: the ONLY data a customer-facing assistant may read. ------
PUBLIC_TABLES = {"branches", "products", "rates", "faqs"}

# Private tables exist in the DB but must never be reachable via the tool.
# (customers, accounts, transactions, cards — balances, SSNs, card numbers…)

PUBLIC_DOCS_DIR = (Path(__file__).parent / "public_docs").resolve()
MAX_ROWS = 100


class PolicyError(Exception):
    """Raised when a tool call is denied. The message is safe to show the model."""


# ---------------------------------------------------------------------------
# customer-record access policy (the Level 3 tool-boundary check)
# ---------------------------------------------------------------------------
# Tools that return a customer's private record. Only the authenticated account
# holder may read their OWN record; every other case is denied here, in code,
# before the tool runs -- never on the model's judgement.
SENSITIVE_TOOLS = {"lookup_customers"}


def check_customer_access(tool_name: str, args: dict, caller_id: int | None) -> None:
    """Raise PolicyError unless this tool call is allowed.

    Non-sensitive tools always pass. For a sensitive lookup: deny if the caller
    is not authenticated; otherwise ALLOW only a lookup that resolves to the
    caller's OWN record. Every other authenticated case -- a different customer,
    a mix, OR a name that matches nobody -- raises the SAME denial, so the
    response cannot be used to tell which names are real customers (no
    enumeration oracle). Fail closed.
    """
    if tool_name not in SENSITIVE_TOOLS:
        return

    if caller_id is None:
        raise PolicyError(
            "Access denied: you must be signed in to view account information. "
            "Please log in or visit a branch with ID."
        )

    name = (args or {}).get("name", "") or ""
    matches = services.find_customers(name)
    own = bool(matches) and all(m["customer_id"] == caller_id for m in matches)
    if not own:
        raise PolicyError(
            "Access denied: you can only view your own account information."
        )


# ---------------------------------------------------------------------------
# query_db policy
# ---------------------------------------------------------------------------
def check_sql(sql: str) -> str:
    """Return a safe, LIMIT-capped SQL string, or raise PolicyError.

    Denies: multiple statements, anything that is not a SELECT (no INSERT/
    UPDATE/DELETE/DDL/PRAGMA/ATTACH), and any query that references a table
    not on the public allowlist — including via JOIN, subquery, CTE or UNION.
    """
    import sqlglot
    from sqlglot import exp
    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except Exception as e:  # unparseable -> fail closed
        raise PolicyError(f"Query rejected: could not parse SQL ({e}).")

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise PolicyError("Query rejected: exactly one statement is allowed.")

    stmt = statements[0]

    # Must be a read: a top-level SELECT (or a UNION of SELECTs).
    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise PolicyError("Query rejected: only read-only SELECT queries are allowed.")

    # Collect every real table the statement references.
    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    referenced = set()
    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue  # a reference to a WITH clause, not a base table
        referenced.add(name)

    if not referenced:
        raise PolicyError("Query rejected: no readable table referenced.")

    illegal = referenced - PUBLIC_TABLES
    if illegal:
        raise PolicyError(
            "Access denied: this assistant can only read public data "
            f"({', '.join(sorted(PUBLIC_TABLES))}). "
            f"Not permitted: {', '.join(sorted(illegal))}."
        )

    # Defense in depth: cap the number of rows returned.
    if isinstance(stmt, exp.Select) and not stmt.args.get("limit"):
        stmt = stmt.limit(MAX_ROWS)

    return stmt.sql(dialect="sqlite")


# ---------------------------------------------------------------------------
# read_file policy
# ---------------------------------------------------------------------------
def check_path(path: str) -> Path:
    """Return a resolved Path inside public_docs/, or raise PolicyError.

    Blocks absolute paths, traversal (../) and symlinks that escape the
    public directory, by resolving the real path and checking containment.
    """
    if not path or not isinstance(path, str):
        raise PolicyError("Access denied: a file name is required.")

    candidate = (PUBLIC_DOCS_DIR / path).resolve()
    try:
        candidate.relative_to(PUBLIC_DOCS_DIR)
    except ValueError:
        raise PolicyError("Access denied: only public handout files may be read.")

    if not candidate.is_file():
        raise PolicyError(f"File not found: {os.path.basename(path)}")

    return candidate


if __name__ == "__main__":
    # Quick self-test of the policy, no LLM or DB needed.
    allow = [
        "SELECT name, city FROM branches",
        "SELECT * FROM products WHERE category = 'savings'",
        "select p.name, r.apr from products p join rates r on r.product_name = p.name",
    ]
    deny = [
        "SELECT * FROM accounts",
        "SELECT first_name, ssn FROM customers",
        "SELECT b.city FROM branches b JOIN accounts a ON 1=1",
        "SELECT name FROM branches; DROP TABLE accounts;",
        "UPDATE accounts SET balance = 0",
        "WITH x AS (SELECT * FROM transactions) SELECT * FROM x",
        "SELECT name FROM branches UNION SELECT card_number FROM cards",
        "SELECT * FROM sqlite_master",
    ]
    print("== should ALLOW ==")
    for q in allow:
        try:
            print("  OK  ->", check_sql(q))
        except PolicyError as e:
            print("  !! wrongly denied:", q, "->", e)
    print("== should DENY ==")
    for q in deny:
        try:
            print("  !! wrongly allowed:", q, "->", check_sql(q))
        except PolicyError as e:
            print("  DENY ->", e)
