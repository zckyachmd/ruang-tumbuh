"""Conservative deterministic chat provider; unrecognized text is never stored as fact."""

import re
from datetime import datetime


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
