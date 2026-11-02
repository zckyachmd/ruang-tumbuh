"""Mobile/desktop acceptance against a real API and isolated PostgreSQL schema."""
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from playwright.sync_api import sync_playwright, expect
from ruang_tumbuh.migrate import migrate

schema = 'ui_'+secrets.token_hex(6)
base = os.environ['TEST_DATABASE_URL']
with psycopg.connect(base,autocommit=True) as conn:
    conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
dsn = make_conninfo(base, options='-csearch_path='+schema)
migrate(dsn,Path('migrations'))
environment = dict(os.environ,DATABASE_URL=dsn,APP_ENV='development',DEV_AUTH_ENABLED='1')
process = subprocess.Popen([sys.executable,'-m','uvicorn','ruang_tumbuh.api:app','--host','127.0.0.1','--port','8137','--no-access-log'],env=environment,stdout=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            urllib.request.urlopen('http://127.0.0.1:8137/ready',timeout=1)
            break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('API did not become ready')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (390,1280):
            page = browser.new_page(viewport={'width':width,'height':844})
            errors=[]
            page.on('pageerror',lambda error: errors.append(str(error)))
            # No live Telegram session: explicitly exercise development auth with synthetic IDs.
            page.route('https://telegram.org/**',lambda route:route.abort())
            page.goto('http://127.0.0.1:8137')
            page.get_by_label('ID pengguna uji').fill(str(width))
            page.get_by_role('button',name='Masuk sebagai pengguna uji').click()
            page.get_by_label('Nama keluarga',exact=True).fill('Synthetic '+str(width))
            page.get_by_label('Nama panggilan anak',exact=True).fill('Alya')
            page.get_by_role('button',name='Buat keluarga',exact=True).click()
            expect(page.get_by_role('heading',name='Catatan terbaru')).to_be_visible()
            page.get_by_role('button',name='Pengaturan',exact=True).click()
            expect(page.get_by_role('heading',name='Pengingat pribadi')).to_be_visible()
            page.get_by_role('button',name='Gunakan Alya untuk chat bot').click()
            expect(page.get_by_role('status').filter(has_text='Chat bot sekarang untuk Alya')).to_be_visible()
            page.get_by_label('Izinkan pengingat untuk saya').check()
            page.get_by_role('button',name='Simpan izin',exact=True).click()
            expect(page.get_by_label('Izinkan pengingat untuk saya')).to_be_checked()
            page.get_by_role('button',name='Tambah',exact=True).click()
            page.get_by_label('Jenis aktivitas').select_option('growth')
            page.get_by_label('Pengukuran',exact=True).select_option('weight')
            page.get_by_label('Nilai',exact=True).fill('4.2')
            with page.expect_response(lambda response: '/events-local' in response.url and response.request.method == 'POST') as saved:
                page.get_by_role('button',name='Simpan catatan',exact=True).click()
            assert saved.value.status == 201, saved.value.text()
            expect(page.get_by_role('heading',name='Timeline',exact=True)).to_be_visible()
            page.get_by_role('button',name='Pertumbuhan',exact=True).click()
            expect(page.get_by_role('img',name='Tren pengukuran; nilai lengkap tersedia di daftar')).to_be_visible()
            expect(page.get_by_text('Tren catatan asli',exact=False)).to_be_visible()
            page.keyboard.press('Tab')
            assert page.evaluate('document.activeElement.tagName') != 'BODY'
            assert not errors, errors
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), 'horizontal overflow'
            page.close()
            print('PASS real API mobile/desktop acceptance',width)
        browser.close()
finally:
    process.terminate()
    process.wait(timeout=10)
    with psycopg.connect(base,autocommit=True) as conn:
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
