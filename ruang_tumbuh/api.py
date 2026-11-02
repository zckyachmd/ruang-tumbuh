"""HTTP boundary. Authentication is required before every family operation."""

import os
import hmac
from pathlib import Path
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .store import Conflict, Denied, Invalid, Store
from .admission import QueueFull
from .agent import ai_consent_scope
from .checkins import acknowledge, get_preferences, set_preferences
from .migrate import schema_ready
from .export import export_csv
from .reminders import cancel_reminder, create_reminder, list_reminders
from .telegram_auth import AuthenticationError, verify_init_data
from .telegram_updates import minimal_private_update


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')


class InitData(Body):
    init_data: str = Field(max_length=8192)


class DevIdentity(Body):
    user_id: int = Field(gt=0, lt=2**52)


class Family(Body):
    name: str = Field(min_length=1, max_length=100)
    nickname: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default='Asia/Jakarta', max_length=100)


class Invitation(Body):
    token: str = Field(min_length=1, max_length=256)


class AIConsent(Body):
    enabled: StrictBool


class Child(Body):
    nickname: str = Field(min_length=1, max_length=100)
    birth_date: date | None = None
    sex: str | None = None
    premature_notes: str | None = Field(default=None, max_length=1000)


class MemberRole(Body):
    role: str


class Event(Body):
    kind: str
    payload: dict[str, Any]
    occurred_at: datetime


class EventUpdate(Body):
    version: int = Field(gt=0)
    payload: dict[str, Any]
    occurred_at: datetime


class EventDelete(Body):
    version: int = Field(gt=0, strict=True)
    confirmed: StrictBool


class FamilyDelete(Body):
    token: str = Field(min_length=1, max_length=256)
    phrase: str


class LocalEvent(Body):
    kind: str
    payload: dict[str, Any]
    occurred_local: str


class LocalEventUpdate(Body):
    version: int = Field(gt=0)
    kind: str
    payload: dict[str, Any]
    occurred_local: str
    occurred_original: datetime | None = None


def local_instant(value, zone_name):
    try:
        value = datetime.fromisoformat(value)
        if value.tzinfo is not None:
            raise ValueError()
        zone = ZoneInfo(zone_name)
        local = value.replace(tzinfo=zone)
        if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset() or local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != value:
            raise ValueError()
        return local.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise Invalid() from None


def local_payload(kind, payload, zone):
    payload = dict(payload)
    if kind == 'sleep' and 'ended_local' in payload:
        payload['ended_at'] = local_instant(payload.pop('ended_local'), zone).isoformat()
    return payload


class CheckinSettings(Body):
    time: str
    timezone: str
    quiet_start: str | None = None
    quiet_end: str | None = None
    snoozed_until: str | None = None
    max_daily: int = Field(ge=1, le=20, strict=True)


class CheckinPreference(Body):
    enabled: StrictBool
    settings: CheckinSettings


class SummarySettings(CheckinSettings):
    child_id: int = Field(gt=0, strict=True)


class SummaryPreference(Body):
    enabled: StrictBool
    settings: SummarySettings


class ReminderCreate(Body):
    body: str = Field(min_length=1, max_length=500)
    due_local: str
    bypass_quiet_hours: StrictBool = False


def create_app(dsn, bot_token, *, environment='production', dev_auth=False, webhook_secret='', telegram_transport='webhook'):
    if dev_auth and environment != 'development':
        raise ValueError('Development authentication requires development environment')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(dsn)
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(QueueFull)
    async def queue_full(request, exc):
        return JSONResponse(status_code=429, content={'detail':'Antrean penuh, coba lagi nanti'}, headers={'Retry-After':'30'})

    @app.exception_handler(Denied)
    async def denied(request, exc):
        return JSONResponse(status_code=403, content={'detail': 'Akses ditolak'})

    @app.exception_handler(Invalid)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={'detail': 'Data tidak valid'})

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={'detail': 'Data berubah atau kunci sudah digunakan'})

    def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if credentials is None:
            raise HTTPException(status_code=401, detail='Sesi diperlukan')
        try:
            return store.session_user(credentials.credentials)
        except Denied:
            raise HTTPException(status_code=401, detail='Sesi tidak valid') from None

    @app.middleware('http')
    async def no_store(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/config')
    def public_config():
        return {'development_auth': environment == 'development' and dev_auth}

    @app.get('/ready')
    def ready():
        try:
            with store.connect() as conn:
                if not schema_ready(conn, Path(__file__).resolve().parent.parent / 'migrations'):
                    raise RuntimeError('Migration missing or modified')
        except Exception:
            raise HTTPException(status_code=503, detail='Database atau skema belum siap') from None
        return {'status': 'ready'}

    @app.post('/api/session')
    def session(body: InitData):
        try:
            user = verify_init_data(body.init_data, bot_token)
        except AuthenticationError:
            raise HTTPException(status_code=401, detail='Data Telegram tidak valid') from None
        return {'token': store.new_session(user), 'expires_in': 3600}

    @app.post('/telegram/webhook')
    async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(default='')):
        if telegram_transport != 'webhook':
            raise HTTPException(status_code=404, detail='Transport webhook tidak aktif')
        if not webhook_secret or not hmac.compare_digest(webhook_secret.encode(), x_telegram_bot_api_secret_token.encode()):
            raise HTTPException(status_code=403, detail='Akses ditolak')
        raw = await request.body()
        if len(raw) > 65536:
            raise HTTPException(status_code=413, detail='Update terlalu besar')
        try:
            import json
            update = json.loads(raw)
            update_id = update['update_id']
            message = update.get('message')
            if not isinstance(message, dict) or message.get('chat', {}).get('type') != 'private':
                return {'ok': True}
            user = message['from']['id']
            if (type(update_id) is not int or type(user) is not int or user <= 0
                    or message['chat']['id'] != user or message['from'].get('is_bot') is True
                    or not isinstance(message.get('text'), str) or len(message['text']) > 4096
                    or type(message.get('date')) is not int):
                raise ValueError()
            store.record_update(update_id, user, minimal_private_update(update_id, user, message['text'], message['date']))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(status_code=400, detail='Update tidak valid') from None
        return {'ok': True}

    if environment == 'development' and dev_auth:
        @app.post('/api/dev/session')
        def dev_session(body: DevIdentity):
            return {'token': store.new_session(body.user_id), 'expires_in': 3600}

    @app.get('/api/families')
    def families(user: int = Depends(current_user)):
        return [{'id': row[0], 'name': row[1], 'timezone': row[2], 'role': row[3]} for row in store.families(user)]

    @app.post('/api/families', status_code=201)
    def create_family(body: Family, user: int = Depends(current_user)):
        family, child = store.create_family(user, body.name, body.nickname, body.timezone)
        return {'family_id': family, 'child_id': child}

    @app.post('/api/families/{family}/invitations', status_code=201)
    def invite(family: int, user: int = Depends(current_user)):
        return {'token': store.invite(family, user)}

    @app.post('/api/families/{family}/deletion-request')
    def request_deletion(family: int, user: int = Depends(current_user)):
        return {'token': store.request_family_deletion(family, user), 'expires_in': 600}

    @app.post('/api/families/{family}/delete', status_code=204)
    def delete_family(family: int, body: FamilyDelete, user: int = Depends(current_user)):
        store.delete_family(family, user, body.token, body.phrase)

    @app.post('/api/invitations/redeem')
    def redeem(body: Invitation, user: int = Depends(current_user)):
        return {'family_id': store.redeem(user, body.token)}

    @app.delete('/api/families/{family}/members/{target}', status_code=204)
    def revoke(family: int, target: int, user: int = Depends(current_user)):
        store.revoke(family, user, target)

    @app.get('/api/families/{family}/members')
    def members(family: int, user: int = Depends(current_user)):
        return [{'user_id': row[0], 'role': row[1]} for row in store.members(family, user)]

    @app.get('/api/families/{family}/ai-usage')
    def ai_usage(family: int, user: int = Depends(current_user)):
        return [{'model': row[0], 'input_tokens': row[1], 'output_tokens': row[2]} for row in store.agent_usage(family, user)]

    @app.get('/api/families/{family}/ai-consent')
    def ai_consent(family: int, user: int = Depends(current_user)):
        return {'enabled': store.ai_consent(family, user, ai_consent_scope())}

    @app.put('/api/families/{family}/ai-consent')
    def save_ai_consent(family: int, body: AIConsent, user: int = Depends(current_user)):
        store.set_ai_consent(family, user, body.enabled, ai_consent_scope())
        return {'enabled': body.enabled}

    @app.put('/api/families/{family}/members/{target}/role')
    def change_role(family: int, target: int, body: MemberRole, user: int = Depends(current_user)):
        store.set_role(family, user, target, body.role)
        return {'role': body.role}

    @app.get('/api/families/{family}/children')
    def children(family: int, user: int = Depends(current_user)):
        return [{'id': row[0], 'nickname': row[1], 'birth_date': row[2], 'sex': row[3], 'premature_notes': row[4]} for row in store.children(family, user)]

    @app.post('/api/families/{family}/children', status_code=201)
    def add_child(family: int, body: Child, user: int = Depends(current_user)):
        return {'id': store.save_child(family, user, body.nickname, body.birth_date, body.sex, body.premature_notes)}

    @app.put('/api/families/{family}/children/{child}')
    def update_child(family: int, child: int, body: Child, user: int = Depends(current_user)):
        return {'id': store.save_child(family, user, body.nickname, body.birth_date, body.sex, body.premature_notes, child)}

    @app.get('/api/families/{family}/checkin-preferences')
    def checkin_preferences(family: int, user: int = Depends(current_user)):
        return get_preferences(store, family, user)

    @app.get('/api/families/{family}/summary-preferences')
    def summary_preferences(family: int, user: int = Depends(current_user)):
        return get_preferences(store, family, user, 'daily_summary')

    @app.put('/api/families/{family}/summary-preferences')
    def save_summary_preferences(family: int, body: SummaryPreference, user: int = Depends(current_user)):
        set_preferences(store, family, user, body.enabled, body.settings.model_dump(), 'daily_summary')
        return {'enabled': body.enabled, 'settings': body.settings.model_dump()}

    @app.get('/api/families/{family}/reminder-preferences')
    def reminder_preferences(family: int, user: int = Depends(current_user)):
        return get_preferences(store, family, user, 'reminder')

    @app.put('/api/families/{family}/reminder-preferences')
    def save_reminder_preferences(family: int, body: CheckinPreference, user: int = Depends(current_user)):
        set_preferences(store, family, user, body.enabled, body.settings.model_dump(), 'reminder')
        return {'enabled': body.enabled, 'settings': body.settings.model_dump()}

    @app.get('/api/families/{family}/reminders')
    def reminders(family: int, user: int = Depends(current_user)):
        return [{'id': row[0], 'body': row[1], 'due_at': row[2], 'expires_at': row[3], 'bypass_quiet_hours': row[4], 'cancelled_at': row[5], 'status': row[6]} for row in list_reminders(store, family, user)]

    @app.post('/api/families/{family}/reminders', status_code=201)
    def add_reminder(family: int, body: ReminderCreate, idempotency_key: str = Header(min_length=1, max_length=200), user: int = Depends(current_user)):
        zone = store.family_timezone(family, user)
        reminder = create_reminder(store, family, user, body.body, local_instant(body.due_local, zone), body.bypass_quiet_hours, idempotency_key)
        return {'id': reminder}

    @app.post('/api/families/{family}/reminders/{reminder}/cancel', status_code=204)
    def cancel(family: int, reminder: int, user: int = Depends(current_user)):
        cancel_reminder(store, family, user, reminder)

    @app.put('/api/families/{family}/checkin-preferences')
    def save_checkin_preferences(family: int, body: CheckinPreference, user: int = Depends(current_user)):
        set_preferences(store, family, user, body.enabled, body.settings.model_dump())
        return {'enabled': body.enabled, 'settings': body.settings.model_dump(), 'suppression': 'Jawaban menutup check-in keluarga untuk tanggal tersebut.'}

    @app.post('/api/families/{family}/checkin-answered')
    def answer_checkin(family: int, user: int = Depends(current_user)):
        get_preferences(store, family, user)
        zones = [row[2] for row in store.families(user) if row[0] == family]
        if not zones:
            raise Denied()
        day = datetime.now(ZoneInfo(zones[0])).date()
        acknowledge(store, family, user, day)
        return {'date': day.isoformat()}

    @app.get('/api/chat-selection')
    def chat_selection(user: int = Depends(current_user)):
        selected = store.chat_selection(user)
        return {'family_id': selected[0], 'child_id': selected[1]} if selected else None

    @app.put('/api/families/{family}/children/{child}/chat-selection')
    def choose_chat_profile(family: int, child: int, user: int = Depends(current_user)):
        store.set_chat_selection(family, user, child)
        return {'family_id': family, 'child_id': child}

    @app.get('/api/families/{family}/delivery-status')
    def delivery_status(family: int, user: int = Depends(current_user)):
        with store.connect() as conn:
            store._access(conn, family, user)
            rows = conn.execute('SELECT update_id,status,attempts,next_attempt_at FROM chat_outbox WHERE family_id=%s AND recipient_id=%s ORDER BY update_id DESC LIMIT 20', (family,user)).fetchall()
        return [{'update_id':row[0], 'status':row[1], 'attempts':row[2], 'retry_at':row[3]} for row in rows]

    @app.get('/api/families/{family}/children/{child}/growth-series')
    def growth_series(family: int, child: int, user: int = Depends(current_user)):
        from .growth import compare, GrowthUnavailable
        children = store.children(family, user)
        profile = next((item for item in children if item[0] == child), None)
        if profile is None:
            raise Invalid()
        zone = ZoneInfo(store.family_timezone(family,user))
        rows = store.timeline(family, user, child, limit=100, kind='growth')
        results = []
        for row in rows:
            payload, instant = row[2], row[3]
            result = {'id':row[0], 'payload':payload, 'occurred_at':instant, 'comparison':None, 'unavailable':None}
            indicator = {'weight':'wfa', 'length':'lhfa', 'height':'lhfa', 'head_circumference':'hcfa'}.get(payload['type'])
            try:
                if not profile[2] or not profile[3]:
                    raise GrowthUnavailable('Tanggal lahir dan jenis kelamin diperlukan untuk perbandingan.')
                if profile[4]:
                    raise GrowthUnavailable('Informasi prematur perlu penilaian tenaga kesehatan; tidak dibuat penyesuaian otomatis.')
                age = (instant.astimezone(zone).date()-profile[2]).days
                result['comparison'] = compare(indicator, profile[3], age, payload['value'], position=payload.get('position'))
            except (GrowthUnavailable, OSError, KeyError, StopIteration, ValueError):
                result['unavailable'] = 'Perbandingan belum tersedia atau input/validasi belum lengkap. Catatan asli tetap tersimpan.'
            results.append(result)
        return {'measurements':results, 'limit':100, 'source':'https://www.who.int/tools/child-growth-standards',
                'notice':'Catatan dan perbandingan bukan diagnosis. WHO tidak mengesahkan aplikasi ini.'}

    @app.get('/api/families/{family}/children/{child}/events')
    def timeline(family: int, child: int, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), kind: str | None = None, user: int = Depends(current_user)):
        if kind is not None and kind not in ('feeding', 'diaper', 'sleep', 'growth', 'note'):
            raise Invalid()
        return [{'id': row[0], 'kind': row[1], 'payload': row[2], 'occurred_at': row[3], 'version': row[4]} for row in store.timeline(family, user, child, limit=limit, offset=offset, kind=kind)]

    @app.get('/api/families/{family}/children/{child}/summary')
    def summary(family: int, child: int, user: int = Depends(current_user)):
        return store.today_summary(family, user, child)

    @app.post('/api/families/{family}/children/{child}/events', status_code=201)
    def create_events(family: int, child: int, entries: list[Event], idempotency_key: str = Header(min_length=1, max_length=200), user: int = Depends(current_user)):
        if len(entries) > 20:
            raise Invalid()
        return {'event_ids': store.create_events(family, user, child, [entry.model_dump() for entry in entries], request_key=idempotency_key)}

    @app.put('/api/families/{family}/events/{event}')
    def update_event(family: int, event: int, body: EventUpdate, user: int = Depends(current_user)):
        return {'version': store.update_event(family, user, event, body.version, body.payload, body.occurred_at)}

    @app.post('/api/families/{family}/events/{event}/delete', status_code=204)
    def delete_event(family: int, event: int, body: EventDelete, user: int = Depends(current_user)):
        if not body.confirmed:
            raise Invalid()
        store.delete_event(family, user, event, body.version)

    @app.get('/api/families/{family}/export.csv')
    def download_csv(family: int, start: date, end: date, user: int = Depends(current_user)):
        content = export_csv(store, family, user, start, end)
        return Response(content=content, media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="ruang-tumbuh.csv"'})

    @app.post('/api/families/{family}/children/{child}/events-local', status_code=201)
    def create_local_event(family: int, child: int, body: LocalEvent, idempotency_key: str = Header(min_length=1, max_length=200), user: int = Depends(current_user)):
        zone = store.family_timezone(family, user)
        entry = {'kind': body.kind, 'payload': local_payload(body.kind, body.payload, zone), 'occurred_at': local_instant(body.occurred_local, zone)}
        return {'event_ids': store.create_events(family, user, child, [entry], request_key=idempotency_key)}

    @app.put('/api/families/{family}/events/{event}/local')
    def update_local_event(family: int, event: int, body: LocalEventUpdate, user: int = Depends(current_user)):
        zone = store.family_timezone(family, user)
        instant = local_instant(body.occurred_local, zone)
        if body.occurred_original and body.occurred_original.utcoffset() is not None and body.occurred_original.replace(microsecond=0) == instant:
            instant = body.occurred_original
        return {'version': store.update_event(family, user, event, body.version, local_payload(body.kind, body.payload, zone), instant)}

    static = Path(__file__).resolve().parent.parent / 'web'
    if static.is_dir():
        app.mount('/', StaticFiles(directory=static, html=True), name='web')

    return app


app = create_app(os.getenv('DATABASE_URL', ''), os.getenv('TELEGRAM_BOT_TOKEN', ''),
                 environment=os.getenv('APP_ENV', 'production'), dev_auth=os.getenv('DEV_AUTH_ENABLED') == '1',
                 webhook_secret=os.getenv('TELEGRAM_WEBHOOK_SECRET', ''),
                 telegram_transport=os.getenv('TELEGRAM_TRANSPORT', 'disabled'))

