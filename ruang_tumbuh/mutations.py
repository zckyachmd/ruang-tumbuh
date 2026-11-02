"""Chat changes: persisted proposals, explicit confirmation, version checks and audit."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from psycopg.types.json import Jsonb

from .events import validate, valid_time
from .store import Invalid, Conflict


def propose_change(store, family, user, child, proposal, context):
    if proposal['operation'] in ('edit', 'delete'):
        records = context.get('records', []) if context and context.get('kind') == 'records' else []
        number = proposal['candidate']
        if not 1 <= number <= len(records):
            return None
        record = records[number-1]
        change = {'operation': proposal['operation'], 'event_id': record['id'], 'version': record['version'], 'kind': record['kind']}
        if change['operation'] == 'edit':
            payload = {**record['payload'], **proposal['payload']} if proposal['payload'] is not None else record['payload']
            instant = proposal['occurred_at'] or record['occurred_at']
            occurred = datetime.fromisoformat(instant)
            if occurred.utcoffset() is None or not validate(record['kind'], payload) or not valid_time(record['kind'], payload, occurred):
                raise Invalid()
            change.update(payload=payload, occurred_at=instant)
        return change
    if proposal['operation'] == 'preferences':
        from .checkins import get_preferences, validate_kind_settings
        pref_kind = proposal['notification_kind']
        old = get_preferences(store,family,user,pref_kind)
        if proposal['enabled'] and old['settings'] is None and proposal['time'] is None and pref_kind != 'reminder':
            return None
        settings = dict(old['settings'] or {'time':'09:00','timezone':store.family_timezone(family,user),
            'quiet_start':None,'quiet_end':None,'snoozed_until':None,'max_daily':5 if pref_kind=='reminder' else 1})
        for key in ('time','quiet_start','quiet_end','max_daily'):
            if proposal[key] is not None:settings[key]=proposal[key]
        if proposal['clear_quiet_hours']:settings.update(quiet_start=None,quiet_end=None)
        if pref_kind=='daily_summary':settings['child_id']=child
        validate_kind_settings(pref_kind,settings)
        return {'operation':'preferences','notification_kind':pref_kind,'enabled':proposal['enabled'],'settings':settings,'expected':old}
    if proposal['operation'] == 'reminder':
        return {'operation': 'reminder', 'body': proposal['body'], 'due_at': proposal['due_at'], 'bypass_quiet_hours': proposal['bypass_quiet_hours']}
    if proposal['operation'] == 'cancel_reminder':
        # Candidate is a bounded ordinal from authenticated reminder listing, never a model-selected DB ID.
        records = context.get('reminders', []) if context and context.get('kind') == 'reminders' else []
        if not 1 <= proposal['candidate'] <= len(records):
            return None
        return {'operation': 'cancel_reminder', 'reminder_id': records[proposal['candidate']-1]}
    raise Invalid()


def confirm_change(store, family, user, child, draft_id, cancel=False):
    with store.connect() as conn:
        store._access(conn, family, user)
        row = conn.execute('SELECT content,status FROM chat_mutations WHERE update_id=%s AND family_id=%s AND telegram_user_id=%s AND child_id=%s AND expires_at>now() FOR UPDATE', (draft_id, family, user, child)).fetchone()
        if not row or row[1] == 'cancelled':
            raise Invalid()
        if row[1] == 'confirmed':
            return 'Perubahan ini sudah diterapkan sebelumnya.'
        if cancel:
            conn.execute("UPDATE chat_mutations SET status='cancelled' WHERE update_id=%s", (draft_id,))
            return 'Usulan dibatalkan. Data tidak diubah.'
        change = store.data_cipher.open_json(row[0], 'chat_mutations.content')
        op = change['operation']
        if op in ('edit', 'delete'):
            event = conn.execute('SELECT version,kind FROM events WHERE family_id=%s AND child_id=%s AND id=%s AND deleted_at IS NULL FOR UPDATE', (family, child, change['event_id'])).fetchone()
            if not event or event[0] != change['version'] or event[1] != change['kind']:
                raise Conflict()
            if op == 'edit':
                occurred = datetime.fromisoformat(change['occurred_at'])
                if occurred > datetime.now(timezone.utc) or occurred.utcoffset() is None or not validate(event[1], change['payload']) or not valid_time(event[1], change['payload'], occurred):
                    raise Invalid()
                conn.execute('UPDATE events SET payload=%s,occurred_at=%s,lookup_token=%s,version=version+1,updated_at=now() WHERE id=%s',
                             (Jsonb(store.data_cipher.seal_json(change['payload'], 'events.payload')), occurred, store.data_cipher.lookup_token(family, event[1], change['payload']), change['event_id']))
            else:
                conn.execute('UPDATE events SET deleted_at=now(),updated_at=now(),version=version+1 WHERE id=%s', (change['event_id'],))
            conn.execute("INSERT INTO audit_log(family_id,actor_id,action,entity_type,entity_id) VALUES (%s,%s,%s,'event',%s)", (family, user, op, change['event_id']))
        elif op == 'preferences':
            from .checkins import set_preferences_in_transaction
            pref_kind=change['notification_kind']
            row=conn.execute('SELECT enabled,settings FROM notification_preferences WHERE family_id=%s AND telegram_user_id=%s AND kind=%s', (family,user,pref_kind)).fetchone()
            current={'enabled':row[0],'settings':store.data_cipher.open_json(row[1],'notification_preferences.settings')} if row else {'enabled':False,'settings':None}
            if current!=change['expected']:
                raise Conflict()
            set_preferences_in_transaction(conn,store,family,user,change['enabled'],change['settings'],pref_kind)
        elif op == 'reminder':
            now = datetime.now(timezone.utc)
            due = datetime.fromisoformat(change['due_at'])
            if due.utcoffset() is None or not now < due <= now+timedelta(days=366):
                raise Invalid()
            pref = conn.execute("SELECT enabled FROM notification_preferences WHERE family_id=%s AND telegram_user_id=%s AND kind='reminder'", (family, user)).fetchone()
            if not pref or not pref[0]:
                raise Invalid()
            zone = ZoneInfo(conn.execute('SELECT timezone FROM families WHERE id=%s', (family,)).fetchone()[0])
            expiry = due+timedelta(hours=1)
            reminder = conn.execute('INSERT INTO reminders(family_id,telegram_user_id,body,due_at,expires_at,bypass_quiet_hours) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                                    (family, user, store.data_cipher.seal(change['body'], 'reminders.body'), due, expiry, change['bypass_quiet_hours'])).fetchone()[0]
            conn.execute("INSERT INTO scheduled_occurrences(family_id,telegram_user_id,occurrence_key,due_at,expires_at,kind,local_date,reminder_id) VALUES (%s,%s,%s,%s,%s,'reminder',%s,%s)", (family, user, 'reminder:'+str(reminder), due, expiry, due.astimezone(zone).date(), reminder))
        elif op == 'cancel_reminder':
            changed = conn.execute('UPDATE reminders SET cancelled_at=now() WHERE family_id=%s AND telegram_user_id=%s AND id=%s RETURNING id', (family, user, change['reminder_id'])).fetchone()
            if not changed:
                raise Invalid()
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled' WHERE family_id=%s AND telegram_user_id=%s AND reminder_id=%s AND status IN ('pending','claimed')", (family, user, change['reminder_id']))
        else:
            raise Invalid()
        conn.execute("UPDATE chat_mutations SET status='confirmed' WHERE update_id=%s", (draft_id,))
        return 'Sudah diterapkan 🤍 Perubahan tersimpan.'
