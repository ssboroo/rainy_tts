"""Persistence, Mongolian text preparation and strict subtitle parsing."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata

DATA = Path(os.getenv('DATA_DIR', './data')).resolve()

@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / 'studio.db', timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        with con:
            yield con
    finally:
        con.close()

def init():
    for directory in ('voices', 'outputs', 'tmp', 'artifacts'):
        (DATA / directory).mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS voices(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),name TEXT NOT NULL,transcript TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),voice_id TEXT NOT NULL,title TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,progress INTEGER DEFAULT 0,error TEXT,created REAL NOT NULL,result TEXT);
        CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,created);
        CREATE TABLE IF NOT EXISTS voice_aliases(
            source_id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            name TEXT NOT NULL,
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS voice_rates(
            source_id TEXT PRIMARY KEY,
            multiplier REAL NOT NULL DEFAULT 1,
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tool_jobs(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            tool_type TEXT NOT NULL,
            title TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            error TEXT,
            result TEXT,
            created REAL NOT NULL,
            updated REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS tool_jobs_user ON tool_jobs(user_id,created DESC);
        CREATE TABLE IF NOT EXISTS artifacts(
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES tool_jobs(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL,
            filename TEXT NOT NULL,
            mime TEXT NOT NULL,
            path TEXT NOT NULL,
            created REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS artifacts_job ON artifacts(job_id,created);
        CREATE TABLE IF NOT EXISTS credit_wallets(
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            balance INTEGER NOT NULL DEFAULT 0,
            lifetime_in INTEGER NOT NULL DEFAULT 0,
            lifetime_out INTEGER NOT NULL DEFAULT 0,
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS subscriptions(
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            plan_id TEXT NOT NULL,
            status TEXT NOT NULL,
            cycle_start REAL NOT NULL,
            cycle_end REAL NOT NULL,
            monthly_credits INTEGER NOT NULL,
            auto_renew INTEGER NOT NULL DEFAULT 0,
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS credit_ledger(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            tool_type TEXT,
            reference TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS credit_ledger_user ON credit_ledger(user_id,created DESC);
        CREATE TABLE IF NOT EXISTS billing_orders(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            plan_id TEXT NOT NULL,
            amount_mnt INTEGER NOT NULL,
            status TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_ref TEXT,
            created REAL NOT NULL,
            paid_at REAL
        );
        CREATE TABLE IF NOT EXISTS billing_order_quotes(order_id TEXT PRIMARY KEY REFERENCES billing_orders(id) ON DELETE CASCADE,credits INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS billing_orders_user ON billing_orders(user_id,created DESC);
        CREATE TABLE IF NOT EXISTS wire_payments(
            order_id TEXT PRIMARY KEY REFERENCES billing_orders(id) ON DELETE CASCADE,
            payment_intent_id TEXT,
            checkout_session_id TEXT,
            checkout_url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            updated REAL NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS wire_payment_intent_unique ON wire_payments(payment_intent_id) WHERE payment_intent_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS wire_webhook_events(
            event_key TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            payment_intent_id TEXT,
            created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pvc_voices(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'mn',
            status TEXT NOT NULL DEFAULT 'draft',
            metadata TEXT NOT NULL DEFAULT '{}',
            created REAL NOT NULL,
            updated REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS pvc_voices_user ON pvc_voices(user_id,created DESC);
        CREATE TABLE IF NOT EXISTS provider_account_snapshot(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS provider_usage(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id TEXT,
            product TEXT NOT NULL,
            provider_cost REAL,
            request_id TEXT,
            trace_id TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS provider_usage_user ON provider_usage(user_id,created DESC);
        CREATE TABLE IF NOT EXISTS reception_integrations(
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            token TEXT UNIQUE NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created REAL NOT NULL,
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reception_events(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tool_name TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            created REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS reception_events_user ON reception_events(user_id,created DESC);
        ''')

def uid():
    return secrets.token_hex(16)

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + digest.hex()

def verify_password(password, stored):
    salt, expected = stored.split(':')
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)

DIGITS = ['тэг', 'нэг', 'хоёр', 'гурав', 'дөрөв', 'тав', 'зургаа', 'долоо', 'найм', 'ес']

def prepare_text(text, glossary=None):
    text = unicodedata.normalize('NFC', text).strip()
    if not text or len(text) > 12000:
        raise ValueError('Текст 1–12000 тэмдэгттэй байна.')
    for source, target in sorted((glossary or {}).items(), key=lambda x: -len(x[0])):
        if not source or not target or len(source) > 100 or len(target) > 200:
            raise ValueError('Дуудлагын толь буруу байна.')
        text = re.sub(re.escape(source), lambda _: target, text, flags=re.I)
    # ElevenLabs v4 can handle mixed Mongolian/Latin text and numbers.
    # Keep a conservative character allow-list to reject emoji/control-like input,
    # while allowing common names, brands, URLs, prices and abbreviations.
    if re.search(r'[^А-Яа-яӨөҮүЁёA-Za-z0-9\u00C0-\u02FF\s.,!?…:;\-—_«»“”"()\[\]{}\u2019\u0027/@#&+*=₮$€%]', text):
        raise ValueError('Дэмжигдээгүй тэмдэгт байна.')
    return re.sub(r'\s+', ' ', text)

def chunks(text, limit=240):
    words = text.split()
    result, current = [], ''
    for word in words:
        if len(word) > limit:
            raise ValueError('Хэт урт тасралтгүй үг байна.')
        if current and len(current) + len(word) + 1 > limit:
            result.append(current)
            current = ''
        current = (current + ' ' + word).strip()
    if current:
        result.append(current)
    return result

def parse_srt(raw):
    def timestamp(value):
        match = re.fullmatch(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', value)
        if not match:
            raise ValueError('SRT хугацааны формат буруу байна.')
        h, m, s, ms = map(int, match.groups())
        if m > 59 or s > 59:
            raise ValueError('SRT хугацаа буруу байна.')
        return h * 3600 + m * 60 + s + ms / 1000
    cues, previous = [], 0
    for block in re.split(r'\n\s*\n', raw.lstrip('\ufeff').strip().replace('\r', '')):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].isdigit() or ' --> ' not in lines[1]:
            raise ValueError('SRT бүтэц буруу байна.')
        start, end = map(timestamp, lines[1].split(' --> '))
        if start < previous or end <= start or end > 3600:
            raise ValueError('Давхцсан эсвэл нэг цагаас урт SRT дэмжихгүй.')
        cues.append({'start': start, 'end': end, 'text': ' '.join(lines[2:])})
        previous = end
    if not cues or len(cues) > 200:
        raise ValueError('SRT нь 1–200 репликтэй байна.')
    return cues

def public_job(row):
    return {k: row[k] for k in ('id','title','status','progress','error','created','result')}


def create_tool_job(user_id, tool_type, title, payload=None, status='running', job_id=None):
    job_id = job_id or uid()
    now = time.time()
    with db() as c:
        c.execute(
            'INSERT INTO tool_jobs(id,user_id,tool_type,title,payload,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
            (job_id,user_id,tool_type,title[:100] or tool_type,json.dumps(payload or {},ensure_ascii=False),status,now,now)
        )
    return job_id

def update_tool_job(job_id, status=None, result=None, error=None):
    fields, values = ['updated=?'], [time.time()]
    if status is not None:
        fields.append('status=?'); values.append(status)
    if result is not None:
        fields.append('result=?'); values.append(json.dumps(result,ensure_ascii=False))
    if error is not None:
        fields.append('error=?'); values.append(str(error)[:1000])
    values.append(job_id)
    with db() as c:
        c.execute('UPDATE tool_jobs SET '+','.join(fields)+' WHERE id=?', values)

def add_artifact(job_id, user_id, kind, filename, mime, path):
    artifact_id = uid()
    with db() as c:
        c.execute(
            'INSERT INTO artifacts(id,job_id,user_id,kind,filename,mime,path,created) VALUES(?,?,?,?,?,?,?,?)',
            (artifact_id,job_id,user_id,kind,filename,mime,str(path),time.time())
        )
    return artifact_id


def add_provider_usage(user_id, job_id, product, provider_cost=None, request_id=None, trace_id=None, metadata=None):
    with db() as c:
        c.execute(
            'INSERT INTO provider_usage(id,user_id,job_id,product,provider_cost,request_id,trace_id,metadata,created) VALUES(?,?,?,?,?,?,?,?,?)',
            (uid(),user_id,job_id,product,provider_cost,request_id,trace_id,json.dumps(metadata or {},ensure_ascii=False),time.time())
        )

def public_tool_job(row):
    data={k:row[k] for k in ('id','tool_type','title','status','error','created','updated')}
    try:
        data['result']=json.loads(row['result']) if row['result'] else None
    except (TypeError,json.JSONDecodeError):
        data['result']=None
    return data

def tool_artifacts(job_id, user_id):
    with db() as c:
        rows=c.execute(
            'SELECT id,kind,filename,mime,created FROM artifacts WHERE job_id=? AND user_id=? ORDER BY created',
            (job_id,user_id)
        ).fetchall()
    return [dict(row) for row in rows]
