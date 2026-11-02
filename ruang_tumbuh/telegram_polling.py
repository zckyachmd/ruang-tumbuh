"""Durable, single-consumer Telegram long polling."""

import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request

from psycopg.types.json import Jsonb

from .store import Conflict, Store
from .admission import admit_update, QueueFull
from .privacy import DataCipher
from .telegram_updates import minimal_private_update


LOCK_ID = 823746102


class PollingConfigurationError(RuntimeError):
    pass


def telegram_get_updates(token, offset, timeout=30):
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getUpdates",
        data=json.dumps({"offset": offset, "timeout": timeout, "allowed_updates": ["message"]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout + 10) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise RuntimeError("Telegram polling request failed")
    if result.get("ok") is not True:
        code = result.get("error_code")
        if type(code) is int and code == 401:
            raise PollingConfigurationError("Telegram rejected the bot token (401); verify TELEGRAM_BOT_TOKEN.")
        if type(code) is int and code == 409:
            raise PollingConfigurationError("Telegram rejected polling (409); remove the active webhook or stop the other poller.")
        raise RuntimeError("Telegram polling request failed")
    if not isinstance(result.get("result"), list):
        raise RuntimeError("Telegram polling request failed")
    return result["result"]


def persist_updates(conn, updates, cipher=None):
    """Persist supported private text messages and cursor atomically."""
    cipher = cipher or DataCipher.from_environment()
    cursor = conn.execute("SELECT next_offset FROM telegram_poll_cursor WHERE singleton=true FOR UPDATE").fetchone()
    offset = cursor[0] if cursor else 0
    highest = offset - 1
    for update in updates:
        if not isinstance(update, dict) or type(update.get("update_id")) is not int or update["update_id"] < offset:
            raise ValueError("Invalid Telegram update batch")
        update_id = update["update_id"]
        highest = max(highest, update_id)
        message = update.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("chat"), dict) or message["chat"].get("type") != "private":
            continue
        sender = message.get("from")
        text = message.get("text")
        date = message.get("date")
        user = sender.get("id") if isinstance(sender, dict) else None
        if (type(user) is not int or user <= 0 or message["chat"].get("id") != user
                or sender.get("is_bot") is True or not isinstance(text, str) or len(text) > 4096
                or type(date) is not int or date <= 0):
            continue
        admit_update(conn, update_id, user)
        payload = minimal_private_update(update_id, user, text, date)
        encrypted_payload = cipher.seal_json(payload, "inbound_updates.payload")
        inserted = conn.execute("""INSERT INTO inbound_updates (update_id,telegram_user_id,payload)
            VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING update_id""",
            (update_id, user, Jsonb(encrypted_payload))).fetchone()
        if not inserted:
            existing = conn.execute("SELECT telegram_user_id,payload,status FROM inbound_updates WHERE update_id=%s", (update_id,)).fetchone()
            scrubbed = existing and existing[0] == user and existing[1] == {} and existing[2] in ('completed', 'failed')
            prior_payload = existing[1] if scrubbed else cipher.open_json(existing[1], "inbound_updates.payload") if existing else None
            if not scrubbed and (not existing or existing[0] != user or prior_payload != payload):
                raise Conflict()
    if highest >= offset:
        next_offset = highest + 1
        conn.execute("""INSERT INTO telegram_poll_cursor(singleton,next_offset) VALUES (true,%s)
            ON CONFLICT (singleton) DO UPDATE SET next_offset=excluded.next_offset""", (next_offset,))
        return next_offset
    return offset


def polling_loop(store, token, *, get_updates=telegram_get_updates, timeout=30, running=lambda: True, sleep=time.sleep):
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required for polling")
    if type(timeout) is not int or not 1 <= timeout <= 50:
        raise ValueError("TELEGRAM_POLL_TIMEOUT must be between 1 and 50")
    with store.connect() as lock_conn:
        lock_conn.autocommit = True
        if not lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
            raise RuntimeError("Another Telegram poller is already running")
        delay = 1
        try:
            while running():
                try:
                    with store.connect() as conn:
                        row = conn.execute("SELECT next_offset FROM telegram_poll_cursor WHERE singleton=true").fetchone()
                    offset = row[0] if row else 0
                    updates = get_updates(token, offset, timeout)
                    with store.connect() as conn:
                        persist_updates(conn, updates, store.data_cipher)
                    delay = 1
                except PollingConfigurationError as exc:
                    if not running():
                        break
                    print(f'{exc} Retrying with backoff.', file=sys.stderr)
                    sleep(delay)
                    delay = min(delay * 2, 30)
                except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, QueueFull):
                    if not running():
                        break
                    print('Telegram polling failed; retrying. Check the bot token, network, and any active webhook; error details are withheld to protect the token.', file=sys.stderr)
                    sleep(delay)
                    delay = min(delay * 2, 30)
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def main():
    if os.getenv("TELEGRAM_TRANSPORT", "disabled") != "polling":
        raise ValueError("Set TELEGRAM_TRANSPORT=polling to run this service")
    try:
        timeout = int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30"))
    except ValueError as exc:
        raise ValueError("TELEGRAM_POLL_TIMEOUT must be an integer between 1 and 50") from exc
    store = Store(os.environ["DATABASE_URL"])
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    polling_loop(store, os.getenv("TELEGRAM_BOT_TOKEN", ""), timeout=timeout, running=lambda: running)


if __name__ == "__main__":
    main()

