# BankBot — layered security for an LLM agent ("Ava")

A small, self-contained demo of how to secure a **tool-using LLM agent**, built as a
synthetic retail-bank assistant called **Ava** on a local **Ollama** model. All data is
synthetic.

The point: once an agent can call tools over private data, security belongs at the
**tool boundary** and the **data layer** — not in the model's "please behave" prompt, and
not in a text filter on the output. BankBot makes that concrete with three switchable,
**cumulative** security levels.

## The three levels (cumulative)

- **L1 = System Instructions.** Ava is *told* to keep customer data confidential. Nothing
  in code enforces it — the model is the only guard, so a pretext or prompt injection can
  talk it into disclosing.
- **L2 = L1 + Output Filter.** A plaintext scan of the final reply withholds it if it
  contains a full card number (PAN), a full SSN, or a CVV. It is context-blind and
  bypassable by spelled-out or encoded digits — a last-resort backstop, **not** a gate.
- **L3 = L1 + L2 + Tool-Boundary Authorization + Data Masking.** Before the sensitive tool
  runs, deterministic code decides *who* may read the record (only the authenticated owner;
  everyone else is denied), and the data layer *masks what even the owner sees*
  (card → last 4, SSN → last 4, CVV dropped; account number and balance kept). The model
  never receives what it must not disclose.

The level is chosen per request (`level` in the body, or `--level`), and each level builds
on the one below it.

## Identity & the customer-access policy

Identity is **proven, not claimed**: a client logs in (`POST /login`) for an opaque token;
the server resolves `token → customer_id`, and the model never gets to assert who it is.
The sensitive `lookup_customers` tool is guarded at L3 by `policy.check_customer_access`:

- not signed in → *"you must be signed in to view account information"*;
- signed in but not the record's owner → *"you can only view your own account information"*
  (a nonexistent name returns the **same** denial, so it can't be used to enumerate real
  customers);
- the owner → allowed, then **masked at the source** (`masking.py`) before it reaches the model.

`query_db(sql)` and `read_file(path)` are likewise policy-guarded at L3: SQL must be a
single read-only `SELECT` over the public tables only (parsed with `sqlglot`); file reads
are confined to `public_docs/`.

Public data: `branches, products, rates, faqs`.
Private data (never leaked): `customers, accounts, transactions, cards`.

## Three callers, one set of controls

| Caller | Result at L3 |
|---|---|
| **Anonymous** (not signed in) | denied — must authenticate |
| **A different customer** (signed in) | denied — you can only view your own record |
| **The account owner** (signed in) | served — with sensitive fields masked |

L1 leaks to all three; L2 catches the plaintext attempt but is bypassable; **L3 holds — and
still serves the legitimate owner.**

## Run it

Requires [Ollama](https://ollama.com) running locally with a tool-capable model
(default `qwen2.5:7b`).

```bash
pip install -r requirements.txt
ollama serve                      # in another terminal
ollama pull qwen2.5:7b

python bankbot/db.py              # build the synthetic bank.db (once)

# interactive CLI
python bankbot/chat.py --level 3

# or the HTTP server
python bankbot/server.py --level 3 --port 8000
```

HTTP API:

```
POST /login   {"username": "...", "password": "..."}        -> {"token": "..."}
POST /chat    {"message": "...", "level": 3}                 (Authorization: Bearer <token>)
```

## Layout

- `bankbot/agent.py` — Ollama tool-calling loop, per-level gating, authenticated-identity injection
- `bankbot/policy.py` — L3 tool-boundary authorization (customer access, SQL allowlist, file path)
- `bankbot/masking.py` — L3 source-layer field masking (PAN/SSN → last 4, CVV dropped)
- `bankbot/filters.py` — L2 output filter (full PAN / SSN / CVV)
- `bankbot/auth.py` — login and `token → customer_id` (demo: in-memory, fake credentials)
- `bankbot/services.py`, `tools.py`, `db.py`, `server.py`, `chat.py`

## Note

Everything here is **synthetic** practice data on localhost. The demo credentials and the
"private" files are fake and exist only to show the controls working.
