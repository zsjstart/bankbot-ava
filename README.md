# BankBot — layered security for an LLM agent ("Ava")

A small, self-contained demo of how to secure a **tool-using LLM agent**, built as a
synthetic retail-bank assistant called **Ava** on a local **Ollama** model. All data is
synthetic.

The point: once an agent can call tools over private data, security belongs at the
**tool boundary** and the **data layer** — not in the model's "please behave" prompt, and
not in a text filter on the output. BankBot makes that concrete with four switchable,
**cumulative** security levels.

## The security levels

Four switchable levels, each **building on the one before it**:

- **Level 1 — System instructions only.** Ava's behaviour is governed entirely by its
  system prompt (for example, *"share account and card data only with the verified account
  holder"*). Nothing in code enforces this, so the model itself is the only safeguard.

- **Level 2 — Level 1 + an output filter.** An output filter is added on top of Level 1 to
  stop Ava from leaking a CVV, a complete card number (PAN), or a complete SSN. An output
  filter has to be designed carefully: if it is too aggressive, it can also suppress
  legitimate replies to properly authorized users.

- **Level 3 — Level 2 + tool-boundary controls.** On top of Levels 1 and 2,
  controls such as **authentication** and **data masking** are enforced at the tool
  boundary, to prevent the agent from making unauthorized tool calls and from disclosing
  sensitive fields it should not return.

- **Level 4 — Level 3 + an minimal stand-in for out-of-band confirmation.** The first three levels
  govern *reading* data. A *write* is different: when Ava can move money
  (`transfer_money`), the account holder is genuinely allowed to move their own funds — so
  authorization passes.
  
  Level 4 adds a confirmation gate: a transfer is **not executed on the model's say-so**; it is parked and only runs
  after the account holder confirms it **out-of-band** (a separate `/confirm` endpoint the
  model cannot call). This is what stops a *confused-deputy* write — an instruction
  smuggled into data the agent reads (indirect prompt injection) — from actually moving
  money.

The level is chosen per request (`level` in the body, or `--level`).

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
python bankbot/server.py --level 4 --port 8000
```

HTTP API:

```
POST /login    {"username": "...", "password": "..."}        -> {"token": "..."}
POST /chat     {"message": "...", "level": 4}                 (Authorization: Bearer <token>)
POST /confirm  {"confirm_id": "..."}                          (Authorization: Bearer <token>)
               -> executes a Level-4 transfer the account holder confirms out-of-band
```

## Layout

- `bankbot/agent.py` — Ollama tool-calling loop, per-level gating, authenticated-identity injection
- `bankbot/policy.py` — Level 3 tool-boundary authorization (customer access, SQL allowlist, file path)
- `bankbot/masking.py` — Level 3 source-layer field masking (PAN/SSN → last 4, CVV dropped)
- `bankbot/filters.py` — Level 2 output filter (full PAN / SSN / CVV)
- `bankbot/payments.py` — Level 4 write-side control: `transfer_money` only parks a transfer; `/confirm` executes it after out-of-band owner confirmation
- `bankbot/auth.py` — login and `token → customer_id` (demo: in-memory, fake credentials)
- `bankbot/services.py`, `tools.py`, `db.py`, `server.py`, `chat.py`

## Note

Everything here is **synthetic** practice data on localhost. The demo credentials and the
"private" files are fake and exist only to show the controls working. The synthetic
transaction data also includes one **benign prompt-injection memo** — a fake "scheduled
payment" note planted in a customer's own record — used to demonstrate the confused-deputy
write at Level 3 vs Level 4.
