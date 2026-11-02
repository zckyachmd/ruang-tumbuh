"""Bounded record queries: models select a period; backend computes all numbers."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .store import Invalid
from .agent import render_event


def query_records(store, family, user, child, mode, start_date, end_date):
    start_date, end_date = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if not 0 <= (end_date-start_date).days <= 30 or mode not in ('summary', 'timeline', 'growth'):
        raise Invalid()
    with store.connect() as conn:
        store._access(conn, family, user)
        zone = ZoneInfo(conn.execute('SELECT timezone FROM families WHERE id=%s', (family,)).fetchone()[0])
        if not conn.execute('SELECT 1 FROM children WHERE family_id=%s AND id=%s', (family, child)).fetchone():
            raise Invalid()
        start = datetime.combine(start_date, time.min, zone).astimezone(timezone.utc)
        end = datetime.combine(end_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        counts = {'feeding': 0, 'diaper': 0, 'sleep': 0, 'growth': 0, 'note': 0}
        volumes = {'expressed': 0, 'formula': 0}
        volume_counts = {'expressed': 0, 'formula': 0}
        records = []
        with conn.cursor(name='record_period') as cursor:
            cursor.itersize = 100
            cursor.execute("""SELECT id,kind,payload,occurred_at,version FROM events
                WHERE family_id=%s AND child_id=%s AND deleted_at IS NULL AND occurred_at >= %s AND occurred_at < %s
                AND (%s=false OR kind='growth') ORDER BY occurred_at DESC,id DESC""", (family, child, start, end, mode == 'growth'))
            for event_id, kind, sealed, occurred, version in cursor:
                payload = store.data_cipher.open_json(sealed, 'events.payload')
                counts[kind] += 1
                if kind == 'feeding' and payload.get('type') in volumes and 'volume_ml' in payload:
                    volumes[payload['type']] += payload['volume_ml']
                    volume_counts[payload['type']] += 1
                if len(records) < 10:
                    records.append({'id': event_id, 'kind': kind, 'payload': payload, 'occurred_at': occurred.isoformat(), 'version': version})
    header = f'Catatan {start_date} sampai {end_date} ({zone.key}).'
    if mode == 'summary':
        values = '; '.join(f'{label}: {volumes[key]} ml' if volume_counts[key] else f'{label}: belum tercatat'
                           for key, label in (('expressed', 'ASIP'), ('formula', 'formula')))
        body = f"{header}\nMinum {counts['feeding']}, popok {counts['diaper']}, tidur {counts['sleep']} catatan. {values}. ASI langsung tidak termasuk volume."
    else:
        lines = [f"{n}. " + render_event(dict(record, occurred_at=datetime.fromisoformat(record['occurred_at'])), zone) for n, record in enumerate(records, 1)]
        body = header + '\n' + ('\n'.join(lines) if lines else 'Belum ada catatan yang cocok.')
        if sum(counts.values()) > len(records):
            body += '\nMenampilkan 10 catatan terbaru; detail lainnya di Mini App.'
    return body + '\nData kosong bukan bukti aktivitas tidak terjadi.', records
