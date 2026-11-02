"""Telegram Mini App initData authentication, with no development bypass."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class AuthenticationError(Exception):
    pass


def verify_init_data(raw, bot_token, *, now=None, max_age=300):
    if not isinstance(raw, str) or len(raw) > 8192 or not isinstance(bot_token, str) or not bot_token:
        raise AuthenticationError()
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=50, errors='strict')
        data = dict(pairs)
        if len(data) != len(pairs):
            raise AuthenticationError()
        received = data.pop('hash')
        check = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
        secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            raise AuthenticationError()
        auth_date = int(data['auth_date'])
        current = time.time() if now is None else now
        if auth_date > current or current - auth_date > max_age:
            raise AuthenticationError()
        user = json.loads(data['user'])
        if not isinstance(user, dict) or type(user.get('id')) is not int or not 0 < user['id'] < 2**52:
            raise AuthenticationError()
        return user['id']
    except (KeyError, ValueError, TypeError, UnicodeError):
        raise AuthenticationError() from None
