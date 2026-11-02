import unittest
from contextlib import contextmanager
from ruang_tumbuh.healthcheck import worker_age


class HeartbeatTests(unittest.TestCase):
    def test_probe_reads_only_single_worker_heartbeat(self):
        for row, expected in ((None, None), ((10,), 10.0), ((121,), 121.0)):
            queries = []

            class Connection:
                def execute(self, sql):
                    queries.append(sql)
                    return self

                def fetchone(self):
                    return row

            class Store:
                @contextmanager
                def connect(self):
                    yield Connection()

            self.assertEqual(worker_age(Store()), expected)
            self.assertEqual(len(queries), 1)
            self.assertIn('worker_heartbeats', queries[0])
            for history_table in ('inbound_updates', 'chat_outbox', 'ai_reservations'):
                self.assertNotIn(history_table, queries[0])
