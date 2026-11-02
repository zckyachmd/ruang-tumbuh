"""Docker persistence and pg_dump/restore acceptance with synthetic data only."""
import json
import os
import secrets
import subprocess
import tempfile
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
    dump=run('exec','-T','db','pg_dump','-U','ruang','-d','ruang','-Fc','--no-owner','--no-acl')
    run('exec','-T','db','createdb','-U','ruang','restored')
    run('exec','-T','db','pg_restore','-U','ruang','-d','restored','--no-owner','--no-acl',input=dump)
    before=run('exec','-T','db','psql','-U','ruang','-d','ruang','-Atc','SELECT payload::text FROM events ORDER BY id')
    after=run('exec','-T','db','psql','-U','ruang','-d','restored','-Atc','SELECT payload::text FROM events ORDER BY id')
    assert before==after
    assert b'synthetic restore fixture' not in dump
    print('PASS container recreate persistence and PostgreSQL encrypted-column backup/restore')
finally:
    run('down','-v','--remove-orphans')
