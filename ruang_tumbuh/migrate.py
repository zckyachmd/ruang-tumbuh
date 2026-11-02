"""Apply immutable SQL migrations once, under a PostgreSQL advisory lock."""

import hashlib
import os
from pathlib import Path

import psycopg

from .privacy import DataCipher, encrypt_existing_sensitive_content


def migrate(dsn, directory=Path('/app/migrations')):
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute('SELECT pg_advisory_lock(%s)', (91357468,))
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, checksum text NOT NULL)')
            for path in sorted(directory.glob('*.sql')):
                sql = path.read_text(encoding='utf-8')
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                row = conn.execute('SELECT checksum FROM schema_migrations WHERE name=%s', (path.name,)).fetchone()
                if row:
                    if row[0] != checksum:
                        raise RuntimeError(f'Migration checksum mismatch: {path.name}')
                    continue
                with conn.transaction():
                    conn.execute(sql)
                    if path.name == '011_encrypt_sensitive_content.sql':
                        encrypt_existing_sensitive_content(conn, DataCipher.from_environment())
                    conn.execute('INSERT INTO schema_migrations (name,checksum) VALUES (%s,%s)', (path.name, checksum))
        finally:
            conn.execute('SELECT pg_advisory_unlock(%s)', (91357468,))


def schema_ready(conn, directory):
    files = sorted(directory.glob('*.sql'))
    if not files:
        return False
    installed = dict(conn.execute('SELECT name,checksum FROM schema_migrations').fetchall())
    return all(installed.get(path.name) == hashlib.sha256(path.read_bytes()).hexdigest() for path in files)


if __name__ == '__main__':
    migrate(os.environ['DATABASE_URL'])
