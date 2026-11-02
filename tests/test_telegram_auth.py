import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from ruang_tumbuh.telegram_auth import AuthenticationError, verify_init_data


def signed_data(timestamp=1000):
    fields = {'auth_date': str(timestamp), 'user': json.dumps({'id': 123, 'first_name': 'Test'})}
    check = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', b'test-token', hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class TelegramAuthTests(unittest.TestCase):
    def test_valid_tampered_expired_future_and_duplicate(self):
        data = signed_data()
        self.assertEqual(verify_init_data(data, 'test-token', now=1100), 123)
        for invalid, now in ((data.replace('123', '124'), 1100), (data, 1301), (data, 999), (data + '&auth_date=1000', 1100)):
            with self.subTest(invalid=invalid, now=now), self.assertRaises(AuthenticationError):
                verify_init_data(invalid, 'test-token', now=now)
        with self.assertRaises(AuthenticationError):
            verify_init_data(data, '', now=1100)


if __name__ == '__main__':
    unittest.main()
