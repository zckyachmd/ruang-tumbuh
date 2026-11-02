"""Authorized CSV export for the requested family and date range."""

import csv
import io
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .store import Invalid


def safe_cell(value):
    text = '' if value is None else str(value)
    if text and (text[0] in '\t\r\n' or text.lstrip().startswith(('=', '+', '-', '@'))):
        return "'" + text
    return text


def export_csv(store, family, user, start_date, end_date):
    if start_date > end_date or end_date == date.max or start_date == date.min:
        raise Invalid()
    with store.connect() as conn:
        store._access(conn, family, user, owner=True)
        zone = ZoneInfo(conn.execute('SELECT timezone FROM families WHERE id=%s', (family,)).fetchone()[0])
        start = datetime.combine(start_date, time.min, zone).astimezone(timezone.utc)
        end = datetime.combine(end_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        rows = conn.execute("""SELECT e.id,c.id,c.nickname,e.kind,e.payload,e.occurred_at,e.created_at,e.created_by,e.version
            FROM events e JOIN children c ON c.family_id=e.family_id AND c.id=e.child_id
            WHERE e.family_id=%s AND e.deleted_at IS NULL AND e.occurred_at >= %s AND e.occurred_at < %s
            ORDER BY e.occurred_at,e.id""", (family, start, end)).fetchall()
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(['event_id', 'child_id', 'child_nickname', 'kind', 'occurred_at_utc', 'created_at_utc', 'created_by_telegram_id', 'unit', 'payload_json', 'version'])
    for event_id, child_id, nickname, kind, payload, occurred, created, creator, version in rows:
        nickname = store.data_cipher.open(nickname, "children.nickname")
        payload = store.data_cipher.open_json(payload, "events.payload")
        writer.writerow([safe_cell(x) for x in (event_id, child_id, nickname, kind, occurred.astimezone(timezone.utc).isoformat(),
                         created.astimezone(timezone.utc).isoformat(), creator, payload.get('unit', 'ml' if 'volume_ml' in payload else ''),
                         json.dumps(payload, ensure_ascii=False, separators=(',', ':')), version)])
    return output.getvalue()
