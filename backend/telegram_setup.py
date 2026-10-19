"""Telegram setup for TRADEden. Never prints the bot token.

  python telegram_setup.py check      the token in backend/.env reaches the bot (prints the bot's username)
  python telegram_setup.py discover   find your private chat (start the bot and send it a message first)
                                      and store it as TRADEDEN_TELEGRAM_CHAT_ID in backend/.env
  python telegram_setup.py test       send the integration test message to that chat
  python telegram_setup.py status     notification history counts

Live alerts stay off until TRADEDEN_TELEGRAM_ALERTS_ENABLED=1 is set and the engine restarts.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

import telegram_notifier as tg

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _client() -> tg.TelegramClient:
    load_dotenv(ENV_FILE)
    try:
        return tg.TelegramClient(os.getenv(tg.TOKEN_ENV, ""))
    except ValueError:
        sys.exit(f"{tg.TOKEN_ENV} is missing or malformed in {ENV_FILE} (value not shown).")


def _mask(chat_id: str) -> str:
    return "*" * max(0, len(chat_id) - 3) + chat_id[-3:]


def set_env_value(path: Path, name: str, value: str) -> None:
    """Set NAME=value in a dotenv file, keeping every other line as it is."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == name:
            if not done:
                out.append(f"{name}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{name}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def check() -> None:
    me = _client().get_me()
    print(f"Token OK: bot @{me.get('username')} is reachable.")


def discover(chat_id: str | None) -> None:
    client = _client()
    try:
        chats = tg.private_chats(client.get_updates())
    except tg.TelegramError as exc:
        sys.exit(f"getUpdates failed: {exc} (if a webhook is set, getUpdates is unavailable)")
    if chat_id:
        if chat_id not in chats:
            sys.exit("That chat has not messaged the bot recently; send the bot a message and retry.")
    elif len(chats) == 1:
        chat_id = next(iter(chats))
    elif not chats:
        sys.exit("No private chat found. Open the bot in Telegram, press Start (or send any message), then retry.")
    else:
        for cid, chat in chats.items():
            print(f"  {_mask(cid)}  {chat.get('first_name', '')} @{chat.get('username', '')}")
        sys.exit("Several private chats found; rerun with --chat-id <id> for yours.")
    chat = chats[chat_id]
    set_env_value(ENV_FILE, tg.CHAT_ENV, chat_id)
    print(f"Stored {tg.CHAT_ENV} ({_mask(chat_id)}, {chat.get('first_name', '')} @{chat.get('username', '')}) in {ENV_FILE.name}.")


def test() -> None:
    client = _client()
    chat_id = os.getenv(tg.CHAT_ENV, "").strip()
    if not chat_id:
        sys.exit(f"{tg.CHAT_ENV} is not set; run: python telegram_setup.py discover")
    try:
        result = client.send_message(chat_id, tg.TEST_MESSAGE)
    except tg.TelegramError as exc:
        sys.exit(f"Test message NOT delivered: {exc}")
    print(f"Test message accepted by Telegram: message_id={result.get('message_id')}, "
          f"chat {_mask(str((result.get('chat') or {}).get('id')))}.")


def status() -> None:
    load_dotenv(ENV_FILE)
    store = tg.NotificationStore()
    counts = Counter((row.get("kind"), row.get("status")) for row in store.items())
    print(f"alerts enabled: {tg.alerts_enabled()}   history: {store.path}")
    for (kind, state), count in sorted(counts.items(), key=str):
        print(f"  {kind:8} {state:10} {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "discover", "test", "status"))
    parser.add_argument("--chat-id")
    args = parser.parse_args()
    {"check": check, "test": test, "status": status}.get(args.command, lambda: discover(args.chat_id))()


if __name__ == "__main__":
    main()
