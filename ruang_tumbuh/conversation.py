"""Local identity resolution and bounded, encrypted clarification context."""

import re
from datetime import datetime, timezone


def named_children(text, children):
    return {child[0] for child in children if re.search(
        r'(?<!\w)' + re.escape(child[1].strip()) + r'(?!\w)', text, re.IGNORECASE)}


def load_context(store, family, user, child):
    with store.connect() as conn:
        store._access(conn, family, user)
        row = conn.execute('SELECT content FROM conversation_contexts WHERE family_id=%s AND telegram_user_id=%s AND child_id=%s AND expires_at>now()',
                           (family, user, child)).fetchone()
        return store.data_cipher.open_json(row[0], 'conversation_contexts.content') if row else None


def save_context(conn, store, family, user, child, content):
    if content is None:
        conn.execute('DELETE FROM conversation_contexts WHERE family_id=%s AND telegram_user_id=%s AND child_id=%s', (family, user, child))
    else:
        conn.execute("""INSERT INTO conversation_contexts (family_id,telegram_user_id,child_id,content,expires_at)
            VALUES (%s,%s,%s,%s,now()+interval '30 minutes') ON CONFLICT (telegram_user_id,family_id,child_id)
            DO UPDATE SET content=excluded.content,expires_at=excluded.expires_at""",
            (family, user, child, store.data_cipher.seal_json(content, 'conversation_contexts.content')))


def merge_clarification(context, reply):
    """Only join an explicitly pending question; never infer a permanent event."""
    if not context or context.get('kind') != 'clarification':
        return reply
    if len(reply) > 1000 or len(context.get('message', '')) + len(reply) > 4000:
        return reply
    return context['message'] + '\nPelengkap dari pengguna: ' + reply


def clarification_question(text):
    if not re.search(r'\b(jam|pukul|\d{1,2}[:.]\d{2})\b', text, re.IGNORECASE):
        return 'Aktivitasnya terjadi tanggal berapa dan jam berapa?'
    if not re.search(r'\b(hari ini|kemarin|\d{4}-\d{2}-\d{2})\b', text, re.IGNORECASE):
        return 'Ini untuk hari ini, kemarin, atau tanggal lain?'
    return 'Boleh tulis jenis aktivitas dan detail yang diketahui? Usulannya akan saya tampilkan sebelum disimpan.'
