"""Re-encrypt sensitive database fields with a replacement application key."""

import os

import psycopg

from .privacy import DataCipher, rotate_sensitive_content


def rotate(dsn, old_key, new_key):
    if old_key == new_key:
        raise ValueError("Old and new encryption keys must differ")
    with psycopg.connect(dsn) as conn:
        rotate_sensitive_content(conn, DataCipher(old_key), DataCipher(new_key))


if __name__ == "__main__":
    rotate(os.environ["DATABASE_URL"], os.environ["APP_DATA_ENCRYPTION_KEY_OLD"],
           os.environ["APP_DATA_ENCRYPTION_KEY_NEW"])
