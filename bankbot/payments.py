"""Write-side control: a money transfer is never executed on the model's
say-so.

transfer_money (a tool the model can call) does NOT move money. It only PARKS a
pending action and hands back a confirm_id. The transfer executes only when the
account holder confirms it at the separate /confirm endpoint, which

  - is NOT a tool (the model cannot call it, so a prompt injection cannot reach
    it), and
  - requires the owner's own login token (the caller resolved from it must match
    the caller who parked the action).

So the execute switch lives outside the model's control loop. Knowing a
confirm_id is not enough: without the owner's token, /confirm refuses it.

This is the "confused-deputy" defense for writes: authorization (is this the
owner?) passes, and there is nothing sensitive to mask, so an out-of-band
confirmation is what stops an injected action. Demo-level, in-memory.
"""
from __future__ import annotations

import json
import secrets
import time

import services

# confirm_id -> {caller_id, to, amount, ts}. In-memory; resets on restart.
_PENDING: dict[str, dict] = {}
TTL_SECONDS = 600  # a parked transfer expires after 10 minutes


def _valid_amount(amount):
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _source_account(caller_id: int | None) -> str | None:
    """The caller's own account the transfer debits (prefer checking)."""
    accts = services.accounts_for(caller_id) if caller_id is not None else []
    for a in accts:
        if a.get("type") == "checking":
            return a.get("account_number")
    return accts[0].get("account_number") if accts else None


def execute_transfer(caller_id: int | None, to: str = "", amount=0, **_ignore) -> str:
    """Below Level 4 there is NO confirmation gate: the transfer executes on the
    model's say-so. It REALLY moves money -- debits the caller's account and
    records a transaction -- so an injected transfer that the model is talked
    into goes straight through, and the effect is verifiable in the balance."""
    if caller_id is None:
        return json.dumps({"error": "You must be signed in to transfer money."})
    amount = _valid_amount(amount)
    if amount is None:
        return json.dumps({"error": "invalid transfer amount"})
    src = _source_account(caller_id)
    if not src:
        return json.dumps({"error": "no source account on file"})
    return json.dumps(services.transfer(src, str(to), amount))


def create_pending(caller_id: int | None, to: str = "", amount=0, **_ignore) -> str:
    """Called by the transfer_money tool. Parks the action and returns a JSON
    the model may relay to the user. A write needs an identity, so an
    unauthenticated caller is refused here."""
    if caller_id is None:
        return json.dumps({"error": "You must be signed in to transfer money."})
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return json.dumps({"error": "invalid transfer amount"})
    if amount <= 0:
        return json.dumps({"error": "transfer amount must be positive"})

    confirm_id = secrets.token_urlsafe(8)
    _PENDING[confirm_id] = {"caller_id": caller_id, "to": str(to),
                            "amount": amount, "ts": time.time()}
    return json.dumps({
        "status": "pending_confirmation",
        "confirm_id": confirm_id,
        "summary": (f"A transfer of ${amount:.2f} to {to} has been prepared but NOT "
                    f"sent. For security it must be confirmed by the account holder "
                    f"via /confirm (confirm_id {confirm_id}) before any money moves."),
    })


def confirm(confirm_id: str, caller_id: int | None) -> dict:
    """Called ONLY by the /confirm endpoint. Possession of a confirm_id is not
    enough: the caller (resolved from their own login token) must be the owner
    who parked the action. Single-use and time-limited."""
    p = _PENDING.get(confirm_id or "")
    if not p:
        return {"ok": False, "error": "no such pending transfer (invalid or already used)"}
    if p["caller_id"] != caller_id:
        # Covers both an anonymous caller and a different signed-in customer.
        return {"ok": False, "error": "this transfer can only be confirmed by its owner"}
    if time.time() - p["ts"] > TTL_SECONDS:
        _PENDING.pop(confirm_id, None)
        return {"ok": False, "error": "this transfer has expired"}

    _PENDING.pop(confirm_id)  # single-use
    # Confirmed out-of-band by the owner -> now actually move the money.
    src = _source_account(p["caller_id"])
    if not src:
        return {"ok": False, "error": "no source account on file"}
    res = services.transfer(src, p["to"], p["amount"])
    if res.get("status") != "completed":
        return {"ok": False, "error": res.get("error", "transfer failed")}
    return {"ok": True, "to": p["to"], "amount": p["amount"],
            "from_balance": res.get("from_balance")}
