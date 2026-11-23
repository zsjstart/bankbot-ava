"""Source-layer field masking (data minimization) for Level 3.

After the Level 3 policy allows a sensitive lookup and the tool fetches the
record, this masks the "never shown in full to anyone" fields BEFORE the record
reaches the model -- so the model cannot disclose what it never received. This
is the counterpart to the tool-boundary authorization: policy decides WHO may
read the record; masking decides WHICH fields come back, even for the owner.

Rules (what even the authenticated account holder sees):
  cvv          -> removed entirely (never shown to anyone, ever)
  card_number  -> last 4 only   (full PAN never shown)
  ssn          -> last 4 only   (full SSN never shown)
  account_number, balance, name, email, phone, dob, address, transactions
               -> kept (the owner's own data; authorization already gated WHO)

Fail closed: if the record can't be parsed/masked, withhold it rather than risk
passing an unmasked leak through.
"""
from __future__ import annotations

import json
import re

MASK = "•"  # the bullet character, for a visibly masked value


def _last4(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-4:] if len(digits) >= 4 else digits


def _mask_ssn(value) -> str:
    return f"{MASK * 3}-{MASK * 2}-{_last4(value)}"


def _mask_pan(value) -> str:
    return f"{MASK * 4} {MASK * 4} {MASK * 4} {_last4(value)}"


def mask_record(records):
    """Mask a lookup_customers record list in place and return it."""
    if not isinstance(records, list):
        raise ValueError("expected a list of customer records")
    for cust in records:
        if not isinstance(cust, dict):
            continue
        if cust.get("ssn"):
            cust["ssn"] = _mask_ssn(cust["ssn"])
        for acct in cust.get("accounts") or []:
            if not isinstance(acct, dict):
                continue
            card = acct.get("card")
            if isinstance(card, dict):
                if card.get("card_number"):
                    card["card_number"] = _mask_pan(card["card_number"])
                card.pop("cvv", None)  # never shown to anyone
    return records


def mask_lookup_json(json_str: str) -> str:
    """Parse the sensitive tool's JSON result, mask it, and re-serialize.

    Fail closed: on any parse/mask error, return a withholding error instead of
    the original text, so a record is never passed through unmasked.
    """
    try:
        data = json.loads(json_str)
        masked = mask_record(data)
        return json.dumps(masked)
    except Exception:
        return json.dumps(
            {"error": "record withheld: could not be safely minimized for display"}
        )
