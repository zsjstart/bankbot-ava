"""Level 2 output filter: scan the model's final reply for private data and
block it if found.

This is deliberately a *plaintext* scan. It catches private data written out
normally, but an encoding trick (base64, ROT13, reversed, spaced-out) sails
right past it — the exact weakness the LinkedIn post describes. Level 3 does
not rely on this; it stops the data at the source instead.
"""
from __future__ import annotations

import re

# Only the "never shown in full to anyone" fields belong here. A context-blind
# text scan cannot tell an owner's OWN account number or balance (legitimate)
# from a leak, so those are enforced at the source instead (Level 3: tool-
# boundary authorization + field masking). What is left is data with no
# legitimate plaintext disclosure to anyone: a full card number (PAN), a full
# SSN, and a CVV. (This filter stays bypassable by spelled-out/encoded digits on
# purpose -- it is a last-resort backstop, not the primary control.)
PATTERNS = {
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "card_number": re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,4}\b"),
    "CVV": re.compile(r"cvv[^.\n]{0,8}?\b\d{3,4}\b", re.IGNORECASE),
}


def scan(text: str) -> list[str]:
    """Return the names of any private-data patterns found in text."""
    hits = []
    for name, pat in PATTERNS.items():
        if pat.search(text or ""):
            hits.append(name)
    return hits


def filter_output(text: str) -> tuple[str, list[str]]:
    """Return (safe_text, hits). If anything private is detected, the reply is
    replaced with a refusal."""
    hits = scan(text)
    if hits:
        refusal = ("I can't share that information. It looks like the response "
                   "contained private account details, so I've withheld it.")
        return refusal, hits
    return text, []
