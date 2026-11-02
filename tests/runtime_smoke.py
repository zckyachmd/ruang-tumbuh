"""Docker persistence and pg_dump/restore acceptance with synthetic data only."""
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path
import stat
import urllib.request
from datetime import datetime, timezone

project='ruang-check-'+secrets.token_hex(4)
env=dict(os.environ,APP_ENV='development',DEV_AUTH_ENABLED='1',APP_PORT='8147',POSTGRES_PASSWORD='synthetic-only')
command=['docker','compose','-p',project]


def run(*args, input=None):
    return subprocess.run([*command,*args],env=env,input=input,check=True,capture_output=True).stdout


def api(path,body=None,token=None,key=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    if key:headers['Idempotency-Key']=key
    request=urllib.request.Request('http://127.0.0.1:8147'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)


try:
    run('up','-d','--build','--wait','--wait-timeout','120')
    token=api('/api/dev/session',{'user_id':8347})['token']
    family=api('/api/families',{'name':'Synthetic runtime','nickname':'Alya'},token)
    path=f"/api/families/{family['family_id']}/children/{family['child_id']}/events"
    api(path,[{'kind':'note','payload':{'text':'synthetic restore fixture'},'occurred_at':datetime.now(timezone.utc).isoformat()}],token,'runtime-fixture')
    run('up','-d','--force-recreate','--wait','--wait-timeout','120','api','worker')
    assert api(path,token=token)[0]['payload']['text']=='synthetic restore fixture'
    with tempfile.TemporaryDirectory(prefix='ruang-backup-test-') as temporary:
        key=Path(temporary)/'key.txt'
        subprocess.run(['age-keygen','-o',str(key)],check=True,capture_output=True)
        public=subprocess.run(['age-keygen','-y',str(key)],check=True,capture_output=True,text=True).stdout.strip()
        backup_env=dict(env,COMPOSE_PROJECT_NAME=project,BACKUP_DIR=str(Path(temporary)/'backups'),BACKUP_AGE_RECIPIENT=public)
        subprocess.run(['bash','scripts/backup-postgres.sh'],env=backup_env,check=True,capture_output=True)
        files=list((Path(temporary)/'backups').glob('*.dump.age'))
        assert len(files)==1
        assert stat.S_IMODE(files[0].stat().st_mode)==0o600
        assert b'synthetic restore fixture' not in files[0].read_bytes()
        dump=subprocess.run(['age','--decrypt','-i',str(key),str(files[0])],check=True,capture_output=True).stdout
    run('exec','-T','db','createdb','-U','ruang','restored')
    run('exec','-T','db','pg_restore','-U','ruang','-d','restored','--no-owner','--no-acl',input=dump)
    before=run('exec','-T','db','psql','-U','ruang','-d','ruang','-Atc','SELECT payload::text FROM events ORDER BY id')
    after=run('exec','-T','db','psql','-U','ruang','-d','restored','-Atc','SELECT payload::text FROM events ORDER BY id')
    assert before==after
    assert b'synthetic restore fixture' not in dump
    print('PASS container recreate persistence and actual age backup script/restore (ciphertext mode 0600)')
finally:
    run('down','-v','--remove-orphans')
