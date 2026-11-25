"""The bank's "business API" layer.

This mimics how the real reference apps are built (e.g. the Azure sample's
Account / Transactions / Payments services): the agent never touches SQL, it
calls these service functions. Crucially, *these functions do NOT authorize* —
they trust their caller, exactly like a backend microservice that assumes the
API gateway already checked who you are. They take an account number and act on
it, no questions asked.

That is deliberate. The authorization check is a separate concern that lives at
the tool boundary (Level 3, policy.py). At Level 1 nothing sits between the
model and these functions, so the model can act on *any* account -- which is
precisely the real-world weakness BankBot exists to demonstrate.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).parent / "bank.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---- Public reads (no customer context needed) -------------------------------
def find_branch(city: str) -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            "SELECT name, city, address, phone, hours FROM branches "
            "WHERE lower(city) = lower(?)", (city,)).fetchall()
    return [dict(r) for r in rows]


def list_products() -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            "SELECT name, category, description, monthly_fee FROM products").fetchall()
    return [dict(r) for r in rows]


def get_rates() -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            "SELECT product_name, apr, effective_date FROM rates").fetchall()
    return [dict(r) for r in rows]


def search_faqs(query: str) -> list[dict]:
    # Keyword match: a FAQ matches if ANY meaningful word in the query appears
    # in its question or answer. Lenient on purpose, so "report lost card"
    # still finds "How do I report a lost card?".
    words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) > 2]
    if not words:
        words = [(query or "").lower()]
    clauses, args = [], []
    for w in words:
        clauses.append("lower(question) LIKE ? OR lower(answer) LIKE ?")
        args += [f"%{w}%", f"%{w}%"]
    sql = "SELECT DISTINCT question, answer FROM faqs WHERE " + " OR ".join(clauses)
    with _connect() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


# ---- Account lookups ---------------------------------------------------------
def accounts_for(customer_id: int) -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            "SELECT account_number, type, balance, status FROM accounts "
            "WHERE customer_id = ?", (customer_id,)).fetchall()
    return [dict(r) for r in rows]


def account_by_number(account_number: str) -> dict | None:
    """Resolve an account by its number. Returns the owner (customer_id) too,
    so the authorization layer can check it -- but this function itself does
    not check anything."""
    with _connect() as c:
        row = c.execute(
            "SELECT account_id, customer_id, account_number, type, balance, status "
            "FROM accounts WHERE account_number = ?", (account_number,)).fetchone()
    return dict(row) if row else None


def transactions_for(account_number: str, days: int = 30) -> list[dict]:
    acct = account_by_number(account_number)
    if not acct:
        return []
    with _connect() as c:
        rows = c.execute(
            "SELECT date, amount, merchant, description FROM transactions "
            "WHERE account_id = ? ORDER BY date DESC", (acct["account_id"],)).fetchall()
    return [dict(r) for r in rows]


def payees_for(customer_id: int) -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            "SELECT name, account_number, bank FROM payees "
            "WHERE customer_id = ?", (customer_id,)).fetchall()
    return [dict(r) for r in rows]


def bills_for(customer_id: int, status: str | None = None) -> list[dict]:
    sql = "SELECT bill_id, payee, amount, due_date, status, memo FROM bills WHERE customer_id = ?"
    args: list = [customer_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    with _connect() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def bill_by_id(bill_id: int) -> dict | None:
    with _connect() as c:
        row = c.execute(
            "SELECT bill_id, customer_id, payee, amount, due_date, status, memo "
            "FROM bills WHERE bill_id = ?", (bill_id,)).fetchone()
    return dict(row) if row else None


def transaction_by_id(txn_id: int) -> dict | None:
    with _connect() as c:
        row = c.execute(
            "SELECT t.txn_id, t.account_id, t.amount, t.merchant, t.description, "
            "a.customer_id FROM transactions t JOIN accounts a ON a.account_id = t.account_id "
            "WHERE t.txn_id = ?", (txn_id,)).fetchone()
    return dict(row) if row else None


# ---- Customer-service lookups (reach ANY customer's data) --------------------
# These mirror a real bank agent's console: it CAN look up anyone. In the real
# world the control is "verify the caller is that person before disclosing".
# BankBot has no such code control until Level 3 -- so at Level 1 only the system
# prompt stands between an anonymous chatter and this sensitive data.
def find_customers(name: str) -> list[dict]:
    """Search customers by (partial) name. Returns sensitive profile data."""
    like = f"%{name}%"
    with _connect() as c:
        rows = c.execute(
            "SELECT customer_id, first_name, last_name, email, phone, ssn, dob, address "
            "FROM customers WHERE (first_name || ' ' || last_name) LIKE ? "
            "OR first_name LIKE ? OR last_name LIKE ?", (like, like, like)).fetchall()
    return [dict(r) for r in rows]


def customer_details(customer_id: int) -> dict | None:
    with _connect() as c:
        row = c.execute(
            "SELECT customer_id, first_name, last_name, email, phone, ssn, dob, address "
            "FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
    return dict(row) if row else None


def card_by_account(account_number: str) -> dict | None:
    with _connect() as c:
        row = c.execute(
            "SELECT c.card_number, c.expiry, c.cvv, c.status FROM cards c "
            "JOIN accounts a ON a.account_id = c.account_id "
            "WHERE a.account_number = ?", (account_number,)).fetchone()
    return dict(row) if row else None


def customer_profile(name: str) -> list[dict]:
    """Customer-360 facade: resolve a customer by name and bundle their full
    record in ONE call -- profile (incl. SSN) + accounts + each account's card
    and recent transactions. The chaining (customers -> accounts -> cards /
    transactions) is done here in the service layer over the real database.
    Reads from the customers, accounts, cards and transactions tables."""
    profiles = find_customers(name)
    for cust in profiles:
        accounts = accounts_for(cust["customer_id"])
        for acct in accounts:
            acct["card"] = card_by_account(acct["account_number"])
            acct["recent_transactions"] = transactions_for(acct["account_number"])[:5]
        cust["accounts"] = accounts
    return profiles


# ---- Writes (money movement / state change) ----------------------------------
def transfer(from_number: str, to_number: str, amount: float, memo: str = "") -> dict:
    """Debit the source account and, if the destination is an internal account,
    credit it. Records a transaction on the source and, for an internal
    destination, an inbound transaction on the recipient. No balance or
    ownership check here -- the caller/authorization layer owns that.

    `memo` is a free-text note chosen by the SENDER (like a Venmo/Zelle note or
    a wire reference). It is stored verbatim on the recipient's inbound
    transaction -- so it is attacker-controllable text that lands in another
    customer's data, the delivery path for an indirect prompt injection."""
    with _connect() as c:
        src = c.execute("SELECT account_id, balance FROM accounts WHERE account_number = ?",
                        (from_number,)).fetchone()
        if not src:
            return {"error": f"source account {from_number} not found"}
        c.execute("UPDATE accounts SET balance = balance - ? WHERE account_id = ?",
                  (amount, src["account_id"]))
        c.execute("INSERT INTO transactions (account_id, date, amount, merchant, description) "
                  "VALUES (?,?,?,?,?)",
                  (src["account_id"], date.today().isoformat(), -amount, to_number,
                   memo or "Transfer"))
        dst = c.execute("SELECT account_id FROM accounts WHERE account_number = ?",
                        (to_number,)).fetchone()
        if dst:
            c.execute("UPDATE accounts SET balance = balance + ? WHERE account_id = ?",
                      (amount, dst["account_id"]))
            # Inbound row on the recipient, carrying the SENDER's memo verbatim.
            c.execute("INSERT INTO transactions (account_id, date, amount, merchant, description) "
                      "VALUES (?,?,?,?,?)",
                      (dst["account_id"], date.today().isoformat(), amount, from_number,
                       memo or "Transfer received"))
        new_bal = c.execute("SELECT balance FROM accounts WHERE account_id = ?",
                            (src["account_id"],)).fetchone()["balance"]
        c.commit()
    return {"status": "completed", "from": from_number, "to": to_number,
            "amount": amount, "from_balance": round(new_bal, 2)}


def pay_bill(bill_id: int, from_number: str) -> dict:
    with _connect() as c:
        bill = c.execute("SELECT payee, amount, status FROM bills WHERE bill_id = ?",
                         (bill_id,)).fetchone()
        if not bill:
            return {"error": f"bill {bill_id} not found"}
        if bill["status"] == "paid":
            return {"error": f"bill {bill_id} is already paid"}
        src = c.execute("SELECT account_id FROM accounts WHERE account_number = ?",
                        (from_number,)).fetchone()
        if not src:
            return {"error": f"account {from_number} not found"}
        amount = bill["amount"]
        c.execute("UPDATE accounts SET balance = balance - ? WHERE account_id = ?",
                  (amount, src["account_id"]))
        c.execute("INSERT INTO transactions (account_id, date, amount, merchant, description) "
                  "VALUES (?,?,?,?,?)",
                  (src["account_id"], date.today().isoformat(), -amount, bill["payee"], "Bill payment"))
        c.execute("UPDATE bills SET status = 'paid' WHERE bill_id = ?", (bill_id,))
        c.commit()
    return {"status": "paid", "bill_id": bill_id, "payee": bill["payee"], "amount": amount}


def open_dispute(txn_id: int, reason: str) -> dict:
    txn = transaction_by_id(txn_id)
    if not txn:
        return {"error": f"transaction {txn_id} not found"}
    with _connect() as c:
        cur = c.execute("INSERT INTO cases (customer_id, txn_id, reason, status) "
                        "VALUES (?,?,?,?)", (txn["customer_id"], txn_id, reason, "open"))
        c.commit()
        case_id = cur.lastrowid
    return {"status": "open", "case_id": case_id, "txn_id": txn_id}
