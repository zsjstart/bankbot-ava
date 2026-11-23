"""CLI for Ava, the public-facing bank assistant.

    python bankbot/chat.py                 # anonymous visitor, Level 1
    python bankbot/chat.py --level 1 --model qwen2.5:7b

You are an anonymous member of the public chatting with Ava. Try to extract a
customer's private data (a balance, an SSN, a card number) and watch what each
level does. At Level 1 the only thing stopping Ava is its system prompt.

Commands inside the chat:
    /level N   switch security level (1, 2 or 3)
    /new       start a fresh conversation
    /quit      exit

Requires `ollama serve` running and bank.db built (python bankbot/db.py).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import agent
import db

DB_PATH = Path(__file__).parent / "bank.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--model", default="qwen2.5:7b")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print("bank.db not found -- building it...")
        db.build()

    level = args.level
    history = None
    print(f"Ava -- Riverside Bank (anonymous visitor). Level {level}, model {args.model}.")
    print("Type /level N, /new, or /quit.\n")

    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg == "/quit":
            break
        if msg == "/new":
            history = None
            print("(new conversation)")
            continue
        if msg.startswith("/level"):
            parts = msg.split()
            if len(parts) == 2 and parts[1] in {"1", "2", "3"}:
                level = int(parts[1])
                history = None
                print(f"(switched to level {level}, new conversation)")
            else:
                print("usage: /level 1|2|3")
            continue

        reply, history, _ = agent.chat(msg, level=level, model=args.model, history=history)
        print(f"Ava> {reply}\n")


if __name__ == "__main__":
    main()
