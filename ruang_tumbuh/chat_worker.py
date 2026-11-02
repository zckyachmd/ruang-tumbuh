"""Durable inbound processing. Delivery is handled separately from processing."""

import os
import re
import secrets
import signal
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from psycopg.types.json import Jsonb

from .chat import interpret
from .agent import FakeProvider, OpenAICompatibleProvider, ProviderError, ai_consent_scope, render_event
from .store import Denied, Invalid, Store


def process_one(store, provider=None):
    provider = provider or FakeProvider()
    token = secrets.token_urlsafe(24)
    with store.connect() as conn:
        conn.execute("UPDATE inbound_updates SET status='failed',payload='{}'::jsonb,last_error='lease expired',lease_until=NULL,lease_token=NULL WHERE status='processing' AND attempts >= 5 AND lease_until < now()")
        row = conn.execute("""WITH candidate AS (
            SELECT update_id FROM inbound_updates WHERE attempts < 5 AND
              (status='pending' OR (status='processing' AND lease_until < now()))
              ORDER BY received_at FOR UPDATE SKIP LOCKED LIMIT 1
            ) UPDATE inbound_updates u SET status='processing', attempts=attempts+1,
              lease_until=now()+interval '2 minutes', lease_token=%s
            FROM candidate c WHERE u.update_id=c.update_id
            RETURNING u.update_id,u.telegram_user_id,u.payload""", (token,)).fetchone()
    if not row:
        return False
    update_id, user, encrypted_update = row
    update = store.data_cipher.open_json(encrypted_update, "inbound_updates.payload")
    message = update['message']
    text = message['text']
    response_family = None
    proposed_events = None
    usage = None
    try:
        families = store.families(user)
        selection = store.chat_selection(user)
        if selection is None and len(families) == 1:
            children = store.children(families[0][0], user)
            if len(children) == 1:
                store.set_chat_selection(families[0][0], user, children[0][0])
                selection = store.chat_selection(user)
        context_family = selection[0] if selection else (families[0][0] if len(families) == 1 else None)
        if context_family is not None:
            with store.connect() as conn:
                store._access(conn, context_family, user)
                assigned = conn.execute("UPDATE inbound_updates SET family_id=%s WHERE update_id=%s AND status='processing' AND lease_token=%s RETURNING update_id", (context_family, update_id, token)).fetchone()
                if not assigned:
                    return True
        emergency = interpret(text, datetime.fromtimestamp(message['date'], timezone.utc), timezone.utc)['kind'] == 'emergency'
        command = re.fullmatch(r'/([a-z]+)(?:@\w+)?(?:\s+(.+))?', text.strip(), flags=re.IGNORECASE)
        if emergency:
            response = 'Jika anak tidak bernapas, tidak sadar, atau mengalami kejang, segera hubungi layanan darurat setempat atau cari pertolongan medis segera.'
            draft = False
        elif command:
            name, argument = command.group(1).lower(), (command.group(2) or '').strip()
            if name in ('start', 'help') and not argument:
                response = ('Halo, saya membantu keluarga mencatat aktivitas anak dan melihat catatan yang tersimpan.\n'
                    'Mulai: /daftar Nama keluarga | Nama anak\n'
                    'Undang anggota (owner): /undang atau /undang ID_KELUARGA\n'
                    'Gabung dengan kode: /start KODE\n'
                    'Pilih profil: /keluarga lalu /pilih ID_KELUARGA ID_ANAK\n'
                    'Catatan hanya dibuat dari informasi yang kamu kirim; ini bukan diagnosis atau layanan darurat.')
                draft = False
            elif name == 'daftar':
                parts = argument.split('|')
                if len(parts) != 2 or not all(part.strip() for part in parts):
                    response = 'Format pendaftaran: /daftar Nama keluarga | Nama anak'
                elif any(len(part.strip()) > 100 for part in parts):
                    response = 'Nama keluarga dan nama anak maksimal 100 karakter.'
                else:
                    family, child = store.create_family(user, parts[0].strip(), parts[1].strip(), update_id=update_id)
                    store.set_chat_selection(family, user, child)
                    response_family = family
                    response = f'Keluarga berhasil dibuat. Anggota dan catatanmu bisa bergabung dengan /start KODE. Untuk membuat kode undangan, kirim /undang {family}.'
                draft = False
            elif name == 'undang':
                families = store.families(user)
                requested = None
                invalid_family_id = False
                if argument:
                    if not argument.isdecimal() or len(argument) > 19 or int(argument) > 9223372036854775807:
                        invalid_family_id = True
                    else:
                        requested = int(argument)
                elif len(families) == 1:
                    requested = families[0][0]
                if invalid_family_id:
                    response = 'ID keluarga tidak valid. Lihat ID yang tersedia melalui /keluarga.'
                elif requested is None:
                    response = 'Pilih keluarga dengan /undang ID_KELUARGA. Lihat ID melalui /keluarga.'
                else:
                    try:
                        invite_token = store.invite(requested, user, update_id=update_id)
                        response_family = requested
                        response = f'Kode undangan sekali pakai berlaku 24 jam. Bagikan dengan anggota keluarga: /start {invite_token}'
                    except Denied:
                        response = 'Hanya owner aktif keluarga tersebut yang dapat membuat undangan.'
                draft = False
            elif name == 'keluarga' and not argument:
                families = store.families(user)
                selection = store.chat_selection(user)
                response = ('Belum ada keluarga. Mulai dengan /daftar Nama keluarga | Nama anak.' if not families else
                    'Keluarga dan profil yang bisa kamu akses:\n' + '\n'.join(
                        f'{row[1]} — ID {row[0]} ({row[3]}): ' + ', '.join(
                            f'{child[1]} (ID {child[0]})' + (' ✓' if selection and (selection[0], selection[1]) == (row[0], child[0]) else '')
                            for child in store.children(row[0], user)) for row in families))
                draft = False
            elif name == 'pilih':
                parts = argument.split()
                valid_ids = len(parts) == 2 and all(part.isdecimal() and len(part) <= 19 and int(part) <= 9223372036854775807 for part in parts)
                if not valid_ids:
                    response = 'Format: /pilih ID_KELUARGA ID_ANAK. Lihat ID melalui /keluarga.'
                else:
                    try:
                        family_id, child_id = map(int, parts)
                        store.set_chat_selection(family_id, user, child_id)
                        selected = store.chat_selection(user)
                        response_family = family_id
                        response = f'Chat sekarang mencatat untuk {selected[4]} di {selected[2]}.'
                    except (Denied, Invalid):
                        response = 'Keluarga atau profil tidak ditemukan, atau kamu tidak memiliki akses aktif.'
                draft = False
            elif name == 'start' and argument:
                try:
                    family = store.redeem(user, argument, update_id=update_id)
                    response_family = family
                    response = 'Kamu sudah bergabung. Data keluarga hanya dapat diakses oleh anggota aktif.'
                except Invalid:
                    response = 'Kode undangan tidak valid, sudah dipakai, atau kedaluwarsa. Minta owner membuat kode baru.'
                draft = False
            elif name == 'ai':
                consent_scope = ai_consent_scope()
                parts = argument.split()
                mode = parts[0].lower() if parts else 'status'
                family_arg = parts[1] if len(parts) == 2 else ''
                families = store.families(user)
                valid_family_arg = family_arg.isdecimal() and len(family_arg) <= 19 and int(family_arg) <= 9223372036854775807 if family_arg else False
                family_id = int(family_arg) if valid_family_arg else (families[0][0] if len(families) == 1 and not family_arg else None)
                if len(parts) > 2 or (family_arg and not valid_family_arg):
                    response = 'Format: /ai aktif ID, /ai setuju ID, /ai nonaktif ID, atau /ai status ID.'
                elif family_id is None:
                    response = 'Pilih keluarga untuk pengaturan AI dengan /ai status ID. Lihat daftar melalui /keluarga.'
                elif mode == 'aktif':
                    if store.ai_consent(family_id, user, consent_scope):
                        response = f'AI eksternal sudah aktif untuk chat keluargamu (ID {family_id}).'
                    else:
                        response = ('Jika disetujui, isi pesan chatmu (termasuk catatan aktivitas atau kesehatan anak), waktu pesan, dan zona waktu keluarga akan dikirim ke endpoint AI kompatibel yang dikonfigurasi operator. '
                            'Nama keluarga/anak, tanggal lahir profil aktif bila disebut sebagai tanggal lahir, email, username Telegram, dan nomor telepon yang dikenali akan disamarkan. Detail lain yang tidak terdeteksi dapat tetap terkirim. '
                            'Penyedia endpoint dapat menyimpan atau mencatat data sesuai kebijakannya; aplikasi tidak mengatur retensi penyedia. Tanyakan kebijakan ini kepada operator sebelum menyetujui. '
                            'Kirim /ai setuju untuk mengaktifkan, atau abaikan pesan ini.')
                elif mode == 'setuju':
                    store.set_ai_consent(family_id, user, True, consent_scope)
                    response = f'AI eksternal diaktifkan untuk chat keluargamu (ID {family_id}). Matikan kapan saja dengan /ai nonaktif.'
                    response_family = family_id
                elif mode == 'nonaktif':
                    store.set_ai_consent(family_id, user, False, consent_scope)
                    response = f'AI eksternal dinonaktifkan untuk chat keluargamu (ID {family_id}). Pesan berikutnya tidak dikirim ke AI.'
                    response_family = family_id
                elif mode == 'status':
                    response = (f'AI eksternal aktif untuk keluarga ID {family_id}.' if store.ai_consent(family_id, user, consent_scope)
                        else f'AI eksternal nonaktif untuk keluarga ID {family_id}. Kirim /ai aktif {family_id} untuk membaca penjelasan sebelum memilih.')
                else:
                    response = 'Format: /ai aktif ID, /ai setuju ID, /ai nonaktif ID, atau /ai status ID.'
                draft = False
            else:
                response = 'Perintah belum dikenali. Kirim /help untuk melihat cara daftar, mengundang, dan mulai mencatat.'
                draft = False
        elif selection is None:
            response = ('Sebelum mencatat, buat keluarga dengan /daftar Nama keluarga | Nama anak.' if not families else
                'Pilih profil anak dengan /keluarga lalu /pilih ID_KELUARGA ID_ANAK sebelum mencatat.')
            draft = False
        else:
            family, selected_child, _, zone_name, _ = selection
            children = store.children(family, user)
            received_at = datetime.fromtimestamp(message['date'], timezone.utc)
            answer = None
            if text.strip().lower() == 'tidak ada':
                with store.connect() as conn:
                    store._access(conn, family, user)
                    answer = conn.execute("""SELECT local_date FROM scheduled_occurrences WHERE family_id=%s AND telegram_user_id=%s
                        AND kind='checkin' AND status IN ('attempted','sent','simulated','uncertain')
                        AND due_at <= %s AND expires_at >= %s ORDER BY due_at DESC LIMIT 1""", (family, user, received_at, received_at)).fetchone()
            if answer:
                from .checkins import acknowledge
                acknowledge(store, family, user, answer[0])
                response = 'Terima kasih, check-in keluarga untuk hari ini ditutup. Tidak ada catatan baru yang dibuat.'
                draft = False
            elif not any(child[0] == selected_child for child in children):
                response = 'Profil anak yang dipilih tidak lagi tersedia. Pilih ulang melalui /keluarga.'
                draft = False
            else:
                zone = ZoneInfo(zone_name)
                confirmation = re.fullmatch(r'\s*simpan\s+(\d{1,19})\s*', text, flags=re.IGNORECASE)
                cancellation = re.fullmatch(r'\s*batal\s+(\d{1,19})\s*', text, flags=re.IGNORECASE)
                if confirmation or cancellation:
                    draft_id = int((confirmation or cancellation)[1])
                    if draft_id > 9223372036854775807:
                        raise Invalid()
                    if cancellation:
                        result = {'kind': 'cancelled_draft' if store.cancel_agent_draft(family, user, draft_id) else 'expired_draft'}
                    else:
                        try:
                            events, ids = store.confirm_agent_draft(family, user, draft_id)
                            result = {'kind': 'committed', 'events': events, 'count': len(ids)}
                        except Invalid:
                            result = {'kind': 'expired_draft'}
                elif text.startswith('/'):
                    result = {'kind': 'clarify'}
                else:
                    try:
                        response_family = family
                        if getattr(provider, 'requires_consent', False):
                            with store.connect() as conn:
                                store._access(conn, family, user)
                                consent = conn.execute("SELECT enabled,provider_scope FROM ai_processing_consents WHERE family_id=%s AND telegram_user_id=%s", (family, user)).fetchone()
                                if consent and consent[0] and consent[1] == ai_consent_scope():
                                    selected_profile = next(child for child in children if child[0] == selected_child)
                                    result = provider.propose(text, received_at, zone,
                                        known_names=[selection[2], *(child[1] for child in children)],
                                        known_birth_dates=[selected_profile[2]])
                                    usage = result.get('usage')
                                else:
                                    result = {'kind': 'ai_disabled'}
                        else:
                            result = provider.propose(text, received_at, zone)
                            usage = result.get('usage')
                    except ProviderError:
                        result = {'kind': 'provider_error'}
                draft = False
                if result['kind'] == 'emergency':
                    response = 'Jika anak tidak bernapas, tidak sadar, atau mengalami kejang, segera hubungi layanan darurat setempat atau cari pertolongan medis segera.'
                elif result['kind'] == 'out_of_scope':
                    response = 'Aku membantu mencatat dan mencari riwayat keluarga. Aku tidak memberi diagnosis, saran perawatan, dosis, atau tafsiran WHO. Untuk kekhawatiran kesehatan, hubungi tenaga kesehatan; untuk keadaan darurat, cari layanan gawat darurat setempat.'
                elif result['kind'] == 'start':
                    response = 'Selamat datang. Buat atau pilih keluarga dan profil anak melalui Mini App.'
                elif result['kind'] == 'create_events':
                    events = result['events']
                    lines = [render_event(event, zone) for event in events]
                    if result.get('requires_confirmation'):
                        proposed_events = [dict(event, occurred_at=event['occurred_at'].isoformat()) for event in events]
                        response = 'Periksa usulan berikut; belum disimpan:\n' + '\n'.join(lines) + f'\nBalas "simpan {update_id}" atau "batal {update_id}" dalam 24 jam.'
                    else:
                        ids = store.create_events(family, user, selected_child, events, update_id=update_id, action_key='create_events')
                        response = f"Tersimpan {len(ids)} catatan:\n" + '\n'.join(lines)
                    response_family = family
                elif result['kind'] == 'committed':
                    response = f"Tersimpan {result['count']} catatan:\n" + '\n'.join(render_event(event, zone) for event in result['events'])
                    response_family = family
                elif result['kind'] == 'cancelled_draft':
                    response = 'Usulan dibatalkan. Tidak ada catatan baru yang dibuat.'
                elif result['kind'] == 'expired_draft':
                    response = 'Usulan tidak ditemukan, telah dibatalkan, atau kedaluwarsa. Kirim ulang informasi yang ingin dicatat.'
                elif result['kind'] == 'find_events':
                    found = store.last_event(family, user, selected_child, result['category'], received_at)
                    response = ('Belum ada catatan yang cocok. Ini tidak berarti aktivitas tidak terjadi.' if not found else
                        'Catatan terakhir: ' + render_event({'kind': found[0], 'payload': found[1], 'occurred_at': found[2]}, zone))
                    response_family = family
                elif result['kind'] == 'get_summary':
                    summary = store.today_summary(family, user, selected_child, as_of=received_at)
                    expressed = f"{summary['volume_ml']['expressed']} ml" if summary['volume_counts']['expressed'] else 'belum tercatat'
                    formula = f"{summary['volume_ml']['formula']} ml" if summary['volume_counts']['formula'] else 'belum tercatat'
                    response = (f"Ringkasan {summary['date']} ({zone_name}): minum {summary['counts']['feeding']}, popok {summary['counts']['diaper']}, tidur {summary['counts']['sleep']} catatan. "
                        f"Volume ASIP {expressed}, formula {formula}. ASI langsung tidak termasuk volume. Data kosong bukan bukti aktivitas tidak terjadi.")
                    response_family = family
                elif result['kind'] == 'provider_error':
                    response = 'Pemrosesan chat tidak tersedia. Tidak ada catatan baru yang disimpan; gunakan formulir Mini App atau coba lagi nanti.'
                elif result['kind'] == 'ai_disabled':
                    response = f'AI eksternal nonaktif untuk keluarga ID {family}. Kirim /ai aktif {family} untuk membaca penjelasan dan memilih.'
                else:
                    response = 'Belum ada catatan yang disimpan. Jelaskan aktivitas, tanggal, dan waktunya; contoh: jam 9 ASIP 120 ml, jam setengah 10 pup.'
                    draft = True
        with store.connect() as conn:
            if response_family is not None:
                store._access(conn, response_family, user)
            current = conn.execute("SELECT 1 FROM inbound_updates WHERE update_id=%s AND status='processing' AND lease_token=%s FOR UPDATE", (update_id, token)).fetchone()
            if not current:
                return True
            if draft:
                conn.execute("INSERT INTO chat_drafts (update_id,telegram_user_id,text,expires_at) VALUES (%s,%s,'',now()+interval '24 hours') ON CONFLICT DO NOTHING", (update_id, user))
            if proposed_events is not None:
                        conn.execute("INSERT INTO agent_drafts (update_id,family_id,child_id,telegram_user_id,events,expires_at) VALUES (%s,%s,%s,%s,%s,now()+interval '24 hours') ON CONFLICT DO NOTHING", (update_id, family, selected_child, user, Jsonb(store.data_cipher.seal_json(proposed_events, "agent_drafts.events"))))
            if usage is not None:
                conn.execute("INSERT INTO agent_usage (update_id,family_id,model,input_tokens,output_tokens) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (update_id, family, usage['model'], usage['input_tokens'], usage['output_tokens']))
            conn.execute("INSERT INTO chat_outbox (update_id,recipient_id,family_id,body) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", (update_id, user, response_family, store.data_cipher.seal(response, "chat_outbox.body")))
            conn.execute("UPDATE inbound_updates SET family_id=COALESCE(family_id,%s),payload='{}'::jsonb,status='completed',lease_until=NULL,lease_token=NULL WHERE update_id=%s", (response_family, update_id))
    except (Denied, Invalid, ValueError, KeyError, OverflowError):
        with store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status='failed',payload='{}'::jsonb,last_error='invalid or inaccessible',lease_until=NULL,lease_token=NULL WHERE update_id=%s AND lease_token=%s", (update_id, token))
    except Exception:
        with store.connect() as conn:
            conn.execute("UPDATE inbound_updates SET status=CASE WHEN attempts >= 5 THEN 'failed' ELSE 'pending' END,payload=CASE WHEN attempts >= 5 THEN '{}'::jsonb ELSE payload END,last_error='processing error',lease_until=NULL,lease_token=NULL WHERE update_id=%s AND lease_token=%s", (update_id, token))
    return True


def main():
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    store = Store(os.environ['DATABASE_URL'])
    try:
        chat_content_retention_days = int(os.getenv('CHAT_CONTENT_RETENTION_DAYS', '7'))
    except ValueError as exc:
        raise ValueError('CHAT_CONTENT_RETENTION_DAYS must be an integer between 1 and 30') from exc
    if not 1 <= chat_content_retention_days <= 30:
        raise ValueError('CHAT_CONTENT_RETENTION_DAYS must be an integer between 1 and 30')
    delivery = os.getenv('TELEGRAM_DELIVERY', 'disabled')
    if delivery not in ('disabled', 'fake', 'telegram') or (delivery == 'fake' and os.getenv('APP_ENV') != 'development'):
        raise ValueError('Invalid delivery mode')
    if delivery == 'telegram' and not os.getenv('TELEGRAM_BOT_TOKEN'):
        raise ValueError('TELEGRAM_BOT_TOKEN is required for Telegram delivery')
    ai_provider = os.getenv('AI_PROVIDER', 'fake')
    if ai_provider == 'fake':
        provider = FakeProvider()
    elif ai_provider == 'openai-compatible':
        provider = OpenAICompatibleProvider(os.getenv('AI_API_KEY', ''), os.getenv('AI_MODEL', ''),
                                           os.getenv('AI_BASE_URL', ''))
    else:
        raise ValueError('Invalid AI_PROVIDER')
    next_cleanup = 0.0
    while running:
        if time.monotonic() >= next_cleanup:
            from .retention import cleanup
            cleanup(store, chat_content_retention_days)
            next_cleanup = time.monotonic() + 3600
        processed = process_one(store, provider)
        from .checkins import deliver_checkin, schedule_today
        schedule_today(store)
        if delivery != 'disabled':
            from .delivery import deliver_one
            processed = deliver_one(store, delivery, os.getenv('TELEGRAM_BOT_TOKEN', '')) or processed
            processed = deliver_checkin(store, delivery, os.getenv('TELEGRAM_BOT_TOKEN', '')) or processed
        if not processed:
            time.sleep(2)


if __name__ == '__main__':
    main()
