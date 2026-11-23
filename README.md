# BankBot — layered security for an LLM agent ("Ava")

A small, self-contained demo of how to secure a **tool-using LLM agent**, built as a
synthetic retail-bank assistant called **Ava** on a local **Ollama** model. All data is
synthetic.

The point: once an agent can call tools over private data, security belongs at the
**tool boundary** and the **data layer** — not in the model's "please behave" prompt, and
not in a text filter on the output. BankBot makes that concrete with three switchable,
**cumulative** security levels.

## The three security levels

Three switchable levels, each **building on the one before it**:

- **Level 1 — System instructions only.** Ava's behaviour is governed entirely by its
  system prompt (for example, *"share account and card data only with the verified account
  holder"*). Nothing in code enforces this, so the model itself is the only safeguard.

- **Level 2 — Level 1 + an output filter.** An output filter is added on top of Level 1 to
  stop Ava from leaking a CVV, a complete card number (PAN), or a complete SSN. An output
  filter has to be designed carefully: if it is too aggressive, it can also suppress
  legitimate replies to properly authorized users.

- **Level 3 — Level 1 + Level 2 + tool-boundary controls.** On top of Levels 1 and 2,
  controls such as **authentication** and **data masking** are enforced at the tool
  boundary, to prevent the agent from making unauthorized tool calls and from disclosing
  sensitive fields it should not return.

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
python bankbot/server.py --level 3 --port 8000
```

HTTP API:

```
POST /login   {"username": "...", "password": "..."}        -> {"token": "..."}
POST /chat    {"message": "...", "level": 3}                 (Authorization: Bearer <token>)
```

## Layout

- `bankbot/agent.py` — Ollama tool-calling loop, per-level gating, authenticated-identity injection
- `bankbot/policy.py` — Level 3 tool-boundary authorization (customer access, SQL allowlist, file path)
- `bankbot/masking.py` — Level 3 source-layer field masking (PAN/SSN → last 4, CVV dropped)
- `bankbot/filters.py` — Level 2 output filter (full PAN / SSN / CVV)
- `bankbot/auth.py` — login and `token → customer_id` (demo: in-memory, fake credentials)
- `bankbot/services.py`, `tools.py`, `db.py`, `server.py`, `chat.py`

## Note

Everything here is **synthetic** practice data on localhost. The demo credentials and the
"private" files are fake and exist only to show the controls working.
