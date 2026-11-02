"""Worker heartbeat and content-free operational counters for the operator."""

import json
import os
import sys


def worker_age(store):
    """Keep the frequent container probe independent of growing history tables."""
    with store.connect() as conn:
        row = conn.execute("SELECT extract(epoch FROM now()-seen_at) FROM worker_heartbeats WHERE name='chat'").fetchone()
    return float(row[0]) if row else None


def snapshot(store):
    with store.connect() as conn:
        heartbeat = conn.execute("SELECT extract(epoch FROM now()-seen_at) FROM worker_heartbeats WHERE name='chat'").fetchone()
        queue = conn.execute("SELECT status,count(*) FROM inbound_updates GROUP BY status").fetchall()
        age = conn.execute("SELECT extract(epoch FROM now()-min(received_at)) FROM inbound_updates WHERE status IN ('pending','processing')").fetchone()[0]
        outbox = conn.execute('SELECT status,count(*) FROM chat_outbox GROUP BY status').fetchall()
        requests = conn.execute("SELECT count(*) FROM ai_reservations WHERE reserved_at>now()-interval '1 day'").fetchone()[0]
        provider = conn.execute("SELECT outcome,count(*) FROM ai_reservations WHERE reserved_at>now()-interval '1 day' GROUP BY outcome").fetchall()
        latency = conn.execute("SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM ai_reservations WHERE finished_at>now()-interval '1 day'").fetchone()[0]
        unobserved = conn.execute("SELECT count(*) FROM ai_reservations WHERE outcome='reserved' AND reserved_at<now()-interval '2 minutes'").fetchone()[0]
        lag = conn.execute("""SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM o.finished_at-u.received_at))
            FROM chat_outbox o JOIN inbound_updates u USING(update_id)
            WHERE o.status='sent' AND o.finished_at>now()-interval '1 day'""").fetchone()[0]
        delivery_age = conn.execute("""SELECT extract(epoch FROM now()-min(u.received_at))
            FROM chat_outbox o JOIN inbound_updates u USING(update_id) WHERE o.status IN ('pending','attempted')""").fetchone()[0]
        tokens = conn.execute("SELECT coalesce(sum(input_tokens),0),coalesce(sum(output_tokens),0) FROM agent_usage WHERE created_at>now()-interval '1 day'").fetchone()
    return {'worker_age_seconds':float(heartbeat[0]) if heartbeat else None, 'queue':dict(queue),
            'oldest_pending_seconds':float(age) if age is not None else None, 'outbox':dict(outbox), 'ai_requests_last_day':requests,
            'provider_outcomes_last_day':dict(provider), 'provider_latency_p95_ms':float(latency) if latency is not None else None,
            'provider_unobserved_reservations':unobserved, 'telegram_delivery_lag_p95_seconds':float(lag) if lag is not None else None,
            'oldest_undelivered_seconds':float(delivery_age) if delivery_age is not None else None,
            'ai_input_tokens_last_day':int(tokens[0]), 'ai_output_tokens_last_day':int(tokens[1])}


if __name__ == '__main__':
    try:
        from .store import Store
        store = Store(os.environ['DATABASE_URL'])
        if '--metrics' in sys.argv:
            result = snapshot(store)
            print(json.dumps(result))
            age = result['worker_age_seconds']
        else:
            age = worker_age(store)
        raise SystemExit(0 if age is not None and age < 120 else 1)
    except Exception:
        # Do not include connection strings or family content in health output.
        raise SystemExit(1)
