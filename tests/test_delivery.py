import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from ruang_tumbuh.delivery import telegram_send, RetryAfter


class TelegramDeliveryTests(unittest.TestCase):
    def test_explicit_429_is_retryable(self):
        error = HTTPError('https://synthetic.invalid', 429, 'limited', {}, io.BytesIO(b'{"parameters":{"retry_after":7}}'))
        with patch('urllib.request.urlopen', side_effect=error):
            self.assertEqual(telegram_send('synthetic', 1, 'hi'), RetryAfter(7))

    def test_timeout_is_uncertain_and_not_blindly_retried(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError()):
            self.assertEqual(telegram_send('synthetic', 1, 'hi'), 'uncertain')

    def test_permanent_rejection_and_unicode_limit(self):
        with patch('urllib.request.urlopen', side_effect=HTTPError('https://synthetic.invalid',403,'blocked',{},None)):
            self.assertEqual(telegram_send('synthetic',1,'hi'), 'failed')
        with patch('urllib.request.urlopen') as send:
            self.assertEqual(telegram_send('synthetic',1,'🤍'*2049), 'failed')
            send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
