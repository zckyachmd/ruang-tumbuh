"""Operator admission and atomic request budgets, independent of data consent."""

import os


class BudgetExceeded(Exception):
    pass


class QueueFull(Exception):
    pass


def admit_update(conn, update_id, user):
    conn.execute('SELECT pg_advisory_xact_lock(%s)', (391072850,))
    if conn.execute('SELECT 1 FROM inbound_updates WHERE update_id=%s', (update_id,)).fetchone():
        return
    global_limit = int(os.getenv('INBOUND_GLOBAL_LIMIT', '10000'))
    user_limit = int(os.getenv('INBOUND_USER_LIMIT', '20'))
    if not 1 <= global_limit <= 100000 or not 1 <= user_limit <= 1000:
        raise ValueError('Invalid inbound limits')
    row = conn.execute("SELECT count(*),count(*) FILTER (WHERE telegram_user_id=%s) FROM inbound_updates WHERE status IN ('pending','processing')", (user,)).fetchone()
    if row[0] >= global_limit or row[1] >= user_limit:
        raise QueueFull()


def allowed_ids(name):
    raw = os.getenv(name, '')
    try:
        return {int(value.strip()) for value in raw.split(',') if value.strip() and int(value.strip()) > 0}
    except ValueError as exc:
        raise ValueError(name + ' must contain positive integer IDs') from exc


def admit_creator(user):
    return os.getenv('APP_ENV', 'production') == 'development' or user in allowed_ids('FAMILY_CREATOR_IDS')


def reserve_ai(conn, family, user, update_id):
    # Serialize the global daily counter before taking the family lock.
    conn.execute('SELECT pg_advisory_xact_lock(%s)', (391072849,))
    if os.getenv('AI_PAUSED', '0') == '1':
        raise BudgetExceeded()
    if os.getenv('APP_ENV', 'production') != 'development' and family not in allowed_ids('AI_FAMILY_IDS'):
        raise BudgetExceeded()
    limits = [('AI_GLOBAL_DAILY_REQUESTS', 500, ''),
              ('AI_FAMILY_DAILY_REQUESTS', 100, ' AND family_id=%s'),
              ('AI_USER_MINUTE_REQUESTS', 5, ' AND telegram_user_id=%s')]
    for name, default, clause in limits:
        limit = int(os.getenv(name, str(default)))
        if not 1 <= limit <= 100000:
            raise ValueError(name + ' out of range')
        interval = '1 minute' if 'MINUTE' in name else '1 day'
        params = (user,) if 'USER' in name else (family,) if clause else ()
        count = conn.execute("SELECT count(*) FROM ai_reservations WHERE reserved_at>now()-interval '" + interval + "'" + clause, params).fetchone()[0]
        if count >= limit:
            raise BudgetExceeded()
    conn.execute('INSERT INTO ai_reservations(update_id,family_id,telegram_user_id) VALUES (%s,%s,%s)', (update_id, family, user))
