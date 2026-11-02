import unittest
from contextlib import contextmanager
from ruang_tumbuh.admission import observe_provider
from ruang_tumbuh.agent import ProviderError


class ObservationFailureTests(unittest.TestCase):
    def test_metrics_failure_does_not_replay_or_discard_provider_result(self):
        class Store:
            @contextmanager
            def connect(self):
                raise RuntimeError('synthetic-sensitive-connection-string')
                yield

        calls = []

        def call():
            calls.append(1)
            return {'kind': 'clarify'}

        with self.assertLogs(level='ERROR') as logs:
            self.assertEqual(observe_provider(Store(), 1, call), {'kind': 'clarify'})
        self.assertEqual(len(calls), 1)
        self.assertNotIn('synthetic-sensitive', str(logs.output))

        with self.assertLogs(level='ERROR'), self.assertRaises(ProviderError):
            observe_provider(Store(), 1, lambda: (_ for _ in ()).throw(ProviderError('synthetic failure')))
