"""Actual PostgreSQL regression tests; no database/driver mocks."""

import os
import secrets
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

os.environ.setdefault('APP_ENV','development')
os.environ.setdefault('APP_DATA_ENCRYPTION_KEY','AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')

from ruang_tumbuh.store import Store, Invalid
from ruang_tumbuh.migrate import migrate
from ruang_tumbuh.chat_worker import process_one
from ruang_tumbuh.delivery import deliver_one, RetryAfter
from ruang_tumbuh.checkins import set_preferences, schedule_today, deliver_checkin
from ruang_tumbuh.admission import reserve_ai, BudgetExceeded
from ruang_tumbuh.mutations import confirm_change
from ruang_tumbuh.mutations import propose_change
from ruang_tumbuh.queries import query_records


class HardeningDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = os.environ['TEST_DATABASE_URL']
        cls.schema = 'hardening_'+secrets.token_hex(6)
        with psycopg.connect(cls.base,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
        cls.dsn = make_conninfo(cls.base,options='-csearch_path='+cls.schema)
        migrate(cls.dsn,Path('migrations'))

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(cls.base,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))

    def setUp(self):
        self.store = Store(self.dsn)
        self.user = secrets.randbits(40)+1
        self.family,self.child = self.store.create_family(self.user,'Synthetic','Alya')
        self.store.set_chat_selection(self.family,self.user,self.child)
        with self.store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='failed' WHERE status IN ('pending','processing')")
            conn.execute("UPDATE chat_outbox SET status='failed' WHERE status='pending'")
            conn.execute('UPDATE notification_preferences SET enabled=false')

    def enqueue(self,text):
        update = time.time_ns()//1000
        self.store.record_update(update,self.user,{'message':{'text':text,'date':int(time.time())}})
        return update

    def response(self,update):
        with self.store.connect() as conn:
            row = conn.execute('SELECT body FROM chat_outbox WHERE update_id=%s',(update,)).fetchone()
        return self.store.data_cipher.open(row[0],'chat_outbox.body')

    def test_clarify_confirm_repeat_and_child_binding(self):
        self.enqueue('ASIP 60 ml'); self.assertTrue(process_one(self.store))
        instant = datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Jakarta'))-timedelta(minutes=2)
        proposal = self.enqueue('hari ini jam '+instant.strftime('%H.%M')); process_one(self.store)
        self.assertIn('belum disimpan',self.response(proposal))
        self.assertEqual(self.store.timeline(self.family,self.user,self.child),[])
        other = self.store.save_child(self.family,self.user,'Bima',None,None,None)
        self.store.set_chat_selection(self.family,self.user,other)
        self.enqueue(f'simpan {proposal}');process_one(self.store)
        self.assertEqual(self.store.timeline(self.family,self.user,self.child),[])
        self.store.set_chat_selection(self.family,self.user,self.child)
        self.enqueue(f'simpan {proposal}');process_one(self.store)
        self.enqueue(f'simpan {proposal}');process_one(self.store)
        self.assertEqual(len(self.store.timeline(self.family,self.user,self.child)),1)

    def test_provider_outcomes_and_delivery_metrics_use_actual_database(self):
        from ruang_tumbuh.agent import ProviderError, ai_consent_scope
        from ruang_tumbuh.healthcheck import snapshot
        self.store.set_ai_consent(self.family, self.user, True, ai_consent_scope())

        class Provider:
            requires_consent = True
            fail = False

            def propose(self, *args, **kwargs):
                if self.fail:
                    raise ProviderError('synthetic failure')
                return {'kind': 'clarify'}

        provider = Provider()
        for fail, expected in ((False, 'succeeded'), (True, 'provider_error')):
            provider.fail = fail
            update = self.enqueue('ASIP 60 ml')
            process_one(self.store, provider)
            with self.store.connect() as conn:
                row = conn.execute('SELECT outcome,latency_ms,finished_at FROM ai_reservations WHERE update_id=%s', (update,)).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], expected)
                self.assertGreaterEqual(row[1], 0)
                self.assertIsNotNone(row[2])
                conn.execute("UPDATE chat_outbox o SET status='sent',finished_at=u.received_at+interval '12 seconds' FROM inbound_updates u WHERE o.update_id=u.update_id AND o.update_id=%s", (update,))
        metrics = snapshot(self.store)
        self.assertGreaterEqual(metrics['provider_outcomes_last_day']['succeeded'], 1)
        self.assertGreaterEqual(metrics['provider_outcomes_last_day']['provider_error'], 1)
        self.assertGreaterEqual(metrics['provider_latency_p95_ms'], 0)
        self.assertIsNotNone(metrics['telegram_delivery_lag_p95_seconds'])
        self.assertNotIn('Synthetic', str(metrics))

    def test_corrupt_inbound_does_not_block_next_job(self):
        bad = self.enqueue('bad')
        with self.store.connect() as conn:
            conn.execute('UPDATE inbound_updates SET payload=%s WHERE update_id=%s',(__import__('psycopg.types.json',fromlist=['Jsonb']).Jsonb('corrupt'),bad))
        good = self.enqueue('/help')
        self.assertTrue(process_one(self.store));self.assertTrue(process_one(self.store))
        self.assertIn('Halo',self.response(good))
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM inbound_updates WHERE update_id=%s',(bad,)).fetchone()[0],'failed')

    def test_rate_rejection_retains_body_and_retries_once_due(self):
        update = self.enqueue('/help');process_one(self.store)
        self.assertTrue(deliver_one(self.store,'telegram',sender=lambda *_:RetryAfter(7)))
        with self.store.connect() as conn:
            row = conn.execute('SELECT status,body FROM chat_outbox WHERE update_id=%s',(update,)).fetchone()
            self.assertEqual(row[0],'pending');self.assertTrue(row[1])
        self.assertFalse(deliver_one(self.store,'fake'))
        with self.store.connect() as conn:
            conn.execute('UPDATE chat_outbox SET next_attempt_at=now() WHERE update_id=%s',(update,))
        self.assertTrue(deliver_one(self.store,'fake'))
        self.assertFalse(deliver_one(self.store,'fake'))

    def test_both_notification_kinds_work_with_default_quota(self):
        now = datetime(2026,11,2,13,tzinfo=timezone.utc)
        settings = {'time':'20:00','timezone':'Asia/Jakarta','quiet_start':None,'quiet_end':None,'snoozed_until':None,'max_daily':1}
        set_preferences(self.store,self.family,self.user,True,settings)
        set_preferences(self.store,self.family,self.user,True,dict(settings,child_id=self.child),'daily_summary')
        schedule_today(self.store,now)
        sent=[]
        for _ in range(2):
            self.assertTrue(deliver_checkin(self.store,'telegram',sender=lambda _,user,body:sent.append(body) or 'sent',now=now))
        self.assertEqual(len(sent),2)
        self.assertTrue(any('Ringkasan' in body for body in sent))
        self.assertFalse(deliver_checkin(self.store,'fake',now=now))

    def test_atomic_ai_budget_reservation(self):
        with self.store.connect() as conn:conn.execute('DELETE FROM ai_reservations')
        update = self.enqueue('synthetic')
        barrier=threading.Barrier(2);results=[]
        def reserve():
            barrier.wait()
            try:
                with self.store.connect() as conn:reserve_ai(conn,self.family,self.user,update)
                results.append('reserved')
            except BudgetExceeded:results.append('denied')
        with patch.dict(os.environ,{'AI_GLOBAL_DAILY_REQUESTS':'1'}):
            threads=[threading.Thread(target=reserve) for _ in range(2)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(timeout=10)
        self.assertCountEqual(results,['reserved','denied'])

    def test_production_admission_is_separate_from_data_consent(self):
        from ruang_tumbuh.store import Denied
        update=self.enqueue('synthetic admitted request')
        with patch.dict(os.environ,{'APP_ENV':'production','FAMILY_CREATOR_IDS':'','AI_FAMILY_IDS':''}):
            with self.assertRaises(Denied):self.store.create_family(self.user,'Unauthorized','Synthetic')
            with self.assertRaises(BudgetExceeded):
                with self.store.connect() as conn:reserve_ai(conn,self.family,self.user,update)
            with patch.dict(os.environ,{'AI_FAMILY_IDS':str(self.family)}):
                with self.store.connect() as conn:reserve_ai(conn,self.family,self.user,update)

    def test_user_lock_preserves_command_before_record(self):
        other = self.store.save_child(self.family,self.user,'Bima',None,None,None)
        first = self.enqueue(f'/pilih {self.family} {other}')
        second = self.enqueue('jam 0 ASIP 60 ml')
        with self.store.connect() as lock:
            lock.autocommit=True
            lock.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',('chat:'+str(self.user),))
            self.assertTrue(process_one(self.store))
            with self.store.connect() as conn:
                self.assertEqual(conn.execute('SELECT status FROM inbound_updates WHERE update_id=%s',(second,)).fetchone()[0],'pending')
            lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',('chat:'+str(self.user),))
        threads=[threading.Thread(target=process_one,args=(self.store,)) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=10)
        # A worker may see the second row before/after the first commits. Drain if still pending.
        process_one(self.store)
        self.assertEqual(len(self.store.timeline(self.family,self.user,self.child)),0)
        self.assertEqual(len(self.store.timeline(self.family,self.user,other)),1)

    def test_period_summary_and_versioned_mutation(self):
        at=datetime(2026,11,1,3,tzinfo=timezone.utc)
        event=self.store.create_events(self.family,self.user,self.child,[{'kind':'feeding','payload':{'type':'expressed','volume_ml':60},'occurred_at':at}])[0]
        body,records=query_records(self.store,self.family,self.user,self.child,'summary','2026-11-01','2026-11-01')
        self.assertIn('ASIP: 60',body)
        update=self.enqueue('synthetic proposal')
        change={'operation':'edit','event_id':event,'version':1,'kind':'feeding','payload':{'type':'expressed','volume_ml':80},'occurred_at':at.isoformat()}
        with self.store.connect() as conn:
            conn.execute('INSERT INTO chat_mutations(update_id,family_id,child_id,telegram_user_id,content) VALUES (%s,%s,%s,%s,%s)',(update,self.family,self.child,self.user,self.store.data_cipher.seal_json(change,'chat_mutations.content')))
        confirm_change(self.store,self.family,self.user,self.child,update)
        confirm_change(self.store,self.family,self.user,self.child,update)
        current=self.store.timeline(self.family,self.user,self.child)[0]
        self.assertEqual(current[2]['volume_ml'],80);self.assertEqual(current[4],2)

    def test_last_poop_uses_index_with_fifty_thousand_newer_pee_records(self):
        at=datetime(2026,10,1,tzinfo=timezone.utc)
        poop=self.store.create_events(self.family,self.user,self.child,[{'kind':'diaper','payload':{'type':'pup'},'occurred_at':at}])[0]
        cipher=self.store.data_cipher
        token=cipher.lookup_token(self.family,'diaper',{'type':'pipis'})
        sealed=Jsonb(cipher.seal_json({'type':'pipis'},'events.payload'))
        with self.store.connect() as conn:
            conn.execute("""INSERT INTO events(family_id,child_id,kind,payload,occurred_at,created_by,lookup_token)
                SELECT %s,%s,'diaper',%s,%s+g*interval '1 second',%s,%s FROM generate_series(1,50000) g""",
                (self.family,self.child,sealed,at,self.user,token))
            conn.execute('ANALYZE events')
            plan=conn.execute("""EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT kind,payload,occurred_at FROM events
                WHERE family_id=%s AND child_id=%s AND kind='diaper' AND deleted_at IS NULL AND occurred_at<=now()
                AND lookup_token=%s ORDER BY occurred_at DESC,id DESC LIMIT 1""",
                (self.family,self.child,cipher.lookup_token(self.family,'diaper',{'type':'pup'}))).fetchone()[0]
        import json
        self.assertIn('events_lookup',json.dumps(plan))
        found=self.store.last_event(self.family,self.user,self.child,'poop',datetime.now(timezone.utc))
        self.assertEqual(found[1],{'type':'pup'})
        self.store.update_event(self.family,self.user,poop,1,{'type':'pipis'},at)
        self.assertIsNone(self.store.last_event(self.family,self.user,self.child,'poop',datetime.now(timezone.utc)))

    def test_preference_proposal_requires_confirmation_and_checks_staleness(self):
        from ruang_tumbuh.checkins import get_preferences
        from ruang_tumbuh.store import Conflict
        proposal={'operation':'preferences','notification_kind':'checkin','enabled':True,'time':'13:00',
                  'quiet_start':None,'quiet_end':None,'max_daily':1,'clear_quiet_hours':False}
        change=propose_change(self.store,self.family,self.user,self.child,proposal,None)
        self.assertFalse(get_preferences(self.store,self.family,self.user)['enabled'])
        draft=self.enqueue('synthetic preference proposal')
        with self.store.connect() as conn:
            conn.execute('INSERT INTO chat_mutations(update_id,family_id,child_id,telegram_user_id,content) VALUES (%s,%s,%s,%s,%s)',
                         (draft,self.family,self.child,self.user,self.store.data_cipher.seal_json(change,'chat_mutations.content')))
        confirm_change(self.store,self.family,self.user,self.child,draft)
        self.assertTrue(get_preferences(self.store,self.family,self.user)['enabled'])
        stale=self.enqueue('synthetic stale proposal')
        with self.store.connect() as conn:
            conn.execute('INSERT INTO chat_mutations(update_id,family_id,child_id,telegram_user_id,content) VALUES (%s,%s,%s,%s,%s)',
                         (stale,self.family,self.child,self.user,self.store.data_cipher.seal_json(change,'chat_mutations.content')))
        with self.assertRaises(Conflict):confirm_change(self.store,self.family,self.user,self.child,stale)

    def test_private_profile_buttons_are_encrypted_and_recheck_revocation(self):
        menu=self.enqueue('/keluarga');process_one(self.store)
        with self.store.connect() as conn:
            markup,families=conn.execute('SELECT reply_markup,authorization_families FROM chat_outbox WHERE update_id=%s',(menu,)).fetchone()
        self.assertTrue(markup.startswith('rt1:'))
        self.assertIn(self.family,families)
        decoded=self.store.data_cipher.open_json(markup,'chat_outbox.reply_markup')
        self.assertEqual(decoded['inline_keyboard'][0][0]['callback_data'],f'choose:{self.family}:{self.child}')
        guest=secrets.randbits(40)+1
        self.store.redeem(guest,self.store.invite(self.family,self.user))
        self.store.set_role(self.family,self.user,guest,'owner')
        self.store.revoke(self.family,guest,self.user)
        def never_send(*args):raise AssertionError('Revoked profile data must not be delivered')
        self.assertTrue(deliver_one(self.store,'telegram',sender=never_send))
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM chat_outbox WHERE update_id=%s',(menu,)).fetchone()[0],'failed')

    def test_edit_button_cancels_old_proposal_without_writing_facts(self):
        now=datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Jakarta'))-timedelta(minutes=2)
        proposal=self.enqueue('ASIP 60 ml hari ini jam '+now.strftime('%H.%M'));process_one(self.store)
        edit=self.enqueue(f'ubah {proposal}');process_one(self.store)
        self.assertIn('Bagian mana',self.response(edit))
        self.assertEqual(self.store.timeline(self.family,self.user,self.child),[])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM agent_drafts WHERE update_id=%s',(proposal,)).fetchone()[0],'cancelled')
            context=conn.execute('SELECT content FROM conversation_contexts WHERE family_id=%s AND telegram_user_id=%s',(self.family,self.user)).fetchone()[0]
            self.assertEqual(self.store.data_cipher.open_json(context,'conversation_contexts.content')['kind'],'clarification')

    def test_photo_does_not_poison_polling_cursor_or_create_an_event(self):
        from ruang_tumbuh.telegram_polling import persist_updates
        update=time.time_ns()//1000
        photo={'update_id':update,'message':{'date':int(time.time()),'from':{'id':self.user},'chat':{'id':self.user,'type':'private'},'photo':[{'file_id':'synthetic-private-file'}]}}
        with self.store.connect() as conn:
            conn.execute('DELETE FROM telegram_poll_cursor')
            self.assertEqual(persist_updates(conn,[photo],self.store.data_cipher),update+1)
        self.assertTrue(process_one(self.store))
        self.assertIn('kirim dalam teks',self.response(update))
        self.assertEqual(self.store.timeline(self.family,self.user,self.child),[])
