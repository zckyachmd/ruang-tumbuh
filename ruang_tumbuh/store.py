"""Transactional family and event operations. Callers must authenticate user IDs."""

import hashlib
import json
import secrets
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from .events import validate, valid_time
from .privacy import DataCipher
from .admission import admit_creator, admit_update

class Denied(Exception):
    pass


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


def validate_entries(entries):
    if not entries:
        raise Invalid()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'kind', 'payload', 'occurred_at'}
                or not isinstance(entry['occurred_at'], datetime) or entry['occurred_at'].utcoffset() is None
                or not validate(entry['kind'], entry['payload']) or not valid_time(entry['kind'], entry['payload'], entry['occurred_at'])):
            raise Invalid()


class Store:
    def __init__(self, dsn):
        self.dsn = dsn
        self.data_cipher = DataCipher.from_environment()

    def _seal(self, value, context):
        return self.data_cipher.seal(value, context)

    def _open(self, value, context):
        return self.data_cipher.open(value, context)

    def _seal_json(self, value, context):
        return self.data_cipher.seal_json(value, context)

    def _open_json(self, value, context):
        return self.data_cipher.open_json(value, context)

    def connect(self):
        return psycopg.connect(self.dsn)

    def new_session(self, user):
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute("INSERT INTO sessions (token_hash,telegram_user_id,expires_at) VALUES (%s,%s,now() + interval '1 hour')", (hashlib.sha256(token.encode()).digest(), user))
        return token

    def session_user(self, token):
        if not isinstance(token, str) or len(token) > 256:
            raise Denied()
        with self.connect() as conn:
            row = conn.execute("SELECT telegram_user_id FROM sessions WHERE token_hash=%s AND expires_at > now()", (hashlib.sha256(token.encode()).digest(),)).fetchone()
            if not row:
                raise Denied()
            return row[0]

    def families(self, user):
        with self.connect() as conn:
            rows = conn.execute("""SELECT f.id,f.name,f.timezone,m.role FROM family_members m
                JOIN families f ON f.id=m.family_id WHERE m.telegram_user_id=%s
                AND m.revoked_at IS NULL AND f.deleted_at IS NULL ORDER BY f.id""", (user,)).fetchall()
            return [(row[0], self._open(row[1], "families.name"), row[2], row[3]) for row in rows]

    def ai_consent(self, family, user, provider_scope):
        with self.connect() as conn:
            self._access(conn, family, user)
            row = conn.execute("SELECT enabled,provider_scope FROM ai_processing_consents WHERE family_id=%s AND telegram_user_id=%s", (family, user)).fetchone()
            return bool(row and row[0] and row[1] == provider_scope)

    def set_ai_consent(self, family, user, enabled, provider_scope):
        if type(enabled) is not bool or not isinstance(provider_scope, str) or len(provider_scope) != 64:
            raise Invalid()
        with self.connect() as conn:
            self._access(conn, family, user)
            conn.execute("""INSERT INTO ai_processing_consents (family_id,telegram_user_id,enabled,provider_scope)
                VALUES (%s,%s,%s,%s) ON CONFLICT (family_id,telegram_user_id)
                DO UPDATE SET enabled=excluded.enabled,provider_scope=excluded.provider_scope,decided_at=now()""", (family, user, enabled, provider_scope))

    def children(self, family, user):
        with self.connect() as conn:
            self._access(conn, family, user)
            rows = conn.execute("SELECT id,nickname,birth_date,sex,premature_notes FROM children WHERE family_id=%s ORDER BY id", (family,)).fetchall()
            return [(row[0], self._open(row[1], "children.nickname"),
                     date.fromisoformat(self._open(row[2], "children.birth_date")) if row[2] else None,
                     self._open(row[3], "children.sex") if row[3] else None,
                     self._open(row[4], "children.premature_notes") if row[4] else None) for row in rows]

    def set_chat_selection(self, family, user, child):
        if type(family) is not int or family <= 0 or type(child) is not int or child <= 0:
            raise Invalid()
        with self.connect() as conn:
            self._access(conn, family, user)
            if not conn.execute("SELECT 1 FROM children WHERE family_id=%s AND id=%s", (family, child)).fetchone():
                raise Invalid()
            conn.execute("""INSERT INTO chat_selections (telegram_user_id,family_id,child_id) VALUES (%s,%s,%s)
                ON CONFLICT (telegram_user_id) DO UPDATE SET family_id=excluded.family_id,child_id=excluded.child_id,selected_at=now()""",
                (user, family, child))

    def chat_selection(self, user):
        with self.connect() as conn:
            row = conn.execute("""SELECT s.family_id,s.child_id,f.name,f.timezone,c.nickname
                FROM chat_selections s JOIN families f ON f.id=s.family_id AND f.deleted_at IS NULL
                JOIN family_members m ON m.family_id=s.family_id AND m.telegram_user_id=s.telegram_user_id AND m.revoked_at IS NULL
                JOIN children c ON c.family_id=s.family_id AND c.id=s.child_id
                WHERE s.telegram_user_id=%s""", (user,)).fetchone()
            return (row[0], row[1], self._open(row[2], "families.name"), row[3],
                    self._open(row[4], "children.nickname")) if row else None

    def save_child(self, family, user, nickname, birth_date, sex, premature_notes, child=None):
        if not isinstance(nickname, str) or not nickname.strip() or len(nickname) > 100 or sex not in (None, 'male', 'female') or (birth_date is not None and (type(birth_date) is not date or birth_date > date.today())) or (premature_notes is not None and (not isinstance(premature_notes, str) or len(premature_notes) > 1000)):
            raise Invalid()
        with self.connect() as conn:
            self._access(conn, family, user, owner=True)
            values = (self._seal(nickname.strip(), "children.nickname"),
                      self._seal(birth_date.isoformat(), "children.birth_date") if birth_date else None,
                      self._seal(sex, "children.sex") if sex else None,
                      self._seal(premature_notes, "children.premature_notes") if premature_notes else None)
            if child is None:
                row = conn.execute('INSERT INTO children (family_id,nickname,birth_date,sex,premature_notes) VALUES (%s,%s,%s,%s,%s) RETURNING id', (family, *values)).fetchone()
            else:
                row = conn.execute('UPDATE children SET nickname=%s,birth_date=%s,sex=%s,premature_notes=%s WHERE family_id=%s AND id=%s RETURNING id', (*values, family, child)).fetchone()
            if not row:
                raise Invalid()
            return row[0]

    def members(self, family, user):
        with self.connect() as conn:
            self._access(conn, family, user)
            return conn.execute('SELECT telegram_user_id,role FROM family_members WHERE family_id=%s AND revoked_at IS NULL ORDER BY telegram_user_id', (family,)).fetchall()

    def set_role(self, family, user, target, role):
        if role not in ('owner', 'member'):
            raise Invalid()
        with self.connect() as conn:
            self._access(conn, family, user, owner=True)
            row = conn.execute('SELECT role FROM family_members WHERE family_id=%s AND telegram_user_id=%s AND revoked_at IS NULL', (family, target)).fetchone()
            if not row:
                raise Invalid()
            if row[0] == 'owner' and role == 'member' and conn.execute("SELECT count(*) FROM family_members WHERE family_id=%s AND role='owner' AND revoked_at IS NULL", (family,)).fetchone()[0] < 2:
                raise Invalid()
            conn.execute('UPDATE family_members SET role=%s WHERE family_id=%s AND telegram_user_id=%s', (role, family, target))
            conn.execute("INSERT INTO audit_log (family_id,actor_id,action,entity_type,entity_id) VALUES (%s,%s,%s,'member',%s)", (family, user, 'role_' + role, target))

    @staticmethod
    def _access(conn, family, user, owner=False):
        # Serialize authorization with revocation and owner changes.
        active = conn.execute("SELECT id FROM families WHERE id=%s AND deleted_at IS NULL FOR UPDATE", (family,)).fetchone()
        row = conn.execute("SELECT role FROM family_members WHERE family_id=%s AND telegram_user_id=%s AND revoked_at IS NULL", (family, user)).fetchone() if active else None
        if row is None or (owner and row[0] != "owner"):
            raise Denied()

    def _chat_action(self, conn, update_id, user, action_key, request):
        if type(update_id) is not int:
            raise Invalid()
        update = conn.execute("SELECT telegram_user_id FROM inbound_updates WHERE update_id=%s FOR UPDATE", (update_id,)).fetchone()
        if not update or update[0] != user:
            raise Denied()
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).digest()
        previous = conn.execute("SELECT request_hash,result FROM actions WHERE update_id=%s AND action_key=%s", (update_id, action_key)).fetchone()
        if previous:
            if bytes(previous[0]) != fingerprint:
                raise Conflict()
            return fingerprint, self._open_json(previous[1], "actions.result")
        return fingerprint, None

    def create_family(self, user, name, nickname, zone="Asia/Jakarta", *, update_id=None):
        if (not isinstance(name, str) or not name.strip() or len(name.strip()) > 100
                or not isinstance(nickname, str) or not nickname.strip() or len(nickname.strip()) > 100):
            raise Invalid()
        if not admit_creator(user):
            raise Denied()
        try:
            ZoneInfo(zone)
        except (ValueError, KeyError):
            raise Invalid() from None
        with self.connect() as conn:
            fingerprint = None
            if update_id is not None:
                fingerprint, previous = self._chat_action(conn, update_id, user, 'create_family', {'name': name.strip(), 'nickname': nickname.strip(), 'zone': zone})
                if previous:
                    return previous['family_id'], previous['child_id']
            family = conn.execute("INSERT INTO families (name, timezone) VALUES (%s,%s) RETURNING id", (self._seal(name.strip(), "families.name"), zone)).fetchone()[0]
            conn.execute("INSERT INTO family_members (family_id, telegram_user_id, role) VALUES (%s,%s,'owner')", (family, user))
            child = conn.execute("INSERT INTO children (family_id,nickname) VALUES (%s,%s) RETURNING id", (family, self._seal(nickname.strip(), "children.nickname"))).fetchone()[0]
            if update_id is not None:
                conn.execute("INSERT INTO actions (update_id,action_key,request_hash,result) VALUES (%s,'create_family',%s,%s)",
                             (update_id, fingerprint, Jsonb(self._seal_json({'family_id': family, 'child_id': child}, "actions.result"))))
        return family, child

    def invite(self, family, user, lifetime=timedelta(hours=24), *, update_id=None):
        if not isinstance(lifetime, timedelta) or lifetime <= timedelta(0) or lifetime > timedelta(days=7):
            raise Invalid()
        token = None
        with self.connect() as conn:
            self._access(conn, family, user, owner=True)
            fingerprint = None
            if update_id is not None:
                fingerprint, previous = self._chat_action(conn, update_id, user, 'create_invitation', {'family': family, 'lifetime_seconds': lifetime.total_seconds()})
                if previous:
                    return previous['token']
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO invitations (family_id,token_hash,expires_at) VALUES (%s,%s,%s)",
                         (family, hashlib.sha256(token.encode()).digest(), datetime.now(timezone.utc) + lifetime))
            if update_id is not None:
                conn.execute("INSERT INTO actions (update_id,action_key,request_hash,result) VALUES (%s,'create_invitation',%s,%s)",
                             (update_id, fingerprint, Jsonb(self._seal_json({'token': token}, "actions.result"))))
        return token

    def redeem(self, user, token, *, update_id=None):
        if not isinstance(token, str) or not 1 <= len(token) <= 256:
            raise Invalid()
        digest = hashlib.sha256(token.encode()).digest()
        with self.connect() as conn:
            fingerprint = None
            if update_id is not None:
                fingerprint, previous = self._chat_action(conn, update_id, user, 'redeem_invitation', {'token_hash': digest.hex()})
                if previous:
                    return previous['family_id']
            candidate = conn.execute('SELECT family_id FROM invitations WHERE token_hash=%s', (digest,)).fetchone()
            if not candidate:
                raise Invalid()
            active = conn.execute("SELECT id FROM families WHERE id=%s AND deleted_at IS NULL FOR UPDATE", (candidate[0],)).fetchone()
            if not active:
                raise Invalid()
            row = conn.execute("""UPDATE invitations SET used_at=now(), used_by=%s
                WHERE token_hash=%s AND used_at IS NULL AND expires_at > now()
                RETURNING family_id""", (user, digest)).fetchone()
            if not row:
                raise Invalid()
            family = row[0]
            conn.execute("""INSERT INTO family_members (family_id,telegram_user_id,role) VALUES (%s,%s,'member')
                ON CONFLICT (family_id,telegram_user_id) DO UPDATE SET revoked_at=NULL""", (family, user))
            if update_id is not None:
                conn.execute("INSERT INTO actions (update_id,action_key,request_hash,result) VALUES (%s,'redeem_invitation',%s,%s)",
                             (update_id, fingerprint, Jsonb(self._seal_json({'family_id': family}, "actions.result"))))
        return family

    def revoke(self, family, actor, target):
        with self.connect() as conn:
            self._access(conn, family, actor, owner=True)
            member = conn.execute("SELECT role FROM family_members WHERE family_id=%s AND telegram_user_id=%s AND revoked_at IS NULL", (family, target)).fetchone()
            if not member:
                raise Invalid()
            if member[0] == "owner" and conn.execute("SELECT count(*) FROM family_members WHERE family_id=%s AND role='owner' AND revoked_at IS NULL", (family,)).fetchone()[0] < 2:
                raise Invalid()
            conn.execute("UPDATE family_members SET revoked_at=now() WHERE family_id=%s AND telegram_user_id=%s", (family, target))
            conn.execute("DELETE FROM chat_selections WHERE family_id=%s AND telegram_user_id=%s", (family, target))
            conn.execute('DELETE FROM conversation_contexts WHERE family_id=%s AND telegram_user_id=%s', (family, target))
            conn.execute("UPDATE notification_preferences SET enabled=false WHERE family_id=%s AND telegram_user_id=%s", (family, target))
            conn.execute("UPDATE ai_processing_consents SET enabled=false,decided_at=now() WHERE family_id=%s AND telegram_user_id=%s", (family, target))
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled' WHERE family_id=%s AND telegram_user_id=%s AND status IN ('pending','claimed')", (family, target))
            conn.execute("INSERT INTO audit_log (family_id,actor_id,action,entity_type,entity_id) VALUES (%s,%s,'revoke','member',%s)", (family, actor, target))

    def record_update(self, update_id, user, payload):
        """Persist a verified Telegram update once; reject conflicting reuse."""
        if type(update_id) is not int or type(user) is not int or not isinstance(payload, dict):
            raise Invalid()
        with self.connect() as conn:
            admit_update(conn, update_id, user)
            encrypted = self._seal_json(payload, "inbound_updates.payload")
            row = conn.execute("""INSERT INTO inbound_updates (update_id,telegram_user_id,payload)
                VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING update_id""", (update_id, user, Jsonb(encrypted))).fetchone()
            if row:
                return True
            existing = conn.execute("SELECT telegram_user_id,payload,status FROM inbound_updates WHERE update_id=%s", (update_id,)).fetchone()
            if existing and existing[0] == user and existing[1] == {} and existing[2] in ('completed', 'failed'):
                return False
            prior_payload = existing[1] if existing and existing[1] == {} else self._open_json(existing[1], "inbound_updates.payload") if existing else None
            if not existing or existing[0] != user or prior_payload != payload:
                raise Conflict()
        return False

    def create_events(self, family, user, child, entries, *, update_id=None, action_key=None, request_key=None):
        validate_entries(entries)
        if (update_id is None) != (action_key is None) or (action_key is not None and (not isinstance(action_key, str) or not 0 < len(action_key) <= 200)):
            raise Invalid()
        if request_key is not None and (update_id is not None or not isinstance(request_key, str) or not 0 < len(request_key) <= 200):
            raise Invalid()
        request = {'family': family, 'user': user, 'child': child, 'entries': [dict(e, occurred_at=e['occurred_at'].isoformat()) for e in entries]}
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).digest()
        ids = []
        with self.connect() as conn:
            self._access(conn, family, user)
            if request_key is not None:
                inserted = conn.execute("""INSERT INTO api_actions (telegram_user_id,action_key,request_hash,family_id)
                    VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING action_key""", (user, request_key, fingerprint, family)).fetchone()
                if not inserted:
                    previous = conn.execute("SELECT request_hash,result FROM api_actions WHERE telegram_user_id=%s AND action_key=%s", (user, request_key)).fetchone()
                    if bytes(previous[0]) != fingerprint:
                        raise Conflict()
                    return previous[1]['event_ids']
            if update_id is not None:
                update = conn.execute("SELECT telegram_user_id FROM inbound_updates WHERE update_id=%s FOR UPDATE", (update_id,)).fetchone()
                if not update or update[0] != user:
                    raise Denied()
                action = conn.execute("SELECT request_hash,result FROM actions WHERE update_id=%s AND action_key=%s", (update_id, action_key)).fetchone()
                if action:
                    if bytes(action[0]) != fingerprint:
                        raise Conflict()
                    return self._open_json(action[1], "actions.result")['event_ids']
            if not conn.execute("SELECT 1 FROM children WHERE family_id=%s AND id=%s", (family, child)).fetchone():
                raise Invalid()
            for entry in entries:
                ids.append(conn.execute("""INSERT INTO events (family_id,child_id,kind,payload,occurred_at,created_by)
                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""", (family, child, entry['kind'], Jsonb(self._seal_json(entry['payload'], "events.payload")), entry['occurred_at'], user)).fetchone()[0])
            if update_id is not None:
                conn.execute("INSERT INTO actions (update_id,action_key,request_hash,result) VALUES (%s,%s,%s,%s)", (update_id, action_key, fingerprint, Jsonb(self._seal_json({'event_ids': ids}, "actions.result"))))
            if request_key is not None:
                conn.execute("UPDATE api_actions SET result=%s WHERE telegram_user_id=%s AND action_key=%s", (Jsonb({'event_ids': ids}), user, request_key))
        return ids

    def confirm_agent_draft(self, family, user, draft_id, *, child=None):
        with self.connect() as conn:
            self._access(conn, family, user)
            row = conn.execute("SELECT events,child_id,status FROM agent_drafts WHERE update_id=%s AND family_id=%s AND telegram_user_id=%s AND expires_at>now() FOR UPDATE", (draft_id, family, user)).fetchone()
            if not row or row[2] == 'cancelled' or (child is not None and row[1] != child):
                raise Invalid()
            entries = [dict(item, occurred_at=datetime.fromisoformat(item['occurred_at'])) for item in self._open_json(row[0], "agent_drafts.events")]
            validate_entries(entries)
            previous = conn.execute("SELECT result FROM actions WHERE update_id=%s AND action_key='create_events'", (draft_id,)).fetchone()
            if row[2] == 'confirmed':
                if not previous:
                    raise Conflict()
                return entries, self._open_json(previous[0], "actions.result")['event_ids']
            if previous:
                raise Conflict()
            ids = []
            for entry in entries:
                ids.append(conn.execute("""INSERT INTO events (family_id,child_id,kind,payload,occurred_at,created_by)
                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""", (family, row[1], entry['kind'], Jsonb(self._seal_json(entry['payload'], "events.payload")), entry['occurred_at'], user)).fetchone()[0])
            request = {'family': family, 'user': user, 'child': row[1], 'entries': [dict(e, occurred_at=e['occurred_at'].isoformat()) for e in entries]}
            fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).digest()
            conn.execute("INSERT INTO actions (update_id,action_key,request_hash,result) VALUES (%s,'create_events',%s,%s)", (draft_id, fingerprint, Jsonb(self._seal_json({'event_ids': ids}, "actions.result"))))
            conn.execute("UPDATE agent_drafts SET status='confirmed' WHERE update_id=%s", (draft_id,))
        return entries, ids

    def cancel_agent_draft(self, family, user, draft_id):
        with self.connect() as conn:
            self._access(conn, family, user)
            return bool(conn.execute("UPDATE agent_drafts SET status='cancelled' WHERE update_id=%s AND family_id=%s AND telegram_user_id=%s AND status='pending' AND expires_at>now() RETURNING update_id", (draft_id, family, user)).fetchone())

    def timeline(self, family, user, child, *, limit=50, offset=0, kind=None):
        with self.connect() as conn:
            self._access(conn, family, user)
            rows = conn.execute("""SELECT id,kind,payload,occurred_at,version FROM events
                WHERE family_id=%s AND child_id=%s AND deleted_at IS NULL AND (%s::text IS NULL OR kind=%s)
                ORDER BY occurred_at DESC,id DESC LIMIT %s OFFSET %s""", (family, child, kind, kind, limit, offset)).fetchall()
            return [(row[0], row[1], self._open_json(row[2], "events.payload"), row[3], row[4]) for row in rows]

    def family_timezone(self, family, user):
        with self.connect() as conn:
            self._access(conn, family, user)
            return conn.execute('SELECT timezone FROM families WHERE id=%s', (family,)).fetchone()[0]

    def summary_in_transaction(self, conn, family, child, *, as_of=None):
        zone = ZoneInfo(conn.execute('SELECT timezone FROM families WHERE id=%s', (family,)).fetchone()[0])
        if not conn.execute('SELECT 1 FROM children WHERE family_id=%s AND id=%s', (family, child)).fetchone():
            raise Invalid()
        today = (as_of.astimezone(zone) if as_of else datetime.now(zone)).date()
        start = datetime.combine(today, time.min, zone).astimezone(timezone.utc)
        end = datetime.combine(today + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        rows = conn.execute("""SELECT kind,payload FROM events WHERE family_id=%s AND child_id=%s
                AND deleted_at IS NULL AND occurred_at >= %s AND occurred_at < %s""", (family, child, start, end)).fetchall()
        counts = {kind: 0 for kind in ('feeding', 'diaper', 'sleep', 'growth', 'note')}
        volumes = {'expressed': 0, 'formula': 0}
        volume_counts = {'expressed': 0, 'formula': 0}
        for kind, payload in rows:
            payload = self._open_json(payload, "events.payload")
            counts[kind] += 1
            if kind == 'feeding' and payload.get('type') in volumes and 'volume_ml' in payload:
                volumes[payload['type']] += payload['volume_ml']
                volume_counts[payload['type']] += 1
        return {'date': today.isoformat(), 'timezone': zone.key, 'counts': counts, 'volume_ml': volumes, 'volume_counts': volume_counts}

    def today_summary(self, family, user, child, *, as_of=None):
        with self.connect() as conn:
            self._access(conn, family, user)
            return self.summary_in_transaction(conn, family, child, as_of=as_of)

    def last_event(self, family, user, child, category, before):
        kinds = {'feeding': 'feeding', 'poop': 'diaper', 'growth': 'growth'}
        if category not in kinds:
            raise Invalid()
        with self.connect() as conn:
            self._access(conn, family, user)
            # A server cursor bounds memory even when encrypted diaper subtype requires scanning.
            with conn.cursor(name='last_event') as cursor:
                cursor.itersize = 100
                cursor.execute("""SELECT kind,payload,occurred_at FROM events WHERE family_id=%s AND child_id=%s
                    AND kind=%s AND deleted_at IS NULL AND occurred_at<=%s
                    ORDER BY occurred_at DESC,id DESC""" + (" LIMIT 1" if category != 'poop' else ''),
                    (family, child, kinds[category], before))
                for kind, payload, occurred_at in cursor:
                    payload = self._open_json(payload, "events.payload")
                    if category != 'poop' or payload.get('type') in ('pup', 'both'):
                        return kind, payload, occurred_at
            return None

    def agent_usage(self, family, user):
        with self.connect() as conn:
            self._access(conn, family, user, owner=True)
            return conn.execute('SELECT model, sum(input_tokens), sum(output_tokens) FROM agent_usage WHERE family_id=%s GROUP BY model ORDER BY model', (family,)).fetchall()

    def update_event(self, family, user, event, version, payload, occurred_at):
        if not isinstance(payload, dict) or not isinstance(occurred_at, datetime) or occurred_at.utcoffset() is None:
            raise Invalid()
        with self.connect() as conn:
            self._access(conn, family, user)
            existing = conn.execute("SELECT kind FROM events WHERE family_id=%s AND id=%s AND deleted_at IS NULL", (family, event)).fetchone()
            if not existing:
                raise Conflict()
            if not validate(existing[0], payload) or not valid_time(existing[0], payload, occurred_at):
                raise Invalid()
            result = conn.execute("""UPDATE events SET payload=%s, occurred_at=%s, updated_at=now(),version=version+1
                WHERE family_id=%s AND id=%s AND version=%s AND deleted_at IS NULL RETURNING version""",
                (Jsonb(self._seal_json(payload, "events.payload")), occurred_at, family, event, version)).fetchone()
            if not result:
                raise Conflict()
            conn.execute("INSERT INTO audit_log (family_id,actor_id,action,entity_type,entity_id) VALUES (%s,%s,'update','event',%s)", (family, user, event))
        return result[0]

    def delete_event(self, family, user, event, version):
        with self.connect() as conn:
            self._access(conn, family, user)
            row = conn.execute("""UPDATE events SET deleted_at=now(),updated_at=now(),version=version+1
                WHERE family_id=%s AND id=%s AND version=%s AND deleted_at IS NULL RETURNING id""", (family, event, version)).fetchone()
            if not row:
                existing = conn.execute('SELECT version,deleted_at FROM events WHERE family_id=%s AND id=%s', (family, event)).fetchone()
                if existing and existing[1] is not None and existing[0] == version + 1:
                    return
                raise Conflict()
            conn.execute("INSERT INTO audit_log (family_id,actor_id,action,entity_type,entity_id) VALUES (%s,%s,'delete','event',%s)", (family, user, event))

    def request_family_deletion(self, family, user):
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            self._access(conn, family, user, owner=True)
            conn.execute("INSERT INTO family_deletion_requests (token_hash,family_id,actor_id,expires_at) VALUES (%s,%s,%s,now()+interval '10 minutes')", (hashlib.sha256(token.encode()).digest(), family, user))
        return token

    def delete_family(self, family, user, token, phrase):
        if phrase != 'HAPUS KELUARGA' or not isinstance(token, str) or not 1 <= len(token) <= 256:
            raise Invalid()
        digest = hashlib.sha256(token.encode()).digest()
        with self.connect() as conn:
            receipt = conn.execute('SELECT 1 FROM family_deletion_receipts WHERE family_id=%s AND actor_id=%s AND token_hash=%s', (family, user, digest)).fetchone()
            if receipt:
                return
            try:
                self._access(conn, family, user, owner=True)
            except Denied:
                receipt = conn.execute('SELECT 1 FROM family_deletion_receipts WHERE family_id=%s AND actor_id=%s AND token_hash=%s', (family, user, digest)).fetchone()
                if receipt:
                    return
                raise
            request = conn.execute('SELECT 1 FROM family_deletion_requests WHERE token_hash=%s AND family_id=%s AND actor_id=%s AND expires_at > now() FOR UPDATE', (digest, family, user)).fetchone()
            if not request:
                raise Invalid()
            conn.execute('INSERT INTO family_deletion_receipts (family_id,actor_id,token_hash) VALUES (%s,%s,%s)', (family, user, digest))
            conn.execute('DELETE FROM chat_outbox WHERE family_id=%s OR update_id IN (SELECT update_id FROM inbound_updates WHERE family_id=%s)', (family, family))
            conn.execute('DELETE FROM agent_drafts WHERE family_id=%s', (family,))
            conn.execute('DELETE FROM conversation_contexts WHERE family_id=%s', (family,))
            conn.execute('DELETE FROM agent_usage WHERE family_id=%s', (family,))
            conn.execute('DELETE FROM chat_drafts WHERE update_id IN (SELECT update_id FROM inbound_updates WHERE family_id=%s)', (family,))
            conn.execute('DELETE FROM actions WHERE update_id IN (SELECT update_id FROM inbound_updates WHERE family_id=%s)', (family,))
            conn.execute("UPDATE inbound_updates SET family_id=NULL,payload='{}'::jsonb,status='completed',lease_until=NULL,lease_token=NULL WHERE family_id=%s", (family,))
            conn.execute('DELETE FROM api_actions WHERE family_id=%s', (family,))
            conn.execute('DELETE FROM family_deletion_requests WHERE family_id=%s', (family,))
            for table in ('checkin_answers', 'scheduled_occurrences', 'reminders', 'notification_preferences', 'ai_processing_consents', 'events', 'children', 'invitations', 'audit_log', 'family_members'):
                conn.execute(f'DELETE FROM {table} WHERE family_id=%s', (family,))
            conn.execute('DELETE FROM families WHERE id=%s', (family,))

