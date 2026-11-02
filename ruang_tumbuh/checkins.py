"""Opt-in daily check-ins. Missed occurrences expire instead of being replayed."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from .delivery import telegram_send, RetryAfter
from .store import Denied, Invalid

MESSAGE = 'Ada minum atau popok yang belum sempat dicatat?'


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) != {'time', 'timezone', 'quiet_start', 'quiet_end', 'snoozed_until', 'max_daily'}:
        raise Invalid()
    try:
        if not isinstance(settings['timezone'], str):
            raise ValueError()
        ZoneInfo(settings['timezone'])
        for key in ('time', 'quiet_start', 'quiet_end'):
            value = settings[key]
            if key != 'time' and value is None:
                continue
            if not isinstance(value, str) or len(value) != 5 or time.fromisoformat(value).strftime('%H:%M') != value:
                raise ValueError()
        if (settings['quiet_start'] is None) != (settings['quiet_end'] is None):
            raise ValueError()
        if settings['quiet_start'] == settings['quiet_end'] and settings['quiet_start'] is not None:
            raise ValueError()
        snooze = settings['snoozed_until']
        if snooze is not None and (not isinstance(snooze, str) or datetime.fromisoformat(snooze).utcoffset() is None):
            raise ValueError()
        if type(settings['max_daily']) is not int or not 1 <= settings['max_daily'] <= 20:
            raise ValueError()
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise Invalid() from None


def validate_kind_settings(kind, settings):
    if kind not in ('checkin', 'daily_summary', 'reminder'):
        raise Invalid()
    if kind == 'daily_summary':
        if not isinstance(settings, dict) or type(settings.get('child_id')) is not int or settings['child_id'] <= 0:
            raise Invalid()
        settings = {key: value for key, value in settings.items() if key != 'child_id'}
    validate_settings(settings)


def set_preferences(store, family, user, enabled, settings, kind='checkin'):
    with store.connect() as conn:
        set_preferences_in_transaction(conn, store, family, user, enabled, settings, kind)


def set_preferences_in_transaction(conn, store, family, user, enabled, settings, kind='checkin'):
    if type(enabled) is not bool:
        raise Invalid()
    validate_kind_settings(kind, settings)
    store._access(conn, family, user)
    if kind == 'daily_summary' and not conn.execute('SELECT 1 FROM children WHERE family_id=%s AND id=%s', (family, settings['child_id'])).fetchone():
        raise Invalid()
    old = conn.execute("SELECT settings,enabled FROM notification_preferences WHERE family_id=%s AND telegram_user_id=%s AND kind=%s", (family, user, kind)).fetchone()
    old = (store.data_cipher.open_json(old[0], "notification_preferences.settings"), old[1]) if old else None
    conn.execute("""INSERT INTO notification_preferences(family_id,telegram_user_id,kind,enabled,settings)
        VALUES (%s,%s,%s,%s,%s) ON CONFLICT (family_id,telegram_user_id,kind)
        DO UPDATE SET enabled=excluded.enabled,settings=excluded.settings""", (family, user, kind, enabled, Jsonb(store.data_cipher.seal_json(settings, "notification_preferences.settings"))))
    changed_schedule = old and kind != 'reminder' and any(old[0].get(key) != settings.get(key) for key in ('time', 'timezone', 'child_id'))
    if not enabled or changed_schedule:
        conn.execute("UPDATE scheduled_occurrences SET status='cancelled',reschedule_allowed=%s WHERE family_id=%s AND telegram_user_id=%s AND kind=%s AND status IN ('pending','claimed')", (bool(enabled and changed_schedule), family, user, kind))
    else:
        conn.execute("UPDATE scheduled_occurrences SET next_attempt_at=NULL WHERE family_id=%s AND telegram_user_id=%s AND kind=%s AND status='pending'", (family, user, kind))
    if enabled and old and not old[1] and kind != 'reminder':
        conn.execute("UPDATE scheduled_occurrences SET reschedule_allowed=true WHERE family_id=%s AND telegram_user_id=%s AND kind=%s AND status='cancelled'", (family, user, kind))



def get_preferences(store, family, user, kind='checkin'):
    if kind not in ('checkin', 'daily_summary', 'reminder'):
        raise Invalid()
    with store.connect() as conn:
        store._access(conn, family, user)
        row = conn.execute("SELECT enabled,settings FROM notification_preferences WHERE family_id=%s AND telegram_user_id=%s AND kind=%s", (family, user, kind)).fetchone()
        return {'enabled': row[0], 'settings': store.data_cipher.open_json(row[1], "notification_preferences.settings")} if row else {'enabled': False, 'settings': None}


def acknowledge(store, family, user, local_date):
    with store.connect() as conn:
        store._access(conn, family, user)
        conn.execute("INSERT INTO checkin_answers (family_id,local_date,answered_by) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (family, local_date, user))
        conn.execute("UPDATE scheduled_occurrences SET status='cancelled' WHERE family_id=%s AND kind='checkin' AND local_date=%s AND status IN ('pending','claimed')", (family, local_date))


def schedule_today(store, now=None):
    now = now or datetime.now(timezone.utc)
    with store.connect() as conn:
        prefs = conn.execute("SELECT family_id,telegram_user_id,settings,kind FROM notification_preferences WHERE kind IN ('checkin','daily_summary') AND enabled=true").fetchall()
    for family, user, sealed_settings, kind in prefs:
        try:
            settings = store.data_cipher.open_json(sealed_settings, "notification_preferences.settings")
            validate_kind_settings(kind, settings)
            zone = ZoneInfo(settings['timezone'])
            today = now.astimezone(zone).date()
            due = datetime.combine(today, time.fromisoformat(settings['time']), tzinfo=zone)
            if due.replace(fold=0).utcoffset() != due.replace(fold=1).utcoffset():
                continue
            due = due.astimezone(timezone.utc)
            expiry = due + timedelta(hours=1)
            if now >= expiry:
                continue
            with store.connect() as conn:
                store._access(conn, family, user)
                family_zone = conn.execute('SELECT timezone FROM families WHERE id=%s', (family,)).fetchone()[0]
                family_date = due.astimezone(ZoneInfo(family_zone)).date()
                active = conn.execute("SELECT enabled,settings FROM notification_preferences WHERE family_id=%s AND telegram_user_id=%s AND kind=%s", (family, user, kind)).fetchone()
                if not active or not active[0] or store.data_cipher.open_json(active[1], "notification_preferences.settings") != settings:
                    continue
                if kind == 'checkin' and conn.execute('SELECT 1 FROM checkin_answers WHERE family_id=%s AND local_date=%s', (family, family_date)).fetchone():
                    continue
                child = settings.get('child_id')
                if child is not None and not conn.execute('SELECT 1 FROM children WHERE family_id=%s AND id=%s', (family, child)).fetchone():
                    continue
                conn.execute("""INSERT INTO scheduled_occurrences(family_id,telegram_user_id,occurrence_key,due_at,expires_at,kind,local_date,child_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (family_id,telegram_user_id,occurrence_key)
                    DO UPDATE SET status='pending',due_at=excluded.due_at,expires_at=excluded.expires_at,next_attempt_at=NULL,child_id=excluded.child_id,reschedule_allowed=false
                    WHERE scheduled_occurrences.status='cancelled' AND scheduled_occurrences.reschedule_allowed""", (family, user, f'{kind}:{today.isoformat()}', due, expiry, kind, family_date, child))
        except (Denied, Invalid):
            continue


def in_quiet_hours(settings, now):
    start, end = settings['quiet_start'], settings['quiet_end']
    if start is None:
        return False
    clock = now.astimezone(ZoneInfo(settings['timezone'])).time().replace(tzinfo=None)
    start, end = time.fromisoformat(start), time.fromisoformat(end)
    return start <= clock < end if start < end else clock >= start or clock < end


def deliver_checkin(store, mode, token='', sender=telegram_send, now=None):
    fixed_now = now is not None
    now = now or datetime.now(timezone.utc)
    with store.connect() as conn:
        conn.execute("UPDATE scheduled_occurrences SET status='uncertain',finished_at=%s WHERE status='attempted' AND attempted_at < %s - interval '2 minutes'", (now, now))
        conn.execute("UPDATE scheduled_occurrences SET status='cancelled',finished_at=%s WHERE kind IN ('checkin','daily_summary','reminder') AND status='pending' AND expires_at <= %s", (now, now))
        row = conn.execute("SELECT id,family_id,telegram_user_id FROM scheduled_occurrences WHERE kind IN ('checkin','daily_summary','reminder') AND status='pending' AND due_at <= %s AND (next_attempt_at IS NULL OR next_attempt_at <= %s) ORDER BY due_at,id LIMIT 1", (now, now)).fetchone()
    if not row:
        return False
    occurrence, family, user = row
    with store.connect() as conn:
        try:
            store._access(conn, family, user)
        except Denied:
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled' WHERE id=%s AND status='pending'", (occurrence,))
            return True
        job = conn.execute("SELECT due_at,expires_at,local_date,status,kind,child_id,reminder_id FROM scheduled_occurrences WHERE id=%s FOR UPDATE", (occurrence,)).fetchone()
        if not job or job[3] != 'pending':
            return True
        kind = job[4]
        pref = conn.execute("SELECT enabled,settings FROM notification_preferences WHERE family_id=%s AND telegram_user_id=%s AND kind=%s", (family, user, kind)).fetchone()
        pref = (pref[0], store.data_cipher.open_json(pref[1], "notification_preferences.settings")) if pref else None
        answered = kind == 'checkin' and conn.execute('SELECT 1 FROM checkin_answers WHERE family_id=%s AND local_date=%s', (family, job[2])).fetchone()
        reminder = conn.execute('SELECT body,bypass_quiet_hours,cancelled_at FROM reminders WHERE family_id=%s AND id=%s AND telegram_user_id=%s', (family, job[6], user)).fetchone() if kind == 'reminder' else None
        reminder = (store.data_cipher.open(reminder[0], "reminders.body"), *reminder[1:]) if reminder else None
        if not pref or not pref[0] or answered or now >= job[1] or (kind == 'reminder' and (not reminder or reminder[2])):
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled',finished_at=%s WHERE id=%s", (now, occurrence))
            return True
        try:
            validate_kind_settings(kind, pref[1])
        except Invalid:
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled',finished_at=%s WHERE id=%s", (now, occurrence))
            return True
        settings = pref[1]
        if (settings['snoozed_until'] and now < datetime.fromisoformat(settings['snoozed_until'])) or (in_quiet_hours(settings, now) and not (reminder and reminder[1])):
            conn.execute("UPDATE scheduled_occurrences SET next_attempt_at=%s WHERE id=%s", (now + timedelta(minutes=1), occurrence))
            return True
        sent = conn.execute("""SELECT count(*) FROM scheduled_occurrences WHERE family_id=%s AND telegram_user_id=%s
            AND local_date=%s AND kind=%s AND status IN ('attempted','sent','simulated','uncertain')""", (family, user, job[2], kind)).fetchone()[0]
        if sent >= settings['max_daily']:
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled',finished_at=%s WHERE id=%s", (now, occurrence))
            return True
        conn.execute("UPDATE scheduled_occurrences SET status='attempted',attempted_at=%s,attempts=attempts+1 WHERE id=%s", (now, occurrence))
    # Commit attempt first: a crash after a send must never cause blind redelivery.
    with store.connect() as conn:
        try:
            store._access(conn, family, user)
        except Denied:
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled',finished_at=%s WHERE id=%s AND status='attempted'", (now, occurrence))
            return True
        current = conn.execute('SELECT status FROM scheduled_occurrences WHERE id=%s FOR UPDATE', (occurrence,)).fetchone()
        if not current or current[0] != 'attempted':
            return True
        if not fixed_now:
            now = datetime.now(timezone.utc)
        pref = conn.execute("SELECT enabled,settings FROM notification_preferences WHERE family_id=%s AND telegram_user_id=%s AND kind=%s", (family, user, kind)).fetchone()
        pref = (pref[0], store.data_cipher.open_json(pref[1], "notification_preferences.settings")) if pref else None
        answered = kind == 'checkin' and conn.execute('SELECT 1 FROM checkin_answers WHERE family_id=%s AND local_date=%s', (family, job[2])).fetchone()
        reminder = conn.execute('SELECT body,bypass_quiet_hours,cancelled_at FROM reminders WHERE family_id=%s AND id=%s AND telegram_user_id=%s', (family, job[6], user)).fetchone() if kind == 'reminder' else None
        reminder = (store.data_cipher.open(reminder[0], "reminders.body"), *reminder[1:]) if reminder else None
        if (not pref or not pref[0] or pref[1] != settings or answered or now >= job[1]
                or (kind == 'reminder' and (not reminder or reminder[2]))
                or (kind == 'daily_summary' and settings.get('child_id') != job[5])
                or (in_quiet_hours(settings, now) and not (reminder and reminder[1]))
                or (settings['snoozed_until'] and now < datetime.fromisoformat(settings['snoozed_until']))):
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled',finished_at=%s WHERE id=%s AND status='attempted'", (now, occurrence))
            return True
        body = MESSAGE
        if kind == 'checkin':
            selected = conn.execute('SELECT c.id,c.nickname FROM chat_selections s JOIN children c ON c.family_id=s.family_id AND c.id=s.child_id WHERE s.family_id=%s AND s.telegram_user_id=%s', (family,user)).fetchone()
            if not selected:
                only = conn.execute('SELECT id,nickname FROM children WHERE family_id=%s ORDER BY id LIMIT 2', (family,)).fetchall()
                selected = only[0] if len(only)==1 else None
            if selected:
                summary = store.summary_in_transaction(conn,family,selected[0],as_of=now)
                name = store.data_cipher.open(selected[1], 'children.nickname')
                body = f"Untuk {name}, hari ini ada {summary['counts']['feeding']} catatan minum dan {summary['counts']['diaper']} catatan popok. " + MESSAGE
            body += ' Balas aktivitas yang ingin dicatat, atau “tidak ada” jika tidak ada tambahan.'
        if kind == 'reminder':
            body = 'Pengingat: ' + reminder[0]
        elif kind == 'daily_summary':
            summary = store.summary_in_transaction(conn, family, job[5], as_of=job[0])
            name = store.data_cipher.open(conn.execute('SELECT nickname FROM children WHERE family_id=%s AND id=%s', (family, job[5])).fetchone()[0], "children.nickname")
            expressed = f"{summary['volume_ml']['expressed']} ml" if summary['volume_counts']['expressed'] else 'belum tercatat'
            formula = f"{summary['volume_ml']['formula']} ml" if summary['volume_counts']['formula'] else 'belum tercatat'
            body = (f"Ringkasan {name} · {summary['date']} ({summary['timezone']}): minum {summary['counts']['feeding']}, "
                    f"popok {summary['counts']['diaper']}, tidur {summary['counts']['sleep']} catatan. "
                    f"ASIP {expressed}; formula {formula}. ASI langsung tidak termasuk volume. Data kosong bukan bukti aktivitas tidak terjadi.")
        status = 'simulated' if mode == 'fake' else sender(token, user, body)
        if isinstance(status, RetryAfter):
            conn.execute("UPDATE scheduled_occurrences SET status=CASE WHEN attempts<5 THEN 'pending' ELSE 'failed' END,next_attempt_at=%s WHERE id=%s AND status='attempted'", (now + timedelta(seconds=status.seconds), occurrence))
            return True
        if status not in ('sent', 'failed', 'uncertain', 'simulated'):
            status = 'uncertain'
        conn.execute("UPDATE scheduled_occurrences SET status=%s,finished_at=%s WHERE id=%s AND status='attempted'", (status, now, occurrence))
    return True

