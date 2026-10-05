"""Account lifecycle. Provider clone IDs remain in an operator cleanup queue.

Operators must delete pending provider voices in the ElevenLabs workspace, then
mark account_provider_cleanup.status='completed'; IDs are never reused as inputs
for automatic provider deletion. Billing rows remain linked to a tombstoned user.
"""
import hashlib
import logging
import json
import os
import re
from pathlib import Path
import secrets
import smtplib
from email.message import EmailMessage
import time
from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from . import core, billing

RESET_TTL=1800
GENERIC_RESET={'ok':True,'message':'Бүртгэлтэй имэйл бол нууц үг сэргээх холбоос илгээнэ.'}

def ensure_schema():
    with core.db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS account_reset_tokens(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires REAL NOT NULL,created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS account_reset_user ON account_reset_tokens(user_id);
        CREATE TABLE IF NOT EXISTS account_provider_cleanup(voice_id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),status TEXT NOT NULL DEFAULT 'pending',created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_bootstrap_applied(email TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,applied REAL NOT NULL);
        ''')

def bootstrap_admin():
    """Apply an operator-supplied hash once; never override later password changes."""
    email=os.getenv('ADMIN_BOOTSTRAP_EMAIL','').strip().lower()
    password_hash=os.getenv('ADMIN_BOOTSTRAP_PASSWORD_HASH','')
    if not email or not _admin(email) or not re.fullmatch(r'[0-9a-f]{32}:[0-9a-f]{128}',password_hash):
        return
    fingerprint=hashlib.sha256(password_hash.encode()).hexdigest()
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        applied=c.execute('SELECT fingerprint FROM admin_bootstrap_applied WHERE email=?',(email,)).fetchone()
        if applied and applied['fingerprint']==fingerprint:
            return
        row=c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
        if row:
            uid=row['id']
            c.execute('UPDATE users SET password=? WHERE id=?',(password_hash,uid))
            c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            c.execute('DELETE FROM account_reset_tokens WHERE user_id=?',(uid,))
        else:
            c.execute('INSERT INTO users VALUES(?,?,?,?)',(core.uid(),email,password_hash,time.time()))
        c.execute('INSERT OR REPLACE INTO admin_bootstrap_applied VALUES(?,?,?)',(email,fingerprint,time.time()))

def startup_accounts():
    ensure_schema()
    bootstrap_admin()

def email_configured():
    return bool(os.getenv('SMTP_HOST') and os.getenv('SMTP_FROM'))

def send_reset_email(email,token):
    origin=os.getenv('PUBLIC_ORIGIN','http://localhost:8080').rstrip('/')
    message=EmailMessage();message['From']=os.environ['SMTP_FROM'];message['To']=email
    message['Subject']='RAINY — нууц үг сэргээх'
    message.set_content(f'Нууц үгээ сэргээх холбоос (30 минут хүчинтэй):\n{origin}/?reset_token={token}\nХэрэв та хүсэлт гаргаагүй бол үл тооно уу.')
    tls=os.getenv('SMTP_TLS','true').strip().lower()
    transport=smtplib.SMTP_SSL if tls=='ssl' else smtplib.SMTP
    with transport(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','465' if tls=='ssl' else '587')),timeout=15) as smtp:
        if tls in {'true','1','yes','starttls'}: smtp.starttls()
        if os.getenv('SMTP_USER'): smtp.login(os.environ['SMTP_USER'],os.getenv('SMTP_PASSWORD',''))
        smtp.send_message(message)

def _deliver_reset(email,token):
    try:send_reset_email(email,token)
    except Exception:
        logging.warning('Account reset delivery failed')
        with core.db() as c:c.execute('DELETE FROM account_reset_tokens WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))

def _admin(email):
    return email.lower() in {x.strip().lower() for x in os.getenv('ADMIN_EMAILS','').split(',') if x.strip()}

async def _body(request):
    try: data=await request.json()
    except Exception: raise HTTPException(400,'JSON хүсэлт буруу байна.')
    if not isinstance(data,dict): raise HTTPException(400,'JSON хүсэлт буруу байна.')
    return data

def _password(data,key='new_password'):
    value=data.get(key,'')
    if not isinstance(value,str) or not 12<=len(value)<=128:
        raise HTTPException(422,'Нууц үг 12–128 тэмдэгттэй байна.')
    return value

def _verified(c,uid,password):
    row=c.execute('SELECT password FROM users WHERE id=?',(uid,)).fetchone()
    if not isinstance(password,str) or len(password)>128 or not row or not core.verify_password(password,row['password']):
        raise HTTPException(403,'Нууц үг буруу байна.')

def _signed_out(**payload):
    response=JSONResponse({'ok':True,**payload});response.delete_cookie('session',path='/');return response

def _safe_unlink(path):
    # Never follow a recorded path outside private storage, including symlinks.
    candidate=Path(path); root=core.DATA.resolve()
    if candidate.resolve().is_relative_to(root) and candidate.is_file():
        candidate.unlink(missing_ok=True)

def register_routes(app,session,mutation_guard,throttle):
    app.router.add_event_handler('startup',startup_accounts)
    @app.get('/api/account')
    def account(request:Request):
        sess=session(request)
        return {'id':sess['user_id'],'email':sess['email'],'email_configured':email_configured(),'admin':_admin(sess['email']),'admin_test':billing.admin_test_mode(sess['user_id'])}

    @app.post('/api/account/password')
    async def change_password(request:Request):
        sess=session(request);mutation_guard(request,sess);throttle('password:'+sess['user_id'],10,900)
        data=await _body(request);password=_password(data)
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE');_verified(c,sess['user_id'],data.get('current_password'))
            c.execute('UPDATE users SET password=? WHERE id=?',(core.hash_password(password),sess['user_id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(sess['user_id'],));c.execute('DELETE FROM account_reset_tokens WHERE user_id=?',(sess['user_id'],))
        return _signed_out()

    @app.post('/api/account/reset/request')
    async def reset_request(request:Request,background_tasks:BackgroundTasks):
        mutation_guard(request);throttle('reset:'+request.client.host,5,900)
        data=await _body(request);email=str(data.get('email','')).strip().lower()[:320]
        if not email_configured():
            raise HTTPException(503,'Нууц үг сэргээх имэйл илгээх үйлчилгээ одоогоор бэлэн биш байна. Тусламж авахын тулд админд хандана уу.')
        if email_configured():
            token=secrets.token_urlsafe(32);now=time.time()
            with core.db() as c:
                row=c.execute("SELECT id FROM users WHERE email=? AND email NOT LIKE '%@deleted.invalid'",(email,)).fetchone()
                if row:
                    c.execute('DELETE FROM account_reset_tokens WHERE user_id=? OR expires<?',(row['id'],now))
                    c.execute('INSERT INTO account_reset_tokens VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],now+RESET_TTL,now))
            if row:background_tasks.add_task(_deliver_reset,email,token)
        return GENERIC_RESET

    @app.post('/api/account/reset/confirm')
    async def reset_confirm(request:Request):
        mutation_guard(request);throttle('reset-confirm:'+request.client.host,10,900)
        data=await _body(request);password=_password(data);token=data.get('token','')
        if not isinstance(token,str) or len(token)>256:raise HTTPException(400,'Сэргээх холбоос хүчингүй эсвэл хугацаа дууссан.')
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT user_id FROM account_reset_tokens WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if not row:raise HTTPException(400,'Сэргээх холбоос хүчингүй эсвэл хугацаа дууссан.')
            c.execute('UPDATE users SET password=? WHERE id=?',(core.hash_password(password),row['user_id']))
            c.execute('DELETE FROM account_reset_tokens WHERE user_id=?',(row['user_id'],));c.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
        return _signed_out()

    @app.post('/api/account/delete')
    async def delete_account(request:Request):
        sess=session(request);mutation_guard(request,sess);throttle('delete-account:'+sess['user_id'],5,900)
        data=await _body(request)
        if data.get('confirmation')!='УСТГАХ':raise HTTPException(422,'Баталгаажуулахын тулд УСТГАХ гэж бичнэ үү.')
        uid=sess['user_id'];paths=[]
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE');_verified(c,uid,data.get('password'))
            for table in ('jobs','tool_jobs'):
                if c.execute(f"SELECT 1 FROM {table} WHERE user_id=? AND status NOT IN ('done','completed','failed','cancelled') LIMIT 1",(uid,)).fetchone():
                    raise HTTPException(409,'Ажиллаж байгаа хүсэлт дууссаны дараа бүртгэлээ устгана уу.')
            paths.extend(r['path'] for r in c.execute('SELECT path FROM artifacts WHERE user_id=?',(uid,)))
            if c.execute("SELECT 1 FROM pvc_voices WHERE user_id=? AND status IN ('queued','processing','training','running') LIMIT 1",(uid,)).fetchone():
                raise HTTPException(409,'Хоолойн сургалт дууссаны дараа бүртгэлээ устгана уу.')
            for row in c.execute('SELECT payload FROM tool_jobs WHERE user_id=?',(uid,)):
                try: payload=json.loads(row['payload'])
                except (ValueError,TypeError): payload={}
                if isinstance(payload,dict) and isinstance(payload.get('source_path'),str):paths.append(payload['source_path'])
            jobs=c.execute('SELECT id FROM jobs WHERE user_id=?',(uid,)).fetchall()
            for row in jobs:
                if all(ch in '0123456789abcdef' for ch in row['id']):
                    paths.extend(str(core.DATA/'outputs'/f"{row['id']}.{ext}") for ext in ('wav','mp3'))
                    folder=core.DATA/'tmp'/row['id']
                    if folder.is_dir() and not folder.is_symlink():
                        paths.extend(str(p) for p in folder.rglob('*') if p.is_file())
            protected={Path(r['path']).resolve() for r in c.execute('SELECT path FROM artifacts WHERE user_id!=?',(uid,))}
            paths=[path for path in paths if Path(path).resolve() not in protected]
            # Save owned provider IDs before removing customer voice metadata.
            for table in ('voices','pvc_voices'):
                for row in c.execute(f'SELECT id FROM {table} WHERE user_id=?',(uid,)).fetchall():
                    c.execute("INSERT OR IGNORE INTO account_provider_cleanup(voice_id,user_id,created) VALUES(?,?,?)",(row['id'],uid,time.time()))
            for table in ('sessions','account_reset_tokens','artifacts','tool_jobs','jobs','voices','pvc_voices','reception_events','reception_integrations'):
                c.execute(f'DELETE FROM {table} WHERE user_id=?',(uid,))
            c.execute("UPDATE users SET email=?,password=? WHERE id=?",(core.uid()+'@deleted.invalid',core.hash_password(secrets.token_urlsafe(48)),uid))
            c.execute("UPDATE subscriptions SET status='cancelled',auto_renew=0 WHERE user_id=?",(uid,))
            c.execute("UPDATE provider_usage SET metadata='{}' WHERE user_id=?",(uid,))
            c.execute("UPDATE credit_ledger SET metadata='{}' WHERE user_id=?",(uid,))
        for path in paths:
            try:_safe_unlink(path)
            except OSError:logging.warning('Deleted account artifact cleanup requires operator attention')
        return _signed_out(provider_cleanup='operator_pending')

    @app.get('/api/admin/overview')
    def overview(request:Request):
        sess=session(request)
        if not _admin(sess['email']):raise HTTPException(403,'Admin эрх шаардлагатай.')
        with core.db() as c:
            counts={table:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('users','jobs','tool_jobs','artifacts')}
            statuses={table:{r['status']:r['count'] for r in c.execute(f'SELECT status,COUNT(*) count FROM {table} GROUP BY status')} for table in ('jobs','tool_jobs')}
            usage=dict(c.execute('SELECT COUNT(*) requests,COALESCE(SUM(provider_cost),0) modeled_provider_cost FROM provider_usage').fetchone())
            pending=c.execute("SELECT COUNT(*) FROM account_provider_cleanup WHERE status='pending'").fetchone()[0]
        from . import operations
        return {'readiness':operations.inspect_readiness(),'counts':counts,'job_statuses':statuses,'provider_usage':usage,'provider_cleanup_pending':pending,'email_configured':email_configured()}
