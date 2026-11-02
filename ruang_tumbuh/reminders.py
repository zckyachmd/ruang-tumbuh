"""One-time reminders for the authenticated recipient only."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .store import Conflict, Invalid


def create_reminder(store, family, user, body, due_at, bypass_quiet_hours, key, *, now=None):
    now = now or datetime.now(timezone.utc)
    if (not isinstance(body, str) or not 1 <= len(body.strip()) <= 500 or not isinstance(due_at, datetime)
            or due_at.utcoffset() is None
            or type(bypass_quiet_hours) is not bool or not isinstance(key, str) or not 1 <= len(key) <= 200):
        raise Invalid()
    body = body.strip()
    request = {'action': 'reminder', 'family': family, 'user': user, 'body': body,
               'due_at': due_at.astimezone(timezone.utc).isoformat(), 'bypass_quiet_hours': bypass_quiet_hours}
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).digest()
    with store.connect() as conn:
        store._access(conn, family, user)
        inserted = conn.execute("INSERT INTO api_actions (telegram_user_id,action_key,request_hash,family_id) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING action_key", (user, key, fingerprint, family)).fetchone()
        if not inserted:
            row = conn.execute('SELECT request_hash,result FROM api_actions WHERE telegram_user_id=%s AND action_key=%s', (user, key)).fetchone()
            if bytes(row[0]) != fingerprint:
                raise Conflict()
            return row[1]['reminder_id']
        if not now < due_at <= now + timedelta(days=366):
            raise Invalid()
        pref = conn.execute("SELECT enabled FROM notification_preferences WHERE family_id=%s AND telegram_user_id=%s AND kind='reminder'", (family, user)).fetchone()
        if not pref or not pref[0]:
            raise Invalid()
        zone = ZoneInfo(conn.execute('SELECT timezone FROM families WHERE id=%s', (family,)).fetchone()[0])
        expiry = due_at + timedelta(hours=1)
        reminder = conn.execute("""INSERT INTO reminders(family_id,telegram_user_id,body,due_at,expires_at,bypass_quiet_hours)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""", (family, user, store.data_cipher.seal(body, "reminders.body"), due_at, expiry, bypass_quiet_hours)).fetchone()[0]
        conn.execute("""INSERT INTO scheduled_occurrences(family_id,telegram_user_id,occurrence_key,due_at,expires_at,kind,local_date,reminder_id)
            VALUES (%s,%s,%s,%s,%s,'reminder',%s,%s)""", (family, user, f'reminder:{reminder}', due_at, expiry, due_at.astimezone(zone).date(), reminder))
        conn.execute('UPDATE api_actions SET result=%s WHERE telegram_user_id=%s AND action_key=%s', (Jsonb({'reminder_id': reminder}), user, key))
    return reminder


def list_reminders(store, family, user):
    with store.connect() as conn:
        store._access(conn, family, user)
        rows = conn.execute("""SELECT r.id,r.body,r.due_at,r.expires_at,r.bypass_quiet_hours,r.cancelled_at,o.status
            FROM reminders r JOIN scheduled_occurrences o ON o.family_id=r.family_id AND o.reminder_id=r.id
            WHERE r.family_id=%s AND r.telegram_user_id=%s ORDER BY r.due_at DESC,r.id DESC LIMIT 100""", (family, user)).fetchall()
        return [(row[0], store.data_cipher.open(row[1], "reminders.body"), *row[2:]) for row in rows]


def cancel_reminder(store, family, user, reminder):
    with store.connect() as conn:
        store._access(conn, family, user)
        row = conn.execute("UPDATE reminders SET cancelled_at=coalesce(cancelled_at,now()) WHERE family_id=%s AND telegram_user_id=%s AND id=%s RETURNING id", (family, user, reminder)).fetchone()
        if not row:
            raise Invalid()
        conn.execute("UPDATE scheduled_occurrences SET status='cancelled',finished_at=now() WHERE family_id=%s AND reminder_id=%s AND status IN ('pending','claimed')", (family, reminder))
