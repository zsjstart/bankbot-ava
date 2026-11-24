"""BankBot HTTP server -- runs the agent in the background and exposes it over
HTTP. The enforcement lives server-side; a client only sees the reply.

Run it (from the repo root, with `ollama serve` up and bank.db built):
    .venv/bin/python bankbot/server.py                 # 127.0.0.1:8000, Level 1
    .venv/bin/python bankbot/server.py --level 3 --port 8080
    .venv/bin/python bankbot/server.py --host 0.0.0.0  # expose on the network

Endpoints:
    GET  /health   -> {"status": "ok", "level": N, "model": "..."}
    POST /login    -> exchange credentials for a token
        request  JSON: {"username": "amara", "password": "..."}
        response JSON: {"token": "..."}            (401 if wrong)
    POST /chat     -> send one message, get a reply (requires a token)
        header:  Authorization: Bearer <token>
        request  JSON: {"message": "...", "conversation_id": "optional",
                        "level": optional, "model": optional}
        response JSON: {"reply": "...", "tool_calls": [...],
                        "conversation_id": "...", "turn_id": "...", "level": N}
    POST /confirm  -> confirm (and execute) a transfer that transfer_money parked
        header:  Authorization: Bearer <token>   (must be the owner's own token)
        request  JSON: {"confirm_id": "..."}
        response JSON: {"ok": true, "to": "...", "amount": N}  (403 if not the owner)
        This endpoint is NOT a tool, so the model cannot reach it; the execute
        switch lives outside the model's control loop.

Identity comes from the token, NOT the request body: the client logs in, the
server maps the token to a customer_id, and the caller can never assert who it
is. (This closes the earlier "self-asserted customer_id" hole. It is still demo
auth -- see auth.py -- not production-grade.)

Conversation state is kept server-side, keyed by conversation_id: send the same
id back to continue a conversation, or omit it to start a fresh one.
"""
from __future__ import annotations

import argparse
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agent
import auth
import db
import payments

# Server-wide defaults (set in main()).
CONFIG = {"level": 1, "model": "qwen2.5:7b"}

# conversation_id -> message history. Guarded by a lock for threaded requests.
SESSIONS: dict[str, list[dict]] = {}
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send(200, {"status": "ok", "level": CONFIG["level"],
                             "model": CONFIG["model"]})
        else:
            self._send(404, {"error": "not found"})

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None

    def _bearer_token(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[len("Bearer "):].strip()
        return None

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        if path == "/login":
            self._do_login()
        elif path == "/chat":
            self._do_chat()
        elif path == "/confirm":
            self._do_confirm()
        else:
            self._send(404, {"error": "not found"})

    def _do_confirm(self) -> None:
        # Confirm (and thereby execute) a transfer that transfer_money parked.
        # NOT a tool, so the model can never reach this; identity comes from the
        # caller's OWN login token, exactly like /chat. Possession of a
        # confirm_id alone is not enough -- the token-resolved caller must match
        # the customer who parked the transfer.
        data = self._read_json()
        if data is None:
            self._send(400, {"error": "invalid JSON body"})
            return
        caller_id = auth.customer_for_token(self._bearer_token())
        result = payments.confirm(data.get("confirm_id", ""), caller_id)
        self._send(200 if result.get("ok") else 403, result)

    def _do_login(self) -> None:
        data = self._read_json()
        if data is None:
            self._send(400, {"error": "invalid JSON body"})
            return
        token = auth.login(data.get("username", ""), data.get("password", ""))
        if token is None:
            self._send(401, {"error": "invalid username or password"})
            return
        self._send(200, {"token": token})

    def _do_chat(self) -> None:
        # Anyone can chat without logging in (public info stays available). An
        # optional login token identifies the caller: we resolve it to a
        # customer_id server-side and pass it down, where the Level 3 check uses
        # it to allow a customer to see only their OWN record. No token -> an
        # anonymous session (caller_id is None).
        data = self._read_json()
        if data is None:
            self._send(400, {"error": "invalid JSON body"})
            return

        message = data.get("message")
        if not message:
            self._send(400, {"error": "missing 'message'"})
            return
        level = int(data.get("level", CONFIG["level"]))
        model = data.get("model", CONFIG["model"])
        conv_id = data.get("conversation_id") or ("conv_" + uuid.uuid4().hex[:12])
        caller_id = auth.customer_for_token(self._bearer_token())

        with LOCK:
            history = SESSIONS.get(conv_id)

        try:
            reply, history, tool_calls = agent.chat(
                message, level=level, model=model, history=history,
                caller_id=caller_id)
        except Exception as e:  # noqa: BLE001  (surface model/connection errors)
            self._send(502, {"error": f"agent failure: {e}"})
            return

        with LOCK:
            SESSIONS[conv_id] = history

        self._send(200, {
            "reply": reply,
            "tool_calls": tool_calls,
            "conversation_id": conv_id,
            "level": level,
        })

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        return


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--level", type=int, default=1, choices=[1, 2, 3, 4])
    ap.add_argument("--model", default="qwen2.5:7b")
    args = ap.parse_args()

    CONFIG["level"] = args.level
    CONFIG["model"] = args.model

    if not (db.DB_PATH).exists():
        print("bank.db not found -- building it...")
        db.build()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"BankBot server on http://{args.host}:{args.port}  "
          f"(default level {args.level}, model {args.model})")
    print("POST /chat  |  GET /health  |  Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
        server.shutdown()


if __name__ == "__main__":
    main()
