"""Outbox delivery never retries a send whose outcome is unknown."""

import json
import urllib.error
import urllib.request

from .store import Denied


def telegram_send(token, recipient, body):
    request = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=json.dumps({'chat_id': recipient, 'text': body}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
            return 'sent' if result.get('ok') is True else 'uncertain'
    except urllib.error.HTTPError as exc:
        return 'failed' if 400 <= exc.code < 500 else 'uncertain'
    except Exception:
        return 'uncertain'


def deliver_one(store, mode, token='', sender=telegram_send):
    with store.connect() as conn:
        conn.execute("UPDATE chat_outbox SET status='uncertain',finished_at=now() WHERE status='attempted' AND attempted_at < now()-interval '2 minutes'")
        row = conn.execute("""WITH candidate AS (SELECT update_id FROM chat_outbox WHERE status='pending'
            ORDER BY update_id FOR UPDATE SKIP LOCKED LIMIT 1)
            UPDATE chat_outbox o SET status='attempted',attempted_at=now() FROM candidate c
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
        if status not in ('sent', 'failed', 'uncertain', 'simulated'):
            status = 'uncertain'
        conn.execute("UPDATE chat_outbox SET status=%s,body=CASE WHEN %s IN ('sent','failed','simulated') THEN '' ELSE body END,finished_at=now() WHERE update_id=%s AND status='attempted'", (status, status, update_id))
    return True
