"""Validate structured event facts at the persistence boundary."""

import math
from datetime import datetime


def positive_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


def validate(kind, payload):
    if not isinstance(payload, dict):
        return False
    fields = {
        'feeding': {'type', 'volume_ml', 'duration_minutes', 'side', 'notes'},
        'diaper': {'type', 'notes'},
        'sleep': {'ended_at', 'notes'},
        'growth': {'type', 'value', 'unit', 'position', 'method', 'notes'},
        'note': {'text'},
    }
    if not isinstance(kind, str) or kind not in fields or not payload.keys() <= fields[kind]:
        return False
    if 'notes' in payload and (not isinstance(payload['notes'], str) or len(payload['notes']) > 2000):
        return False
    if kind == 'note':
        return isinstance(payload.get('text'), str) and 0 < len(payload['text'].strip()) <= 2000
    if kind == 'diaper':
        return payload.get('type') in ('pipis', 'pup', 'both')
    if kind == 'feeding':
        if payload.get('type') not in ('direct', 'expressed', 'formula', 'unknown'):
            return False
        for field in ('volume_ml', 'duration_minutes'):
            if field in payload and not positive_number(payload[field]):
                return False
        if payload['type'] == 'direct' and 'volume_ml' in payload:
            return False
        if ('side' in payload or 'duration_minutes' in payload) and payload['type'] != 'direct':
            return False
        return 'side' not in payload or payload['side'] in ('left', 'right', 'both', 'unknown')
    if kind == 'growth':
        units = {'weight': 'kg', 'length': 'cm', 'height': 'cm', 'head_circumference': 'cm'}
        measurement = payload.get('type')
        if not isinstance(measurement, str) or measurement not in units:
            return False
        position = {'length': 'recumbent', 'height': 'standing'}.get(measurement)
        method = payload.get('method')
        return (payload.get('unit') == units[measurement]
                and positive_number(payload.get('value')) and payload.get('position') == position
                and ('method' not in payload or (isinstance(method, str) and bool(method.strip()) and len(method) <= 200)))
    if 'ended_at' in payload:
        try:
            end = datetime.fromisoformat(payload['ended_at'])
            return end.utcoffset() is not None
        except (TypeError, ValueError):
            return False
    return True


def valid_time(kind, payload, occurred_at):
    return kind != 'sleep' or 'ended_at' not in payload or datetime.fromisoformat(payload['ended_at']) > occurred_at
