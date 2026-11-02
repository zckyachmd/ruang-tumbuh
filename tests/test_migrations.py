import base64
import hashlib
import os
import secrets
import unittest
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

os.environ.setdefault('APP_DATA_ENCRYPTION_KEY', 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')

from ruang_tumbuh.migrate import migrate
from ruang_tumbuh.privacy import DataCipher, DataIntegrityError, _walk_sensitive_fields, rotate_sensitive_content


class SensitiveDataMigrationTests(unittest.TestCase):
    def test_upgrade_encrypts_existing_sensitive_values(self):
        base_dsn = os.environ['TEST_DATABASE_URL']
        schema = f'encryption_upgrade_{secrets.token_hex(6)}'
        migration_dir = Path(__file__).resolve().parent.parent / 'migrations'
        cipher = DataCipher.from_environment()
        with psycopg.connect(base_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        dsn = make_conninfo(base_dsn, options=f'-csearch_path={schema}')
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute('CREATE TABLE schema_migrations (name text PRIMARY KEY, checksum text NOT NULL)')
                for path in sorted(migration_dir.glob('*.sql')):
                    if path.name == '011_encrypt_sensitive_content.sql':
                        break
                    source = path.read_text(encoding='utf-8')
                    checksum = hashlib.sha256(source.encode()).hexdigest()
                    with conn.transaction():
                        conn.execute(source)
                        conn.execute('INSERT INTO schema_migrations (name,checksum) VALUES (%s,%s)', (path.name, checksum))

                family = conn.execute("INSERT INTO families(name) VALUES ('Legacy Family') RETURNING id").fetchone()[0]
                child = conn.execute("""INSERT INTO children(family_id,nickname,birth_date,sex,premature_notes)
                    VALUES (%s,'Legacy Child','2024-02-03','female','Legacy profile note') RETURNING id""", (family,)).fetchone()[0]
                conn.execute("INSERT INTO family_members(family_id,telegram_user_id,role) VALUES (%s,7,'owner')", (family,))
                conn.execute("""INSERT INTO events(family_id,child_id,kind,payload,occurred_at,created_by)
                    VALUES (%s,%s,'note',%s,now(),7)""", (family, child, Jsonb({'text': 'Legacy event'})))
                conn.execute("INSERT INTO inbound_updates(update_id,telegram_user_id,payload) VALUES (701,7,%s)",
                             (Jsonb({'message': {'text': 'Legacy inbound'}}),))
                conn.execute("INSERT INTO actions(update_id,action_key,request_hash,result) VALUES (701,'invite',%s,%s)",
                             (b'legacy-hash', Jsonb({'token': 'Legacy invite token'})))
                conn.execute("""INSERT INTO notification_preferences(family_id,telegram_user_id,kind,settings)
                    VALUES (%s,7,'checkin',%s)""", (family, Jsonb({'time': '09:00'})))
                conn.execute("INSERT INTO chat_drafts(update_id,telegram_user_id,text,expires_at) VALUES (701,7,'Legacy draft',now()+interval '1 day')")
                conn.execute("INSERT INTO chat_outbox(update_id,recipient_id,body) VALUES (701,7,'Legacy response')")
                conn.execute("INSERT INTO inbound_updates(update_id,telegram_user_id,payload) VALUES (702,7,%s)",
                             (Jsonb({'message': {'text': 'Legacy draft source'}}),))
                conn.execute("""INSERT INTO agent_drafts(update_id,family_id,child_id,telegram_user_id,events,expires_at)
                    VALUES (702,%s,%s,7,%s,now()+interval '1 day')""",
                             (family, child, Jsonb([{'payload': {'text': 'Legacy proposal'}}])))
                conn.execute("""INSERT INTO reminders(family_id,telegram_user_id,body,due_at,expires_at)
                    VALUES (%s,7,'Legacy reminder',now()+interval '1 day',now()+interval '2 days')""", (family,))

            migrate(dsn, migration_dir)

            with psycopg.connect(dsn) as conn:
                values = {
                    'families.name': conn.execute('SELECT name FROM families WHERE id=%s', (family,)).fetchone()[0],
                    'children.nickname': conn.execute('SELECT nickname FROM children WHERE id=%s', (child,)).fetchone()[0],
                    'children.birth_date': conn.execute('SELECT birth_date FROM children WHERE id=%s', (child,)).fetchone()[0],
                    'children.sex': conn.execute('SELECT sex FROM children WHERE id=%s', (child,)).fetchone()[0],
                    'children.premature_notes': conn.execute('SELECT premature_notes FROM children WHERE id=%s', (child,)).fetchone()[0],
                    'events.payload': conn.execute('SELECT payload FROM events WHERE family_id=%s', (family,)).fetchone()[0],
                    'actions.result': conn.execute('SELECT result FROM actions WHERE update_id=701').fetchone()[0],
                    'inbound_updates.payload': conn.execute('SELECT payload FROM inbound_updates WHERE update_id=701').fetchone()[0],
                    'chat_drafts.text': conn.execute('SELECT text FROM chat_drafts WHERE update_id=701').fetchone()[0],
                    'chat_outbox.body': conn.execute('SELECT body FROM chat_outbox WHERE update_id=701').fetchone()[0],
                    'notification_preferences.settings': conn.execute('SELECT settings FROM notification_preferences WHERE family_id=%s', (family,)).fetchone()[0],
                    'agent_drafts.events': conn.execute('SELECT events FROM agent_drafts WHERE update_id=702').fetchone()[0],
                    'reminders.body': conn.execute('SELECT body FROM reminders WHERE family_id=%s', (family,)).fetchone()[0],
                }

            self.assertEqual(cipher.open(values['families.name'], 'families.name'), 'Legacy Family')
            self.assertEqual(cipher.open(values['children.nickname'], 'children.nickname'), 'Legacy Child')
            self.assertEqual(cipher.open(values['children.birth_date'], 'children.birth_date'), '2024-02-03')
            self.assertEqual(cipher.open(values['children.sex'], 'children.sex'), 'female')
            self.assertEqual(cipher.open(values['children.premature_notes'], 'children.premature_notes'), 'Legacy profile note')
            self.assertEqual(cipher.open_json(values['events.payload'], 'events.payload'), {'text': 'Legacy event'})
            self.assertEqual(cipher.open_json(values['actions.result'], 'actions.result'), {'token': 'Legacy invite token'})
            self.assertEqual(cipher.open_json(values['inbound_updates.payload'], 'inbound_updates.payload'), {'message': {'text': 'Legacy inbound'}})
            self.assertEqual(cipher.open(values['chat_drafts.text'], 'chat_drafts.text'), 'Legacy draft')
            self.assertEqual(cipher.open(values['chat_outbox.body'], 'chat_outbox.body'), 'Legacy response')
            self.assertEqual(cipher.open_json(values['notification_preferences.settings'], 'notification_preferences.settings'), {'time': '09:00'})
            self.assertEqual(cipher.open_json(values['agent_drafts.events'], 'agent_drafts.events'), [{'payload': {'text': 'Legacy proposal'}}])
            self.assertEqual(cipher.open(values['reminders.body'], 'reminders.body'), 'Legacy reminder')

            new_cipher = DataCipher(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
            with psycopg.connect(dsn) as conn:
                family_ciphertext = values['families.name']
                conn.execute("UPDATE events SET payload=%s WHERE family_id=%s", (Jsonb('corrupt'), family))
                with self.assertRaises(DataIntegrityError):
                    with conn.transaction():
                        rotate_sensitive_content(conn, cipher, new_cipher)
                self.assertEqual(conn.execute('SELECT name FROM families WHERE id=%s', (family,)).fetchone()[0], family_ciphertext)
                conn.execute('UPDATE events SET payload=%s WHERE family_id=%s', (Jsonb(values['events.payload']), family))
                with conn.transaction():
                    rotate_sensitive_content(conn, cipher, new_cipher)
                for _, _, _, context, is_json, _, encrypted in _walk_sensitive_fields(conn):
                    if encrypted is None or encrypted == '' or encrypted == {}:
                        continue
                    opened = new_cipher.open_json(encrypted, context) if is_json else new_cipher.open(encrypted, context)
                    self.assertIsNotNone(opened)
                    with self.assertRaises(DataIntegrityError):
                        cipher.open(encrypted, context)
        finally:
            with psycopg.connect(base_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    unittest.main()
