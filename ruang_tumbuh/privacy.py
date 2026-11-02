"""Authenticated encryption for sensitive values stored in PostgreSQL."""

import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PREFIX = "rt1:"
NONCE_BYTES = 12


class DataIntegrityError(ValueError):
    pass


class DataCipher:
    def __init__(self, encoded_key):
        if not isinstance(encoded_key, str) or not encoded_key:
            raise ValueError("APP_DATA_ENCRYPTION_KEY is required")
        try:
            key = base64.b64decode(encoded_key, altchars=b"-_", validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("APP_DATA_ENCRYPTION_KEY must be URL-safe base64 for 32 random bytes") from exc
        if len(key) != 32:
            raise ValueError("APP_DATA_ENCRYPTION_KEY must decode to exactly 32 bytes")
        self._cipher = AESGCM(key)

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("APP_DATA_ENCRYPTION_KEY"))

    def seal(self, value, context):
        if not isinstance(value, str) or not isinstance(context, str) or not context:
            raise ValueError("Sensitive values and encryption context must be strings")
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, value.encode("utf-8"), context.encode("utf-8"))
        payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
        return PREFIX + payload

    def open(self, value, context):
        if not isinstance(value, str) or not value.startswith(PREFIX) or not isinstance(context, str) or not context:
            raise DataIntegrityError("Encrypted data is missing or has an unsupported format")
        try:
            payload = base64.b64decode(value[len(PREFIX):] + "=" * (-len(value[len(PREFIX):]) % 4),
                                       altchars=b"-_", validate=True)
            if len(payload) < NONCE_BYTES + 16:
                raise ValueError()
            return self._cipher.decrypt(payload[:NONCE_BYTES], payload[NONCE_BYTES:], context.encode("utf-8")).decode("utf-8")
        except (ValueError, UnicodeDecodeError, InvalidTag, base64.binascii.Error) as exc:
            raise DataIntegrityError("Encrypted data failed authentication") from exc

    def seal_json(self, value, context):
        return self.seal(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False), context)

    def open_json(self, value, context):
        return json.loads(self.open(value, context))


SENSITIVE_FIELDS = (
        ("families", "id", "name", "families.name", False),
        ("children", "id", "nickname", "children.nickname", False),
        ("children", "id", "birth_date", "children.birth_date", False),
        ("children", "id", "sex", "children.sex", False),
        ("children", "id", "premature_notes", "children.premature_notes", False),
        ("events", "id", "payload", "events.payload", True),
        ("actions", "update_id,action_key", "result", "actions.result", True),
        ("inbound_updates", "update_id", "payload", "inbound_updates.payload", True),
        ("chat_drafts", "update_id", "text", "chat_drafts.text", False),
        ("chat_outbox", "update_id", "body", "chat_outbox.body", False),
        ("notification_preferences", "family_id,telegram_user_id,kind", "settings", "notification_preferences.settings", True),
        ("agent_drafts", "update_id", "events", "agent_drafts.events", True),
        ("reminders", "id", "body", "reminders.body", False),
)


def _walk_sensitive_fields(conn):
    for table, key_columns, column, context, is_json in SENSITIVE_FIELDS:
        keys = key_columns.split(",")
        selected = ",".join(keys)
        for row in conn.execute(f"SELECT {selected},{column} FROM {table}").fetchall():
            yield table, keys, column, context, is_json, row[:-1], row[-1]


def encrypt_existing_sensitive_content(conn, cipher):
    from psycopg.types.json import Jsonb

    for table, keys, column, context, is_json, values, value in _walk_sensitive_fields(conn):
        if value is None or value == "" or value == {}:
            continue
        if isinstance(value, str) and value.startswith(PREFIX):
            continue
        encrypted = cipher.seal_json(value, context) if is_json else cipher.seal(str(value), context)
        conn.execute(f"UPDATE {table} SET {column}=%s WHERE " +
                     " AND ".join(f"{key}=%s" for key in keys),
                     (Jsonb(encrypted) if is_json else encrypted, *values))


def rotate_sensitive_content(conn, old_cipher, new_cipher):
    from psycopg.types.json import Jsonb

    for table, keys, column, context, is_json, values, value in _walk_sensitive_fields(conn):
        if value is None or value == "" or value == {}:
            continue
        plaintext = old_cipher.open_json(value, context) if is_json else old_cipher.open(value, context)
        encrypted = new_cipher.seal_json(plaintext, context) if is_json else new_cipher.seal(plaintext, context)
        conn.execute(f"UPDATE {table} SET {column}=%s WHERE " +
                     " AND ".join(f"{key}=%s" for key in keys),
                     (Jsonb(encrypted) if is_json else encrypted, *values))
