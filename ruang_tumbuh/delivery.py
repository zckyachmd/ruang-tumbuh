"""Outbox delivery never retries a send whose outcome is unknown."""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .store import Denied


@dataclass(frozen=True)
class RetryAfter:
    seconds: int


def telegram_send(token, recipient, body):
    # Rendering owns previews; never silently truncate an arbitrary send here.
    if not body or len(body.encode('utf-16-le')) // 2 > 4096:
        return 'failed'
    payload = {'chat_id': recipient, 'text': body}
    proposal = re.search(r'Balas "simpan (\d{1,19})" atau "batal \1"', body)
    if proposal:
        payload['reply_markup'] = {'inline_keyboard': [[
            {'text':'Simpan 🤍', 'callback_data':'save:'+proposal[1]},
            {'text':'Batal', 'callback_data':'cancel:'+proposal[1]}]]}
    request = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
            return 'sent' if result.get('ok') is True else 'uncertain'
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            try:
                result = json.loads(exc.read(65536))
                delay = result['parameters']['retry_after']
                if type(delay) is int and 1 <= delay <= 86400:
                    return RetryAfter(delay)
            except (ValueError, KeyError, TypeError):
                pass
            return RetryAfter(60)
        return 'failed' if 400 <= exc.code < 500 else 'uncertain'
    except Exception:
        return 'uncertain'


def acknowledge_callback(token, callback_id):
    request = urllib.request.Request(f'https://api.telegram.org/bot{token}/answerCallbackQuery',
        data=json.dumps({'callback_query_id':callback_id}).encode(), headers={'Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read(65536)
    except Exception:
        # Cosmetic acknowledgement only; never retry or repeat the underlying write.
        pass


def deliver_one(store, mode, token='', sender=telegram_send):
    with store.connect() as conn:
        conn.execute("UPDATE chat_outbox SET status='uncertain',finished_at=now() WHERE status='attempted' AND attempted_at < now()-interval '2 minutes'")
        row = conn.execute("""WITH candidate AS (SELECT update_id FROM chat_outbox WHERE status='pending'
            AND (next_attempt_at IS NULL OR next_attempt_at<=now())
            ORDER BY update_id FOR UPDATE SKIP LOCKED LIMIT 1)
            UPDATE chat_outbox o SET status='attempted',attempted_at=now(),attempts=attempts+1 FROM candidate c
            WHERE o.update_id=c.update_id RETURNING o.update_id,o.recipient_id,o.family_id,o.body""").fetchone()
    if not row:
        return False
    update_id, user, family, body = row
    body = store.data_cipher.open(body, "chat_outbox.body")
    with store.connect() as conn:
        if family is not None:
            try:
                store._access(conn, family, user)
            except Denied:
                conn.execute("UPDATE chat_outbox SET status='failed',finished_at=now() WHERE update_id=%s AND status='attempted'", (update_id,))
                return True
        current = conn.execute('SELECT status FROM chat_outbox WHERE update_id=%s FOR UPDATE', (update_id,)).fetchone()
        if not current or current[0] != 'attempted':
            return True
        status = 'simulated' if mode == 'fake' else sender(token, user, body)
        if isinstance(status, RetryAfter):
            conn.execute("""UPDATE chat_outbox SET status=CASE WHEN attempts<5 THEN 'pending' ELSE 'failed' END,
                next_attempt_at=%s,finished_at=NULL WHERE update_id=%s AND status='attempted'""",
                (datetime.now(timezone.utc) + timedelta(seconds=status.seconds), update_id))
            return True
        if status not in ('sent', 'failed', 'uncertain', 'simulated'):
            status = 'uncertain'
        conn.execute("UPDATE chat_outbox SET status=%s,body=CASE WHEN %s IN ('sent','failed','simulated') THEN '' ELSE body END,finished_at=now() WHERE update_id=%s AND status='attempted'", (status, status, update_id))
    return True

