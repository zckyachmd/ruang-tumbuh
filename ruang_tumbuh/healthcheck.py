"""Worker heartbeat and content-free operational counters for the operator."""

import json
import os
import sys
from .store import Store


def snapshot(store):
    with store.connect() as conn:
        heartbeat = conn.execute("SELECT extract(epoch FROM now()-seen_at) FROM worker_heartbeats WHERE name='chat'").fetchone()
        queue = conn.execute("SELECT status,count(*) FROM inbound_updates GROUP BY status").fetchall()
        age = conn.execute("SELECT extract(epoch FROM now()-min(received_at)) FROM inbound_updates WHERE status IN ('pending','processing')").fetchone()[0]
        outbox = conn.execute('SELECT status,count(*) FROM chat_outbox GROUP BY status').fetchall()
        requests = conn.execute("SELECT count(*) FROM ai_reservations WHERE reserved_at>now()-interval '1 day'").fetchone()[0]
    return {'worker_age_seconds':float(heartbeat[0]) if heartbeat else None, 'queue':dict(queue),
            'oldest_pending_seconds':float(age) if age is not None else None, 'outbox':dict(outbox), 'ai_requests_last_day':requests}


if __name__ == '__main__':
    try:
        result = snapshot(Store(os.environ['DATABASE_URL']))
        if '--metrics' in sys.argv:
            print(json.dumps(result))
        raise SystemExit(0 if result['worker_age_seconds'] is not None and result['worker_age_seconds'] < 120 else 1)
    except Exception:
        # Do not include connection strings or family content in health output.
        raise SystemExit(1)
