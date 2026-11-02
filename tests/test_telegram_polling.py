import io
import json
import os
import unittest
from unittest.mock import patch

from ruang_tumbuh.telegram_polling import polling_loop, telegram_get_updates
from ruang_tumbuh.privacy import DataCipher

os.environ.setdefault('APP_DATA_ENCRYPTION_KEY', 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')


class Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    autocommit = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, _params=()):
        if 'pg_try_advisory_lock' in query:
            return Cursor((True,))
        if 'SELECT next_offset' in query:
            return Cursor((0,))
        return Cursor((True,))


class Store:
    data_cipher = DataCipher(os.environ['APP_DATA_ENCRYPTION_KEY'])

    def connect(self):
        return Connection()


class TelegramPollingTests(unittest.TestCase):
    def test_get_updates_uses_configured_long_poll_and_network_timeout(self):
        response = io.BytesIO(b'{"ok":true,"result":[]}')
        with patch('ruang_tumbuh.telegram_polling.urllib.request.urlopen', return_value=response) as urlopen:
            self.assertEqual(telegram_get_updates('synthetic', 123, timeout=45), [])
        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data), {'offset': 123, 'timeout': 45, 'allowed_updates': ['message']})
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 55)

    def test_api_configuration_errors_give_safe_actionable_messages(self):
        for code, expected in ((401, 'verify TELEGRAM_BOT_TOKEN'), (409, 'remove the active webhook')):
            response = io.BytesIO(json.dumps({'ok': False, 'error_code': code, 'description': 'contains synthetic token'}).encode())
            with self.subTest(code=code), patch('ruang_tumbuh.telegram_polling.urllib.request.urlopen', return_value=response):
                with self.assertRaisesRegex(RuntimeError, expected) as caught:
                    telegram_get_updates('synthetic', 0)
                self.assertNotIn('synthetic', str(caught.exception))

    def test_polling_loop_rejects_timeout_outside_app_bounds(self):
        for timeout in (0, 51, True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                polling_loop(None, 'synthetic', timeout=timeout)

    def test_polling_loop_passes_configured_timeout_to_get_updates(self):
        calls = []
        running = iter((True, False))
        with patch('ruang_tumbuh.telegram_polling.persist_updates'):
            polling_loop(Store(), 'synthetic', get_updates=lambda token, offset, timeout: calls.append((token, offset, timeout)) or [],
                         timeout=45, running=lambda: next(running))
        self.assertEqual(calls, [('synthetic', 0, 45)])
