"""Conservative deterministic chat provider; unrecognized text is never stored as fact."""

import re
from datetime import datetime, date, timedelta


def completed_record(text, received_at, zone):
    """Conservative grammar for the clarification round trip; no model needed."""
    lowered = text.lower().replace('\nPelengkap dari pengguna: '.lower(), ' ').strip()
    local = received_at.astimezone(zone)
    day = local.date()
    if 'kemarin' in lowered:
        day -= timedelta(days=1)
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', lowered)
    if dates:
        if len(dates) != 1:
            return None
        try:
            day = date.fromisoformat(dates[0])
        except ValueError:
            return None
    # Require explicit date in this new grammar, unlike the legacy jam-first syntax.
    if not dates and not re.search(r'\b(hari ini|kemarin)\b', lowered):
        return None
    lowered = re.sub(r'\b(hari ini|kemarin|tanggal|pukul)\b|\b\d{4}-\d{2}-\d{2}\b', '', lowered)
    times = re.findall(r'\b(?:jam\s+)?(\d{1,2})[:.](\d{2})\b', lowered)
    if len(times) != 1:
        return None
    hour, minute = map(int, times[0])
    if hour > 23 or minute > 59:
        return None
    lowered = re.sub(r'\b(?:jam\s+)?\d{1,2}[:.]\d{2}\b', '', lowered).strip(' ,;')
    activity = re.fullmatch(r'(asip|formula)\s+(\d+(?:\.\d+)?)\s*ml|(pup|pipis)', lowered)
    if not activity:
        return None
    occurrence = local.replace(year=day.year, month=day.month, day=day.day, hour=hour, minute=minute, second=0, microsecond=0)
    if occurrence > local or occurrence.replace(fold=0).utcoffset() != occurrence.replace(fold=1).utcoffset():
        return None
    if activity[3]:
        event = {'kind':'diaper','payload':{'type':activity[3]},'occurred_at':occurrence}
    else:
        volume = float(activity[2])
        if not 0 < volume < 100000:
            return None
        event = {'kind':'feeding','payload':{'type':'expressed' if activity[1] == 'asip' else 'formula','volume_ml':volume},'occurred_at':occurrence}
    return {'kind':'create_events','events':[event],'requires_confirmation':True}


def interpret(text, received_at, zone):
    lowered = text.strip().lower()
    if any(word in lowered for word in ('tidak bernapas', 'tidak bernafas', 'kejang', 'tidak sadar')):
        return {'kind': 'emergency'}
    if lowered == '/start':
        return {'kind': 'start'}
    local = received_at.astimezone(zone)
    events = []
    for part in lowered.split(','):
        match = re.fullmatch(r'\s*jam\s+(?:(setengah)\s+)?(\d{1,2})(?:[.:](\d{2}))?\s+(asip\s+\d+(?:\.\d+)?\s*ml|formula\s+\d+(?:\.\d+)?\s*ml|pup|pipis)\s*', part)
        if not match:
            return {'kind': 'clarify'}
        half, hour_text, minute_text, activity = match.groups()
        hour = int(hour_text) - (1 if half else 0)
        minute = 30 if half else int(minute_text or 0)
        if hour not in range(24) or minute not in range(60) or (half and minute_text):
            return {'kind': 'clarify'}
        occurrence = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if occurrence.replace(fold=0).utcoffset() != occurrence.replace(fold=1).utcoffset():
            return {'kind': 'clarify'}
        # Ambiguous future times are not silently assigned to the previous day.
        if occurrence > local:
            return {'kind': 'clarify'}
        if activity in ('pup', 'pipis'):
            events.append({'kind': 'diaper', 'payload': {'type': activity}, 'occurred_at': occurrence})
        else:
            drink = re.fullmatch(r'(asip|formula)\s+(\d+(?:\.\d+)?)\s*ml', activity)
            volume = float(drink[2])
            if not 0 < volume < 100000:
                return {'kind': 'clarify'}
            events.append({'kind': 'feeding', 'payload': {'type': 'expressed' if drink[1] == 'asip' else 'formula', 'volume_ml': volume}, 'occurred_at': occurrence})
    return {'kind': 'create_events', 'events': events}

