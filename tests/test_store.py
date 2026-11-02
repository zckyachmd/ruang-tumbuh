import hashlib
import csv
import io
import json
import os
import re
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('APP_DATA_ENCRYPTION_KEY', 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from ruang_tumbuh.api import create_app, local_instant
from ruang_tumbuh import chat_worker
from ruang_tumbuh.chat_worker import process_one
from ruang_tumbuh.agent import OpenAICompatibleProvider, ai_consent_scope
from ruang_tumbuh.delivery import deliver_one
from ruang_tumbuh.migrate import migrate
from ruang_tumbuh.checkins import acknowledge, deliver_checkin, get_preferences, schedule_today, set_preferences
from ruang_tumbuh.retention import cleanup
from ruang_tumbuh.reminders import cancel_reminder, create_reminder, list_reminders
from ruang_tumbuh.store import Conflict, Denied, Invalid, Store
from ruang_tumbuh.telegram_polling import polling_loop
from ruang_tumbuh.privacy import encrypt_existing_sensitive_content
from ruang_tumbuh.events import validate
from test_telegram_auth import signed_data


def compatible_tool_response(name, arguments, usage=None):
    result = {'choices': [{'message': {'tool_calls': [{'type': 'function', 'function': {
        'name': name, 'arguments': arguments}}]}}]}
    if usage is not None:
        result['usage'] = usage
    return result


class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['TEST_DATABASE_URL']
        migrate(cls.dsn, Path('migrations'))

    def setUp(self):
        self.store = Store(self.dsn)
        with self.store.connect() as conn:
            conn.execute("UPDATE notification_preferences SET enabled=false")
            conn.execute("UPDATE scheduled_occurrences SET status='cancelled' WHERE status='pending'")
            conn.execute("UPDATE chat_outbox SET status='simulated' WHERE status='pending'")
        self.family, self.child = self.store.create_family(1, 'Keluarga', 'Anak')

    def test_worker_reads_openai_compatible_provider_configuration(self):
        class StopWorker(Exception):
            pass

        environment = {
            'DATABASE_URL': 'postgresql://synthetic',
            'CHAT_CONTENT_RETENTION_DAYS': '7',
            'TELEGRAM_DELIVERY': 'disabled',
            'AI_PROVIDER': 'openai-compatible',
            'AI_API_KEY': 'synthetic-key',
            'AI_MODEL': 'synthetic-model',
            'AI_BASE_URL': 'https://ai.example/v1',
        }
        with (patch.dict(os.environ, environment, clear=True),
              patch.object(chat_worker, 'Store', return_value=object()),
              patch('ruang_tumbuh.retention.cleanup'),
              patch.object(chat_worker.signal, 'signal'),
              patch.object(chat_worker, 'process_one', side_effect=StopWorker) as process_mock):
            with self.assertRaises(StopWorker):
                chat_worker.main()

        provider = process_mock.call_args.args[1]
        self.assertIsInstance(provider, OpenAICompatibleProvider)
        self.assertEqual((provider.api_key, provider.model, provider.base_url),
                         ('synthetic-key', 'synthetic-model', 'https://ai.example/v1'))

    def test_membership_and_family_isolation(self):
        for user in (2, 3):
            token = self.store.invite(self.family, 1)
            self.assertEqual(self.store.redeem(user, token), self.family)
            with self.assertRaises(Invalid):
                self.store.redeem(4, token)
        now = datetime.now(timezone.utc)
        self.store.create_events(self.family, 2, self.child, [{'kind': 'note', 'payload': {'text': 'uji'}, 'occurred_at': now}])
        self.assertEqual(len(self.store.timeline(self.family, 3, self.child)), 1)
        with self.assertRaises(Denied):
            self.store.timeline(self.family, 4, self.child)
        with self.assertRaises(Invalid):
            self.store.revoke(self.family, 1, 1)
        self.store.revoke(self.family, 1, 2)
        with self.assertRaises(Denied):
            self.store.timeline(self.family, 2, self.child)
        other, other_child = self.store.create_family(4, 'Lain', 'Anak lain')
        with self.assertRaises(Denied):
            self.store.timeline(other, 3, other_child)

    def test_growth_capture_requires_explicit_matching_position(self):
        self.assertTrue(validate('growth', {'type': 'length', 'value': 54.2, 'unit': 'cm', 'position': 'recumbent'}))
        self.assertTrue(validate('growth', {'type': 'height', 'value': 88.1, 'unit': 'cm', 'position': 'standing'}))
        self.assertTrue(validate('growth', {'type': 'weight', 'value': 8.4, 'unit': 'kg'}))
        for payload in (
            {'type': 'length', 'value': 54.2, 'unit': 'cm'},
            {'type': 'length', 'value': 54.2, 'unit': 'cm', 'position': 'standing'},
            {'type': 'height', 'value': 88.1, 'unit': 'cm', 'position': 'recumbent'},
            {'type': 'weight', 'value': 8.4, 'unit': 'kg', 'position': 'standing'},
            {'type': 'height', 'value': 88.1, 'unit': 'cm', 'position': 'standing', 'method': []},
            {'type': [], 'value': 88.1, 'unit': 'cm', 'position': 'standing'},
        ):
            with self.subTest(payload=payload):
                self.assertFalse(validate('growth', payload))

    def test_sensitive_content_backfill_encrypts_legacy_values(self):
        update_id = 991234567
        self.store.record_update(update_id, 1, {'message': {'text': 'legacy message'}})
        now = datetime.now(timezone.utc)
        event_id = self.store.create_events(self.family, 1, self.child, [
            {'kind': 'note', 'payload': {'text': 'temporary'}, 'occurred_at': now}
        ])[0]
        with self.store.connect() as conn:
            conn.execute("""UPDATE families SET name='Legacy Family' WHERE id=%s""", (self.family,))
            conn.execute("""UPDATE children SET nickname='Legacy Child',birth_date='2024-02-03',sex='female',premature_notes='Legacy note' WHERE id=%s""", (self.child,))
            conn.execute("UPDATE events SET payload=%s WHERE id=%s", (Jsonb({'text': 'legacy event'}), event_id))
            conn.execute("UPDATE inbound_updates SET payload=%s WHERE update_id=%s", (Jsonb({'message': {'text': 'legacy inbound'}}), update_id))
            encrypt_existing_sensitive_content(conn, self.store.data_cipher)
            family_name = conn.execute('SELECT name FROM families WHERE id=%s', (self.family,)).fetchone()[0]
            child = conn.execute('SELECT nickname,birth_date,sex,premature_notes FROM children WHERE id=%s', (self.child,)).fetchone()
            event = conn.execute('SELECT payload FROM events WHERE id=%s', (event_id,)).fetchone()[0]
            inbound = conn.execute('SELECT payload FROM inbound_updates WHERE update_id=%s', (update_id,)).fetchone()[0]
        self.assertTrue(family_name.startswith('rt1:'))
        self.assertEqual(self.store.data_cipher.open(family_name, 'families.name'), 'Legacy Family')
        for value, context, expected in zip(child, ('children.nickname', 'children.birth_date', 'children.sex', 'children.premature_notes'),
                                            ('Legacy Child', '2024-02-03', 'female', 'Legacy note')):
            self.assertEqual(self.store.data_cipher.open(value, context), expected)
        self.assertEqual(self.store.data_cipher.open_json(event, 'events.payload'), {'text': 'legacy event'})
        self.assertEqual(self.store.data_cipher.open_json(inbound, 'inbound_updates.payload'), {'message': {'text': 'legacy inbound'}})

    def test_chat_selection_requires_active_membership_and_clears_on_revoke(self):
        self.store.redeem(2, self.store.invite(self.family, 1))
        self.store.set_chat_selection(self.family, 2, self.child)
        self.assertEqual(self.store.chat_selection(2)[:2], (self.family, self.child))
        with self.assertRaises(Denied):
            self.store.set_chat_selection(self.family, 3, self.child)
        other, other_child = self.store.create_family(1, 'Keluarga lain', 'Anak lain')
        with self.assertRaises(Invalid):
            self.store.set_chat_selection(self.family, 2, other_child)
        self.store.revoke(self.family, 1, 2)
        self.assertIsNone(self.store.chat_selection(2))

    def test_sent_chat_body_is_scrubbed(self):
        self.store.record_update(919, 1, {'message': 'private reply'})
        with self.store.connect() as conn:
            conn.execute('INSERT INTO chat_outbox (update_id,recipient_id,body) VALUES (919,1,%s)',
                         (self.store.data_cipher.seal('private reply', 'chat_outbox.body'),))
        self.assertTrue(deliver_one(self.store, 'telegram', sender=lambda *_: 'sent'))
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT status,body FROM chat_outbox WHERE update_id=919').fetchone(), ('sent', ''))

    def test_child_profile_and_owner_transfer(self):
        self.store.redeem(2, self.store.invite(self.family, 1))
        with self.assertRaises(Denied):
            self.store.save_child(self.family, 2, 'Anak lain', None, None, None)
        child = self.store.save_child(self.family, 1, 'Adik', None, 'female', 'Catatan opsional')
        self.assertEqual(len(self.store.children(self.family, 2)), 2)
        with self.assertRaises(Invalid):
            self.store.set_role(self.family, 1, 1, 'member')
        self.store.set_role(self.family, 1, 2, 'owner')
        self.store.set_role(self.family, 1, 1, 'member')
        self.store.save_child(self.family, 2, 'Adik Baru', None, None, None, child)
        self.assertEqual(self.store.children(self.family, 1)[1][1], 'Adik Baru')
        with self.assertRaises(Invalid):
            self.store.revoke(self.family, 2, 2)

    def test_csv_authorization_range_and_soft_delete(self):
        self.store.redeem(2, self.store.invite(self.family, 1))
        child = self.store.save_child(self.family, 1, '=SUM(1,1)', None, None, None)
        at = datetime(2026, 1, 1, 17, 30, tzinfo=timezone.utc)
        event = self.store.create_events(self.family, 1, child, [{'kind': 'note', 'payload': {'text': '+cmd'}, 'occurred_at': at}])[0]
        client = TestClient(create_app(self.dsn, '', environment='development', dev_auth=True))
        def headers(user):
            token = client.post('/api/dev/session', json={'user_id': user}).json()['token']
            return {'Authorization': 'Bearer ' + token}
        url = f'/api/families/{self.family}/export.csv?start=2026-01-02&end=2026-01-02'
        self.assertEqual(client.get(url, headers=headers(2)).status_code, 403)
        owner = headers(1)
        result = client.get(url, headers=owner)
        self.assertEqual(result.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(result.text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['child_nickname'], "'=SUM(1,1)")
        self.assertEqual(rows[0]['occurred_at_utc'], '2026-01-01T17:30:00+00:00')
        self.assertEqual(client.get(f'/api/families/{self.family}/export.csv?start=2026-01-01&end=2026-01-01', headers=owner).text.count('note'), 0)
        delete_url = f'/api/families/{self.family}/events/{event}/delete'
        self.assertEqual(client.post(delete_url, headers=owner, json={'version': 1, 'confirmed': False}).status_code, 422)
        self.assertEqual(client.post(delete_url, headers=owner, json={'version': 1, 'confirmed': True}).status_code, 204)
        self.assertEqual(client.post(delete_url, headers=owner, json={'version': 1, 'confirmed': True}).status_code, 204)
        self.assertEqual(list(csv.DictReader(io.StringIO(client.get(url, headers=owner).text))), [])

    def test_family_deletion_is_scoped_confirmed_and_repeatable(self):
        self.store.redeem(2, self.store.invite(self.family, 1))
        other, other_child = self.store.create_family(2, 'Keluarga lain', 'Anak lain')
        now = datetime.now(timezone.utc)
        self.store.create_events(self.family, 1, self.child, [{'kind': 'note', 'payload': {'text': 'pribadi'}, 'occurred_at': now}], request_key='delete-family-test')
        self.store.create_events(other, 2, other_child, [{'kind': 'note', 'payload': {'text': 'lain'}, 'occurred_at': now}])
        self.store.record_update(991, 1, {'message': 'pribadi'})
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET family_id=%s,status='completed' WHERE update_id=991", (self.family,))
            conn.execute("INSERT INTO chat_outbox (update_id,recipient_id,family_id,body) VALUES (991,1,%s,'pribadi')", (self.family,))
        with self.assertRaises(Denied):
            self.store.request_family_deletion(self.family, 2)
        expired = self.store.request_family_deletion(self.family, 1)
        with self.store.connect() as conn:
            conn.execute("UPDATE family_deletion_requests SET expires_at=now()-interval '1 second' WHERE family_id=%s", (self.family,))
        with self.assertRaises(Invalid):
            self.store.delete_family(self.family, 1, expired, 'HAPUS KELUARGA')
        token = self.store.request_family_deletion(self.family, 1)
        with self.assertRaises(Invalid):
            self.store.delete_family(self.family, 1, token, 'SALAH')
        self.assertEqual(len(self.store.timeline(self.family, 2, self.child)), 1)
        self.store.delete_family(self.family, 1, token, 'HAPUS KELUARGA')
        self.store.delete_family(self.family, 1, token, 'HAPUS KELUARGA')
        with self.assertRaises(Denied):
            self.store.timeline(self.family, 2, self.child)
        self.assertEqual(len(self.store.timeline(other, 2, other_child)), 1)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM api_actions WHERE family_id=%s', (self.family,)).fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM family_deletion_receipts WHERE family_id=%s', (self.family,)).fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT payload,family_id FROM inbound_updates WHERE update_id=991').fetchone(), ({}, None))
            self.assertEqual(conn.execute('SELECT count(*) FROM chat_outbox WHERE update_id=991').fetchone()[0], 0)
        self.assertFalse(self.store.record_update(991, 1, {'message': 'pribadi'}))

    def test_expired_transient_content_is_scrubbed_without_replaying_update(self):
        self.store.record_update(909, 1, {'message': 'sintetis'})
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='completed',received_at=now()-interval '8 days' WHERE update_id=909")
        cleanup(self.store)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT payload FROM inbound_updates WHERE update_id=909').fetchone()[0], {})
        self.assertFalse(self.store.record_update(909, 1, {'message': 'sintetis'}))

    def test_configured_chat_retention_scrubs_expired_updates(self):
        self.store.record_update(910, 1, {'message': 'data sintetis'})
        self.store.record_update(911, 1, {'message': 'data sintetis'})
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET received_at=now()-interval '2 days' WHERE update_id=910")
            conn.execute("UPDATE inbound_updates SET status='processing',received_at=now()-interval '2 days',lease_until=now()-interval '3 minutes' WHERE update_id=911")
        cleanup(self.store, chat_content_retention_days=1)
        with self.store.connect() as conn:
            rows = conn.execute('SELECT status,payload FROM inbound_updates WHERE update_id IN (910,911) ORDER BY update_id').fetchall()
        self.assertEqual(rows, [('failed', {}), ('failed', {})])
        self.assertFalse(self.store.record_update(910, 1, {'message': 'data sintetis'}))

    def test_chat_content_retention_rejects_invalid_bounds(self):
        for days in (0, 31, True):
            with self.subTest(days=days), self.assertRaises(ValueError):
                cleanup(self.store, chat_content_retention_days=days)

    def test_family_deletion_http_confirmation(self):
        client = TestClient(create_app(self.dsn, '', environment='development', dev_auth=True))
        token = client.post('/api/dev/session', json={'user_id': 1}).json()['token']
        headers = {'Authorization': 'Bearer ' + token}
        endpoint = f'/api/families/{self.family}'
        challenge = client.post(endpoint + '/deletion-request', headers=headers).json()['token']
        self.assertEqual(client.post(endpoint + '/delete', headers=headers, json={'token': challenge, 'phrase': 'salah'}).status_code, 422)
        self.assertEqual(client.post(endpoint + '/delete', headers=headers, json={'token': challenge, 'phrase': 'HAPUS KELUARGA'}).status_code, 204)
        self.assertEqual(client.post(endpoint + '/delete', headers=headers, json={'token': challenge, 'phrase': 'HAPUS KELUARGA'}).status_code, 204)

    def test_concurrent_family_delete_is_repeatable(self):
        token = self.store.request_family_deletion(self.family, 1)
        barrier = threading.Barrier(2)
        results = []
        def delete():
            barrier.wait()
            try:
                self.store.delete_family(self.family, 1, token, 'HAPUS KELUARGA')
                results.append('ok')
            except Exception as exc:
                results.append(type(exc).__name__)
        threads = [threading.Thread(target=delete) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(results, ['ok', 'ok'])

    def test_invitation_race(self):
        token = self.store.invite(self.family, 1)
        results = []
        barrier = threading.Barrier(2)
        def redeem(user):
            barrier.wait()
            try:
                self.store.redeem(user, token)
                results.append('ok')
            except Invalid:
                results.append('invalid')
        threads = [threading.Thread(target=redeem, args=(user,)) for user in (2, 3)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(results, ['ok', 'invalid'])

    def test_chat_registration_invitation_and_per_user_ai_consent(self):
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='failed' WHERE status='pending'")
        user, guest = 7812301, 7812302
        class CaptureProvider(OpenAICompatibleProvider):
            def __init__(self):
                self.sent = []
            def propose(self, text, received_at, zone, *, known_names=(), known_birth_dates=()):
                self.sent.append(text)
                if text == 'catat untuk profil terpilih':
                    return {'kind': 'create_events', 'events': [
                        {'kind': 'note', 'payload': {'text': 'profil kedua'}, 'occurred_at': received_at}
                    ]}
                return {'kind': 'clarify'}
        provider = CaptureProvider()

        def chat(actor, text):
            update_id = time.time_ns() // 1000
            payload = {'update_id': update_id, 'message': {'date': int(time.time()), 'text': text,
                'chat': {'id': actor, 'type': 'private'}, 'from': {'id': actor, 'is_bot': False}}}
            self.store.record_update(update_id, actor, payload)
            self.assertTrue(process_one(self.store, provider))
            with self.store.connect() as conn:
                body, family = conn.execute('SELECT body,family_id FROM chat_outbox WHERE update_id=%s', (update_id,)).fetchone()
            return update_id, self.store.data_cipher.open(body, 'chat_outbox.body'), family

        update_id, response, _ = chat(user, '/daftar Keluarga Mawar | Lili')
        self.assertIn('berhasil dibuat', response)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT payload FROM inbound_updates WHERE update_id=%s', (update_id,)).fetchone()[0], {})
        family = self.store.families(user)[0][0]
        self.assertEqual(self.store.chat_selection(user)[:2], (family, self.store.children(family, user)[0][0]))
        second_child = self.store.save_child(family, user, 'Mawar', None, None, None)
        self.assertEqual(self.store.create_family(user, 'Keluarga Mawar', 'Lili', update_id=update_id), (family, self.store.children(family, user)[0][0]))
        self.assertEqual(len(self.store.families(user)), 1)
        _, family_listing, _ = chat(user, '/keluarga')
        self.assertIn(f'Mawar (ID {second_child})', family_listing)
        _, selection_response, _ = chat(user, f'/pilih {family} {second_child}')
        self.assertIn('Mawar', selection_response)
        self.assertEqual(self.store.chat_selection(user)[:2], (family, second_child))
        _, denied_selection, _ = chat(user, f'/pilih 9223372036854775807 {second_child}')
        self.assertIn('tidak memiliki akses', denied_selection)
        self.assertEqual(self.store.chat_selection(user)[:2], (family, second_child))
        invite_update, invite_response, _ = chat(user, f'/undang {family}')
        invite = re.search(r'/start ([A-Za-z0-9_-]{30,})', invite_response).group(1)
        _, join_response, joined_family = chat(guest, f'/start {invite}')
        self.assertIn('sudah bergabung', join_response)
        self.assertEqual(joined_family, family)
        self.assertEqual(len(self.store.families(guest)), 1)
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET received_at=now()-interval '3 days' WHERE update_id=%s", (invite_update,))
        cleanup(self.store)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT result FROM actions WHERE update_id=%s AND action_key='create_invitation'", (invite_update,)).fetchone()[0], {})
            self.assertEqual(conn.execute('SELECT body,status FROM chat_outbox WHERE update_id=%s', (invite_update,)).fetchone(), ('', 'failed'))

        _, blocked, _ = chat(user, 'Lili minum 120 ml')
        self.assertIn('AI eksternal nonaktif', blocked)
        self.assertEqual(provider.sent, [])
        chat(user, f'/ai aktif {family}')
        chat(user, '/ai setuju')
        self.assertTrue(self.store.ai_consent(family, user, ai_consent_scope()))
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='failed' WHERE status='pending'")
        chat(user, 'catat untuk profil terpilih')
        self.assertEqual(len(self.store.timeline(family, user, second_child)), 1)
        self.assertEqual(len(self.store.timeline(family, user, self.store.children(family, user)[0][0])), 0)
        chat(user, f'/pilih {family} {self.store.children(family, user)[0][0]}')
        chat(user, 'Lili minum 120 ml')
        self.assertEqual(provider.sent, ['catat untuk profil terpilih', 'Lili minum 120 ml'])
        chat(user, f'/ai nonaktif {family}')
        self.assertFalse(self.store.ai_consent(family, user, ai_consent_scope()))
        chat(user, 'Lili minum 120 ml')
        self.assertEqual(len(provider.sent), 2)

    def test_ai_consent_is_inactive_for_a_different_provider_scope(self):
        old_scope, new_scope = 'a' * 64, 'b' * 64
        self.store.set_ai_consent(self.family, 1, True, old_scope)
        self.assertTrue(self.store.ai_consent(self.family, 1, old_scope))
        self.assertFalse(self.store.ai_consent(self.family, 1, new_scope))

    def test_chat_invite_action_is_repeatable_without_minting_extra_codes(self):
        update_id = time.time_ns() // 1000
        self.store.record_update(update_id, 1, {'message': {'text': '/undang'}})
        first = self.store.invite(self.family, 1, update_id=update_id)
        second = self.store.invite(self.family, 1, update_id=update_id)
        self.assertEqual(first, second)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM invitations WHERE family_id=%s", (self.family,)).fetchone()[0], 1)

    def test_telegram_polling_persists_private_updates_before_advancing_offset(self):
        with self.store.connect() as conn:
            conn.execute('DELETE FROM telegram_poll_cursor')
            conn.execute("DELETE FROM inbound_updates WHERE update_id BETWEEN 910000 AND 910010")
        updates = [
            {'update_id': 910000, 'message': {'date': 1760000000, 'text': '/start', 'chat': {'id': 45, 'type': 'private'}, 'from': {'id': 45, 'is_bot': False, 'username': 'synthetic_username', 'first_name': 'Synthetic'}}},
            {'update_id': 910001, 'message': {'date': 1760000000, 'text': 'rahasia', 'chat': {'id': 46, 'type': 'group'}, 'from': {'id': 46, 'is_bot': False}}},
        ]
        calls = []
        def get_updates(token, offset, timeout):
            calls.append((offset, timeout))
            return updates
        polling_loop(self.store, 'synthetic-token', get_updates=get_updates, timeout=45, running=lambda: not calls)
        self.assertEqual(calls, [(0, 45)])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT next_offset FROM telegram_poll_cursor').fetchone()[0], 910002)
            user_id, payload = conn.execute('SELECT telegram_user_id,payload FROM inbound_updates WHERE update_id=910000').fetchone()
            self.assertIsInstance(payload, str)
            self.assertTrue(payload.startswith('rt1:'))
            payload = self.store.data_cipher.open_json(payload, 'inbound_updates.payload')
            self.assertEqual((user_id, payload['message']['text']), (45, '/start'))
            self.assertNotIn('username', payload['message']['from'])
            self.assertNotIn('first_name', payload['message']['from'])
            self.assertIsNone(conn.execute('SELECT 1 FROM inbound_updates WHERE update_id=910001').fetchone())

        restarted_calls = []
        polling_loop(self.store, 'synthetic-token',
                     get_updates=lambda token, offset, timeout: restarted_calls.append(offset) or [],
                     timeout=45, running=lambda: not restarted_calls)
        self.assertEqual(restarted_calls, [910002])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT next_offset FROM telegram_poll_cursor').fetchone()[0], 910002)
            self.assertEqual(conn.execute('SELECT count(*) FROM inbound_updates WHERE update_id=910000').fetchone()[0], 1)

    def test_atomic_validation_order_and_version(self):
        now = datetime.now(timezone.utc)
        valid = {'kind': 'diaper', 'payload': {'type': 'pup'}, 'occurred_at': now}
        with self.assertRaises(Invalid):
            self.store.create_events(self.family, 1, self.child, [valid, {'kind': 'unknown'}])
        self.assertEqual(self.store.timeline(self.family, 1, self.child), [])
        older = dict(valid, occurred_at=now - timedelta(days=1))
        ids = self.store.create_events(self.family, 1, self.child, [valid, older])
        self.assertEqual([row[0] for row in self.store.timeline(self.family, 1, self.child)], ids)
        self.assertEqual(self.store.update_event(self.family, 1, ids[0], 1, {'type': 'pipis'}, now), 2)
        with self.assertRaises(Conflict):
            self.store.update_event(self.family, 1, ids[0], 1, {'type': 'pup'}, now)

    def test_idempotency_and_payload_validation(self):
        now = datetime.now(timezone.utc)
        entries = [{'kind': 'feeding', 'payload': {'type': 'expressed', 'volume_ml': 120}, 'occurred_at': now},
                   {'kind': 'diaper', 'payload': {'type': 'pup'}, 'occurred_at': now}]
        self.assertTrue(self.store.record_update(42, 1, {'update_id': 42}))
        self.assertFalse(self.store.record_update(42, 1, {'update_id': 42}))
        ids = self.store.create_events(self.family, 1, self.child, entries, update_id=42, action_key='create')
        self.assertEqual(ids, self.store.create_events(self.family, 1, self.child, entries, update_id=42, action_key='create'))
        self.assertEqual(len(self.store.timeline(self.family, 1, self.child)), 2)
        with self.assertRaises(Conflict):
            self.store.create_events(self.family, 1, self.child, entries[:1], update_id=42, action_key='create')
        with self.assertRaises(Invalid):
            self.store.create_events(self.family, 1, self.child, [dict(entries[0], payload={'type': 'direct', 'volume_ml': 120})])
        with self.assertRaises(Invalid):
            self.store.update_event(self.family, 1, ids[1], 1, {'type': 'unknown'}, now)

    def test_concurrent_edits(self):
        now = datetime.now(timezone.utc)
        event = self.store.create_events(self.family, 1, self.child, [
            {'kind': 'note', 'payload': {'text': 'awal'}, 'occurred_at': now}
        ])[0]
        barrier = threading.Barrier(2)
        results = []
        def edit(text):
            barrier.wait()
            try:
                self.store.update_event(self.family, 1, event, 1, {'text': text}, now)
                results.append('ok')
            except Conflict:
                results.append('conflict')
        threads = [threading.Thread(target=edit, args=(text,)) for text in ('satu', 'dua')]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertCountEqual(results, ['ok', 'conflict'])

    def test_concurrent_retry_creates_one_batch(self):
        now = datetime.now(timezone.utc)
        entries = [{'kind': 'note', 'payload': {'text': 'uji'}, 'occurred_at': now}]
        self.store.record_update(101, 1, {'update_id': 101})
        barrier = threading.Barrier(2)
        results = []
        def create():
            barrier.wait()
            results.append(self.store.create_events(self.family, 1, self.child, entries, update_id=101, action_key='create'))
        threads = [threading.Thread(target=create) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.store.timeline(self.family, 1, self.child)), 1)

    def test_http_session_and_family_authorization(self):
        client = TestClient(create_app(self.dsn, 'test-token'))
        self.assertEqual(client.get('/ready').status_code, 200)
        with self.store.connect() as conn:
            conn.execute("UPDATE schema_migrations SET checksum='invalid' WHERE name='003_checkins.sql'")
        self.assertEqual(client.get('/ready').status_code, 503)
        checksum = hashlib.sha256(Path('migrations/003_checkins.sql').read_bytes()).hexdigest()
        with self.store.connect() as conn:
            conn.execute("UPDATE schema_migrations SET checksum=%s WHERE name='003_checkins.sql'", (checksum,))
        self.assertEqual(client.get('/ready').status_code, 200)
        self.assertEqual(client.get('/api/families').status_code, 401)
        session = client.post('/api/session', json={'init_data': signed_data(int(time.time()))})
        self.assertEqual(session.status_code, 200)
        headers = {'Authorization': 'Bearer ' + session.json()['token']}
        self.assertEqual(client.get(f'/api/families/{self.family}/children', headers=headers).status_code, 403)
        token = self.store.invite(self.family, 1)
        self.assertEqual(client.post('/api/invitations/redeem', headers=headers, json={'token': token}).status_code, 200)
        self.assertEqual(client.get(f'/api/families/{self.family}/children', headers=headers).status_code, 200)
        consent_url = f'/api/families/{self.family}/ai-consent'
        self.assertEqual(client.get(consent_url, headers=headers).json(), {'enabled': False})
        self.assertEqual(client.put(consent_url, headers=headers, json={'enabled': True}).json(), {'enabled': True})
        self.assertEqual(client.get(consent_url, headers=headers).json(), {'enabled': True})
        preference_url = f'/api/families/{self.family}/checkin-preferences'
        settings = {'time': '13:00', 'timezone': 'Asia/Jakarta', 'quiet_start': '22:00',
                    'quiet_end': '06:00', 'snoozed_until': None, 'max_daily': 1}
        self.assertFalse(client.get(preference_url, headers=headers).json()['enabled'])
        self.assertEqual(client.put(preference_url, headers=headers, json={'enabled': True, 'settings': settings}).status_code, 200)
        self.assertTrue(client.get(preference_url, headers=headers).json()['enabled'])
        headers['Idempotency-Key'] = 'test-request'
        body = [{'kind': 'note', 'payload': {'text': 'uji'}, 'occurred_at': datetime.now(timezone.utc).isoformat()}]
        url = f'/api/families/{self.family}/children/{self.child}/events'
        first = client.post(url, headers=headers, json=body)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(client.post(url, headers=headers, json=body).json(), first.json())
        self.assertEqual(len(client.get(url, headers=headers).json()), 1)
        self.store.revoke(self.family, 1, 123)
        with self.store.connect() as conn:
            self.assertFalse(conn.execute('SELECT enabled FROM ai_processing_consents WHERE family_id=%s AND telegram_user_id=123', (self.family,)).fetchone()[0])
        self.assertEqual(client.get(url, headers=headers).status_code, 403)
        self.assertEqual(client.get(preference_url, headers=headers).status_code, 403)
        self.assertEqual(client.post(url, headers=headers, json=body).status_code, 403)

    def test_local_times_summary_and_pagination(self):
        self.assertEqual(local_instant('2026-01-02T00:30', 'Asia/Jakarta'), datetime(2026, 1, 1, 17, 30, tzinfo=timezone.utc))
        with self.assertRaises(Invalid):
            local_instant('2026-11-01T01:30', 'America/New_York')
        now = datetime.now(timezone.utc)
        entries = [{'kind': 'feeding', 'payload': {'type': 'expressed', 'volume_ml': 120}, 'occurred_at': now},
                   {'kind': 'feeding', 'payload': {'type': 'direct', 'duration_minutes': 10}, 'occurred_at': now}]
        self.store.create_events(self.family, 1, self.child, entries)
        summary = self.store.today_summary(self.family, 1, self.child)
        self.assertEqual(summary['counts']['feeding'], 2)
        self.assertEqual(summary['volume_ml']['expressed'], 120)
        self.assertEqual(summary['volume_counts']['formula'], 0)
        first = self.store.timeline(self.family, 1, self.child, limit=1)
        second = self.store.timeline(self.family, 1, self.child, limit=1, offset=1)
        self.assertNotEqual(first[0][0], second[0][0])
        client = TestClient(create_app(self.dsn, '', environment='development', dev_auth=True))
        token = client.post('/api/dev/session', json={'user_id': 1}).json()['token']
        headers = {'Authorization': 'Bearer ' + token}
        local = now.astimezone(ZoneInfo('Asia/Jakarta')).replace(microsecond=0, tzinfo=None).isoformat()
        event = first[0]
        response = client.put(f'/api/families/{self.family}/events/{event[0]}/local', headers=headers,
                              json={'kind': event[1], 'payload': event[2], 'version': event[4],
                                    'occurred_local': local, 'occurred_original': event[3].isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.timeline(self.family, 1, self.child, limit=1)[0][3], now)

    def test_development_auth_requires_explicit_local_configuration(self):
        with self.assertRaises(ValueError):
            create_app(self.dsn, '', dev_auth=True)
        production = TestClient(create_app(self.dsn, ''))
        self.assertIn(production.post('/api/dev/session', json={'user_id': 999}).status_code, (404, 405))
        development = TestClient(create_app(self.dsn, '', environment='development', dev_auth=True))
        response = development.post('/api/dev/session', json={'user_id': 999})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.session_user(response.json()['token']), 999)

    def test_webhook_queue_and_ambiguous_draft(self):
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='completed' WHERE status='pending'")
        client = TestClient(create_app(self.dsn, '', webhook_secret='test-secret'))
        timestamp = int(datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc).timestamp())
        def update(update_id, text):
            return {'update_id': update_id, 'message': {'date': timestamp, 'from': {'id': 1},
                    'chat': {'id': 1, 'type': 'private'}, 'text': text}}
        # Existing tests create several families for user 1; use a distinct member.
        self.store.redeem(888, self.store.invite(self.family, 1))
        self.assertEqual(client.post('/telegram/webhook', json=update(600, 'x' * 4097), headers={'X-Telegram-Bot-Api-Secret-Token': 'test-secret'}).status_code, 400)
        first = update(601, 'jam 9 ASIP 120 ml, jam setengah 10 pup')
        first['message']['from']['id'] = first['message']['chat']['id'] = 888
        self.assertEqual(client.post('/telegram/webhook', json=first).status_code, 403)
        headers = {'X-Telegram-Bot-Api-Secret-Token': 'test-secret'}
        self.assertEqual(client.post('/telegram/webhook', json=first, headers=headers).status_code, 200)
        self.assertEqual(client.post('/telegram/webhook', json=first, headers=headers).status_code, 200)
        self.assertTrue(process_one(self.store))
        self.assertEqual(len(self.store.timeline(self.family, 888, self.child)), 2)
        ambiguous = update(602, 'jam 9 ASIP 120 ml, mungkin pup')
        ambiguous['message']['from']['id'] = ambiguous['message']['chat']['id'] = 888
        self.assertEqual(client.post('/telegram/webhook', json=ambiguous, headers=headers).status_code, 200)
        self.assertTrue(process_one(self.store))
        self.assertEqual(len(self.store.timeline(self.family, 888, self.child)), 2)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM chat_drafts WHERE update_id=602').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT text FROM chat_drafts WHERE update_id=602').fetchone()[0], '')
            self.assertEqual(conn.execute('SELECT payload FROM inbound_updates WHERE update_id IN (601,602) ORDER BY update_id').fetchall(), [({},), ({},)])
            self.assertEqual(conn.execute('SELECT count(*) FROM chat_outbox WHERE update_id IN (601,602)').fetchone()[0], 2)
        self.assertTrue(deliver_one(self.store, 'telegram', sender=lambda *_: 'uncertain'))
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM chat_outbox WHERE update_id=601').fetchone()[0], 'uncertain')
        later = update(603, 'jam 9 pup')
        later['message']['from']['id'] = later['message']['chat']['id'] = 888
        self.assertEqual(client.post('/telegram/webhook', json=later, headers=headers).status_code, 200)
        self.assertTrue(process_one(self.store))
        self.store.revoke(self.family, 1, 888)
        self.assertTrue(deliver_one(self.store, 'fake'))
        self.assertTrue(deliver_one(self.store, 'fake'))
        self.assertFalse(deliver_one(self.store, 'fake'))
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM chat_outbox WHERE update_id=601').fetchone()[0], 'uncertain')
            self.assertEqual(conn.execute('SELECT status FROM chat_outbox WHERE update_id=603').fetchone()[0], 'failed')

    def test_ai_proposal_confirmation_and_repeat(self):
        self.store.redeem(889, self.store.invite(self.family, 1))
        self.store.set_ai_consent(self.family, 889, True, ai_consent_scope())
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='completed' WHERE status='pending'")
        at = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        def message(update_id, text):
            return {'update_id': update_id, 'message': {'date': int(at.timestamp()), 'from': {'id': 889},
                    'chat': {'id': 889, 'type': 'private'}, 'text': text}}
        args = {'events': [{'kind': 'diaper', 'occurred_at': '2026-01-01T09:30:00+07:00', 'payload_json': '{"type":"pup"}'}]}
        provider = OpenAICompatibleProvider('synthetic', 'test-model', 'https://ai.example/v1',
            lambda _: compatible_tool_response('create_events', json.dumps(args), {'prompt_tokens':44,'completion_tokens':12}))
        self.store.record_update(1101, 889, message(1101, 'pup setengah 10'))
        self.assertTrue(process_one(self.store, provider))
        self.assertEqual(self.store.timeline(self.family, 889, self.child), [])
        with self.store.connect() as conn:
            body = conn.execute('SELECT body FROM chat_outbox WHERE update_id=1101').fetchone()[0]
            self.assertTrue(body.startswith('rt1:'))
            self.assertIn('belum disimpan', self.store.data_cipher.open(body, 'chat_outbox.body'))
        self.assertEqual(tuple(self.store.agent_usage(self.family, 1)[0]), ('test-model', 44, 12))
        with self.assertRaises(Denied):
            self.store.agent_usage(self.family, 889)
        self.store.record_update(1102, 889, message(1102, 'simpan 1101'))
        self.assertTrue(process_one(self.store, provider))
        self.assertEqual(len(self.store.timeline(self.family, 889, self.child)), 1)
        self.store.record_update(1103, 889, message(1103, 'simpan 1101'))
        self.assertTrue(process_one(self.store, provider))
        self.assertEqual(len(self.store.timeline(self.family, 889, self.child)), 1)
        self.store.revoke(self.family, 1, 889)
        with self.assertRaises(Denied):
            self.store.confirm_agent_draft(self.family, 889, 1101)

    def test_agent_cancel_and_confirm_are_serialized(self):
        self.store.redeem(887, self.store.invite(self.family, 1))
        self.store.set_ai_consent(self.family, 887, True, ai_consent_scope())
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='completed' WHERE status='pending'")
        at = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        update = {'update_id': 1201, 'message': {'date': int(at.timestamp()), 'text':'pup', 'from':{'id':887}, 'chat':{'id':887,'type':'private'}}}
        args = {'events': [{'kind':'diaper','occurred_at':'2026-01-01T09:30:00+07:00','payload_json':'{"type":"pup"}'}]}
        provider = OpenAICompatibleProvider('synthetic','test-model','https://ai.example/v1',
            lambda _: compatible_tool_response('create_events', json.dumps(args)))
        self.store.record_update(1201, 887, update)
        process_one(self.store, provider)
        barrier, results = threading.Barrier(2), []
        def confirm():
            barrier.wait()
            try:
                self.store.confirm_agent_draft(self.family, 887, 1201)
                results.append('confirmed')
            except Invalid:
                results.append('invalid')
        def cancel():
            barrier.wait()
            results.append('cancelled' if self.store.cancel_agent_draft(self.family, 887, 1201) else 'not_cancelled')
        threads = [threading.Thread(target=confirm), threading.Thread(target=cancel)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertIn(set(results), ({'confirmed', 'not_cancelled'}, {'invalid', 'cancelled'}))
        self.assertEqual(len(self.store.timeline(self.family, 887, self.child)), int('confirmed' in results))

    def test_agent_failure_does_not_report_or_create_success(self):
        self.store.redeem(886, self.store.invite(self.family, 1))
        self.store.set_ai_consent(self.family, 886, True, ai_consent_scope())
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='completed' WHERE status='pending'")
        now = datetime.now(timezone.utc)
        update = {'update_id': 1301, 'message': {'date': int(now.timestamp()), 'text':'catat minum', 'from':{'id':886}, 'chat':{'id':886,'type':'private'}}}
        provider = OpenAICompatibleProvider('synthetic', 'test-model', 'https://ai.example/v1',
            lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.store.record_update(1301, 886, update)
        self.assertTrue(process_one(self.store, provider))
        self.assertEqual(self.store.timeline(self.family, 886, self.child), [])
        with self.store.connect() as conn:
            response = conn.execute('SELECT body FROM chat_outbox WHERE update_id=1301').fetchone()[0]
        response = self.store.data_cipher.open(response, 'chat_outbox.body')
        self.assertIn('Tidak ada catatan baru yang disimpan', response)

    def test_checkin_consent_snooze_suppression_and_revocation(self):
        now = datetime(2026, 1, 1, 3, 15, tzinfo=timezone.utc)
        for user in (2, 3):
            self.store.redeem(user, self.store.invite(self.family, 1))
        self.assertFalse(get_preferences(self.store, self.family, 1)['enabled'])
        settings = {'time': '10:00', 'timezone': 'Asia/Jakarta', 'quiet_start': None,
                    'quiet_end': None, 'snoozed_until': None, 'max_daily': 1}
        snoozed = dict(settings, snoozed_until=(now + timedelta(minutes=10)).isoformat())
        set_preferences(self.store, self.family, 1, True, snoozed)
        set_preferences(self.store, self.family, 2, True, settings)
        set_preferences(self.store, self.family, 3, True, settings)
        schedule_today(self.store, now)
        schedule_today(self.store, now)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM scheduled_occurrences WHERE family_id=%s', (self.family,)).fetchone()[0], 3)
        self.assertTrue(deliver_checkin(self.store, 'fake', now=now))
        self.assertTrue(deliver_checkin(self.store, 'telegram', sender=lambda *_: 'uncertain', now=now))
        self.store.revoke(self.family, 1, 3)
        acknowledge(self.store, self.family, 2, now.astimezone(ZoneInfo('Asia/Jakarta')).date())
        schedule_today(self.store, now + timedelta(minutes=11))
        self.assertFalse(deliver_checkin(self.store, 'fake', now=now + timedelta(minutes=11)))
        with self.store.connect() as conn:
            rows = conn.execute('SELECT telegram_user_id,status FROM scheduled_occurrences WHERE family_id=%s ORDER BY telegram_user_id', (self.family,)).fetchall()
            self.assertEqual(rows, [(1, 'cancelled'), (2, 'uncertain'), (3, 'cancelled')])
        self.store.redeem(3, self.store.invite(self.family, 1))
        self.assertFalse(get_preferences(self.store, self.family, 3)['enabled'])

    def test_checkin_quiet_hours_and_expiration(self):
        now = datetime(2026, 1, 1, 3, 15, tzinfo=timezone.utc)
        settings = {'time': '10:00', 'timezone': 'Asia/Jakarta', 'quiet_start': '09:00',
                    'quiet_end': '11:00', 'snoozed_until': None, 'max_daily': 1}
        set_preferences(self.store, self.family, 1, True, settings)
        schedule_today(self.store, now)
        self.assertTrue(deliver_checkin(self.store, 'fake', now=now))
        self.assertFalse(deliver_checkin(self.store, 'fake', now=now))
        self.assertFalse(deliver_checkin(self.store, 'fake', now=now + timedelta(hours=1)))
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM scheduled_occurrences WHERE family_id=%s', (self.family,)).fetchone()[0], 'cancelled')

    def test_reminder_consent_quiet_override_cancel_and_uncertain(self):
        now = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        settings = {'time':'13:00', 'timezone':'Asia/Jakarta', 'quiet_start':'09:00',
                    'quiet_end':'11:00', 'snoozed_until':None, 'max_daily':3}
        self.store.redeem(2, self.store.invite(self.family, 1))
        due = now + timedelta(minutes=10)
        with self.assertRaises(Invalid):
            create_reminder(self.store, self.family, 1, 'Bawa catatan', due, True, 'reminder-1', now=now)
        set_preferences(self.store, self.family, 1, True, settings, 'reminder')
        reminder = create_reminder(self.store, self.family, 1, 'Bawa catatan', due, True, 'reminder-1', now=now)
        self.assertEqual(reminder, create_reminder(self.store, self.family, 1, 'Bawa catatan', due, True, 'reminder-1', now=due))
        with self.assertRaises(Invalid):
            cancel_reminder(self.store, self.family, 2, reminder)
        sent = []
        self.assertTrue(deliver_checkin(self.store, 'telegram', sender=lambda _, user, body: sent.append((user, body)) or 'uncertain', now=due))
        self.assertEqual(sent, [(1, 'Pengingat: Bawa catatan')])
        self.assertFalse(deliver_checkin(self.store, 'fake', now=due + timedelta(minutes=2)))
        self.assertEqual(list_reminders(self.store, self.family, 1)[0][-1], 'uncertain')
        another = create_reminder(self.store, self.family, 1, 'Jangan kirim', now + timedelta(minutes=20), False, 'reminder-2', now=now)
        cancel_reminder(self.store, self.family, 1, another)
        cancel_reminder(self.store, self.family, 1, another)
        self.assertFalse(deliver_checkin(self.store, 'fake', now=now + timedelta(minutes=21)))

    def test_daily_summary_reads_latest_data_and_respects_opt_in(self):
        now = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        settings = {'time':'10:00', 'timezone':'Asia/Jakarta', 'quiet_start':None, 'quiet_end':None,
                    'snoozed_until':None, 'max_daily':3, 'child_id':self.child}
        self.assertFalse(get_preferences(self.store, self.family, 1, 'daily_summary')['enabled'])
        set_preferences(self.store, self.family, 1, True, settings, 'daily_summary')
        schedule_today(self.store, now)
        self.store.create_events(self.family, 1, self.child, [{'kind':'feeding', 'payload':{'type':'expressed','volume_ml':120}, 'occurred_at':now - timedelta(minutes=1)}])
        sent = []
        self.assertTrue(deliver_checkin(self.store, 'telegram', sender=lambda _, user, body: sent.append(body) or 'sent', now=now))
        self.assertIn('minum 1', sent[0])
        self.assertIn('ASIP 120 ml', sent[0])
        self.assertIn('formula belum tercatat', sent[0])
        schedule_today(self.store, now + timedelta(minutes=1))
        self.assertFalse(deliver_checkin(self.store, 'fake', now=now + timedelta(minutes=1)))

    def test_cancelled_quota_job_does_not_reappear_each_poll(self):
        now = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
        settings = {'time':'10:00', 'timezone':'Asia/Jakarta', 'quiet_start':None, 'quiet_end':None,
                    'snoozed_until':None, 'max_daily':1, 'child_id':self.child}
        set_preferences(self.store, self.family, 1, True, settings, 'daily_summary')
        set_preferences(self.store, self.family, 1, True, {k:v for k,v in settings.items() if k != 'child_id'}, 'checkin')
        schedule_today(self.store, now)
        self.assertTrue(deliver_checkin(self.store, 'fake', now=now))
        self.assertTrue(deliver_checkin(self.store, 'fake', now=now))
        schedule_today(self.store, now)
        self.assertFalse(deliver_checkin(self.store, 'fake', now=now))

    def test_checkin_no_answer_does_not_create_event(self):
        now = datetime(2026, 1, 1, 3, 15, tzinfo=timezone.utc)
        self.store.redeem(777, self.store.invite(self.family, 1))
        settings = {'time': '10:00', 'timezone': 'Asia/Jakarta', 'quiet_start': None,
                    'quiet_end': None, 'snoozed_until': None, 'max_daily': 1}
        set_preferences(self.store, self.family, 777, True, settings)
        schedule_today(self.store, now)
        self.assertTrue(deliver_checkin(self.store, 'fake', now=now))
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='completed' WHERE status='pending'")
        update = {'update_id': 801, 'message': {'date': int(now.timestamp()), 'text': 'tidak ada',
                  'from': {'id': 777}, 'chat': {'id': 777, 'type': 'private'}}}
        self.store.record_update(801, 777, update)
        self.assertTrue(process_one(self.store))
        self.assertEqual(self.store.timeline(self.family, 777, self.child), [])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM checkin_answers WHERE family_id=%s', (self.family,)).fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
