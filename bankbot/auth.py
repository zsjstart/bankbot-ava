"""A minimal identity layer for BankBot.

The point: the customer's identity must be something the client *proves*, not
something it *claims*. Before this, /chat trusted a customer_id in the request
body -- so anyone could POST customer_id=2 and act as Jian. Now a client must
log in with a username + password, gets back an opaque token, and every call is
identified by that token. The server maps token -> customer_id itself; the
client never gets to say who it is.

This is deliberately simple (an in-memory credential map and token store, demo
passwords). It is NOT production auth -- no hashing, no expiry, no persistence
-- but it closes the "identity is self-asserted" hole, which was the real gap.
All credentials are fake.
"""
from __future__ import annotations

import secrets

# username -> (password, customer_id). Demo credentials; all fake.
CREDENTIALS = {
    "amara": ("maple14", 1),
    "jian": ("oak7", 2),
    "noah": ("pine221", 3),
    "mary": ("birch5", 4),
}

# Issued tokens: token -> customer_id. In-memory, so they reset when the server
# restarts (fine for a demo).
_TOKENS: dict[str, int] = {}


def login(username: str, password: str) -> str | None:
    """Check credentials; on success issue and return a token, else None."""
    record = CREDENTIALS.get((username or "").lower())
    if record and secrets.compare_digest(record[0], password or ""):
        token = secrets.token_urlsafe(24)
        _TOKENS[token] = record[1]
        return token
    return None


def customer_for_token(token: str | None) -> int | None:
    """Resolve a bearer token to the customer_id it was issued for."""
    if not token:
        return None
    return _TOKENS.get(token)


def logout(token: str) -> None:
    _TOKENS.pop(token, None)
