"""Durable, user-scoped creative work with atomic credit reservations."""
import json
import logging
from pathlib import Path
import time
from fastapi import UploadFile
from starlette.datastructures import Headers
from . import billing, core
from .eleven_tools import ElevenAPIError

METHODS = {'music', 'dialogue', 'sound_effect', 'voice_changer', 'voice_isolator', 'speech_to_text', 'forced_alignment'}


def ensure_schema():
    with core.db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS durable_jobs(
            job_id TEXT PRIMARY KEY REFERENCES tool_jobs(id) ON DELETE CASCADE,
            execution TEXT NOT NULL, charge_id TEXT, credits INTEGER NOT NULL,
            filename TEXT NOT NULL, mime TEXT NOT NULL, upload_path TEXT,
            upload_name TEXT, upload_mime TEXT)''')


def enqueue(user_id, tool_type, title, execution, filename, mime, credits,
            upload_path=None, upload_name=None, upload_mime=None):
    if execution.get('method') not in METHODS or not isinstance(execution.get('args'), list):
        raise ValueError('Ажлын төрөл буруу байна.')
    ensure_schema()
    billing.ensure_wallet(user_id)
    billing._expire_if_needed(user_id)
    job_id, now = core.uid(), time.time()
    credits = max(0, int(credits)) if billing.billing_enabled() else 0
    with core.db() as db:
        db.execute('BEGIN IMMEDIATE')
        user=db.execute('SELECT email FROM users WHERE id=?',(user_id,)).fetchone()
        if not user or user['email'].endswith('@deleted.invalid'):
            raise ValueError('Аккаунт идэвхгүй байна.')
        active = db.execute("SELECT COUNT(*) FROM tool_jobs WHERE user_id=? AND status IN ('queued','running')", (user_id,)).fetchone()[0]
        if active >= 3:
            raise ValueError('Зэрэг 3-аас олон аудио ажил үүсгэхгүй.')
        wallet = db.execute('SELECT balance FROM credit_wallets WHERE user_id=?', (user_id,)).fetchone()
        if credits > wallet['balance']:
            raise ValueError(f"Credit хүрэлцэхгүй байна. Шаардлагатай: {credits}, үлдэгдэл: {wallet['balance']}.")
        charge_id = core.uid() if credits else None
        if credits:
            balance = wallet['balance'] - credits
            db.execute('UPDATE credit_wallets SET balance=?,lifetime_out=lifetime_out+?,updated=? WHERE user_id=?', (balance, credits, now, user_id))
            db.execute('INSERT INTO credit_ledger VALUES(?,?,?,?,?,?,?,?,?)',
                       (charge_id, user_id, 'usage', -credits, balance, tool_type, job_id, json.dumps({'title': title}), now))
        payload = {'billing': {'charge_id': charge_id, 'credits': credits}, 'source_path': str(upload_path) if upload_path else None}
        db.execute('INSERT INTO tool_jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (job_id, user_id, tool_type, title[:100], json.dumps(payload), 'queued', None, None, now, now))
        # Named columns above intentionally match core's schema; execution is private.
        db.execute('INSERT INTO durable_jobs VALUES(?,?,?,?,?,?,?,?,?)',
                   (job_id, json.dumps(execution, ensure_ascii=False), charge_id, credits, filename, mime,
                    str(upload_path) if upload_path else None, upload_name, upload_mime))
    return job_id


def claim_next():
    ensure_schema()
    with core.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT t.*,d.execution,d.charge_id,d.credits,d.filename,d.mime,d.upload_path,d.upload_name,d.upload_mime FROM tool_jobs t JOIN durable_jobs d ON d.job_id=t.id WHERE t.status='queued' ORDER BY t.created LIMIT 1").fetchone()
        if row:
            db.execute("UPDATE tool_jobs SET status='running',updated=? WHERE id=?", (time.time(), row['id']))
        return dict(row) if row else None


def recover_interrupted():
    ensure_schema()
    with core.db() as db:
        count=db.execute("UPDATE tool_jobs SET status='failed',error=?,updated=? WHERE status='running' AND id IN (SELECT job_id FROM durable_jobs)",
                         ('Сервер дахин ассан. Давхар төлбөрөөс сэргийлж ажлыг дахин илгээгээгүй. Хэрэглээг админ шалгана.', time.time())).rowcount
    return count


def cancel(job_id, user_id):
    with core.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT t.status,d.charge_id,d.upload_path FROM tool_jobs t JOIN durable_jobs d ON d.job_id=t.id WHERE t.id=? AND t.user_id=?',(job_id,user_id)).fetchone()
        if not row: raise ValueError('Ажил олдсонгүй.')
        if row['status']=='cancelled': return False
        if row['status']!='queued': raise ValueError('Ажил эхэлсэн тул одоо цуцлах боломжгүй.')
        db.execute("UPDATE tool_jobs SET status='cancelled',updated=? WHERE id=?",(time.time(),job_id))
    billing.refund(user_id,row['charge_id'],'queued_cancelled')
    if row['upload_path']:
        Path(row['upload_path']).unlink(missing_ok=True)
    return True


def reconcile_cancelled():
    with core.db() as db:
        rows=db.execute("SELECT t.user_id,d.charge_id FROM tool_jobs t JOIN durable_jobs d ON d.job_id=t.id WHERE t.status='cancelled'").fetchall()
    for row in rows: billing.refund(row['user_id'],row['charge_id'],'queued_cancelled')


async def execute(job):
    from . import server
    upload=None
    provider_succeeded=False
    try:
        execution=json.loads(job['execution'])
        method=execution['method']
        if method not in METHODS: raise ValueError('Ажлын төрөл буруу байна.')
        args=execution['args']
        if job.get('upload_path'):
            path=Path(job['upload_path']).resolve()
            if not path.is_relative_to((core.DATA/'tmp').resolve()):
                raise ValueError('Аудио файлын байрлал буруу байна.')
            upload=UploadFile(filename=job['upload_name'],file=path.open('rb'),headers=Headers({'content-type':job['upload_mime'] or 'audio/mpeg'}))
            args=[upload]+args
        if method=='forced_alignment':
            from .audio_extensions import execute_alignment
            result=await execute_alignment(job['user_id'],job['id'],*args)
            core.update_tool_job(job['id'],'done',result=result)
            return
        raw=await getattr(server.tools,method)(*args)
        provider_succeeded=True
        if method=='speech_to_text':
            result=server.save_transcript_result(job['user_id'],job['id'],raw,job['credits'],execution.get('keyterms_count',0))
        else:
            data,meta=raw if isinstance(raw,tuple) else (raw,{})
            if not isinstance(data,bytes) or not data:
                raise ValueError('Аудио хариу хоосон эсвэл буруу байна.')
            mime=meta.get('mime') or job['mime']
            filename=job['filename']
            if method=='voice_isolator':
                suffix={'audio/wav':'.wav','audio/flac':'.flac','audio/ogg':'.ogg'}.get(mime,'.mp3')
                filename='rainy-isolated-voice'+suffix
            artifact=server.create_artifact_bytes(job['user_id'],job['id'],'audio',filename,mime,data)
            result={'artifact_id':artifact,'credits_used':job['credits']}
            if meta:
                core.add_provider_usage(job['user_id'],job['id'],job['tool_type'],request_id=meta.get('request_id'),trace_id=meta.get('trace_id'),metadata=meta)
                result['provider_usage']=meta
        core.update_tool_job(job['id'],'done',result=result)
    except Exception as exc:
        # A timeout after submission can mean the provider generated and billed it.
        import httpx
        uncertain=provider_succeeded or isinstance(exc,(httpx.TimeoutException,httpx.NetworkError)) or bool(getattr(exc,'useful_output',False)) or (getattr(exc,'status_code',getattr(exc,'status',0)) or 0)>=500
        if not uncertain: billing.refund(job['user_id'],job['charge_id'],'provider_failed')
        error=str(exc)[:500] if isinstance(exc,(ElevenAPIError,ValueError)) else 'Аудио ажил амжилтгүй боллоо.'
        if uncertain: error='Үйлчилгээний хариу тасарсан. Давхар үүсгэлт хийхээс өмнө хэрэглээг админ шалгана.'
        core.update_tool_job(job['id'],'failed',error=error)
        logging.getLogger(__name__).warning('Creative job %s failed (%s)',job['id'],type(exc).__name__)
    finally:
        if upload: await upload.close()
        if job.get('upload_path'): Path(job['upload_path']).unlink(missing_ok=True)
