import json
import asyncio
import time
import logging
import shutil
import subprocess
import threading
from . import core, billing, durable_jobs
from .engine import ElevenLabsEngine, assemble
from .voice_direction import segments

log = logging.getLogger(__name__)
engine = ElevenLabsEngine()
stop = threading.Event()

def run_job(job):
    payload = json.loads(job['payload'])
    folder = core.DATA / 'tmp' / job['id']
    folder.mkdir(exist_ok=True)
    output = core.DATA / 'outputs' / (job['id'] + '.wav')
    parts = []
    try:
        resolved_voice_id = payload.get('provider_voice_id')
        if not resolved_voice_id:
            resolved_voice_id = ElevenLabsEngine.resolve_voice_id(job['voice_id'])
        if not resolved_voice_id:
            with core.db() as c:
                alias = c.execute('SELECT provider_id FROM voice_aliases WHERE source_id=?',(job['voice_id'],)).fetchone()
                custom = c.execute('SELECT 1 FROM voices WHERE id=? AND user_id=?',(job['voice_id'],job['user_id'])).fetchone()
            if alias:
                resolved_voice_id = alias['provider_id']
            elif custom:
                resolved_voice_id = job['voice_id']
        if not resolved_voice_id:
            raise ValueError('Сонгосон ElevenLabs voice workspace-д sync хийгдээгүй байна.')
        cues = payload.get('cues')
        texts = segments(payload)
        parts = []
        provider_meta=[]
        model_id=(payload.get('billing') or {}).get('model_id') or payload.get('model_id') or engine.model_id
        for i, text in enumerate(texts):
            part = folder / f'{i}.wav'
            continuity={}
            if i: continuity['previous_text']=texts[i-1]
            if i+1<len(texts): continuity['next_text']=texts[i+1]
            meta=engine.synthesize(
                text, part, payload['speed'], resolved_voice_id,
                trusted_voice=True, model_id=model_id,
                **continuity
            ) or {}
            provider_meta.append(meta)
            parts.append(part)
            with core.db() as c:
                c.execute('UPDATE jobs SET progress=? WHERE id=?', (round((i+1)/len(texts)*90),job['id']))
        warnings = assemble(parts, output, cues)
        subprocess.run(
            ['ffmpeg','-nostdin','-v','error','-y','-i',str(output),'-codec:a','libmp3lame','-q:a','2',str(output.with_suffix('.mp3'))],
            check=True, timeout=120, capture_output=True
        )
        char_cost=0.0
        request_ids=[]; trace_ids=[]
        for meta in provider_meta:
            try:
                if meta.get('character_cost') not in (None,''):
                    char_cost+=float(meta['character_cost'])
            except (TypeError,ValueError):
                pass
            if meta.get('request_id'): request_ids.append(meta['request_id'])
            if meta.get('trace_id'): trace_ids.append(meta['trace_id'])
        usage_meta={
            'model_id':model_id,
            'character_cost':char_cost if char_cost else None,
            'request_ids':request_ids,
            'trace_ids':trace_ids,
            'segments':len(provider_meta),
        }
        core.add_provider_usage(
            job['user_id'],job['id'],'text_to_speech',
            request_id=request_ids[0] if request_ids else None,
            trace_id=trace_ids[0] if trace_ids else None,
            metadata=usage_meta
        )
        result={'warnings':warnings,'provider_usage':usage_meta}
        with core.db() as c:
            c.execute("UPDATE jobs SET status='done',progress=100,result=? WHERE id=?", (json.dumps(result,ensure_ascii=False),job['id']))
    except Exception as exc:
        log.warning('TTS job %s failed (%s)',job['id'],type(exc).__name__)
        output.unlink(missing_ok=True)
        output.with_suffix('.mp3').unlink(missing_ok=True)
        if isinstance(exc,(ValueError,RuntimeError)):
            message=str(exc)[:500]
        elif isinstance(exc,FileNotFoundError):
            message='FFmpeg олдсонгүй. FFmpeg суулгаж worker-ээ restart хийнэ үү.'
        elif isinstance(exc,subprocess.CalledProcessError):
            message='FFmpeg аудио боловсруулах үед алдаа гарлаа.'
        else:
            message='Дуу үүсгэж чадсангүй. Worker terminal дээрх log-ийг шалгана уу.'
        billing_info=payload.get('billing') or {}
        import httpx
        cause=exc; uncertain=bool(parts)
        while cause:
            uncertain=uncertain or isinstance(cause,(httpx.TimeoutException,httpx.NetworkError)) or (getattr(cause,'status_code',getattr(cause,'status',0)) or 0)>=500
            cause=cause.__cause__
        if not uncertain:
            billing.refund(job['user_id'],billing_info.get('charge_id'),'tts_failed')
        else:
            message='Үүсгэлтийн хариу тасарсан. Давхар төлбөрөөс сэргийлж дахин илгээгээгүй. Хэрэглээг админ шалгана.'
        with core.db() as c:
            c.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (message,job['id']))
    finally:
        shutil.rmtree(folder, ignore_errors=True)

def heartbeat():
    while not stop.is_set():
        (core.DATA/'worker-heartbeat').write_text(str(time.time()))
        stop.wait(15)

def loop():
    durable_jobs.ensure_schema()
    durable_jobs.recover_interrupted()
    durable_jobs.reconcile_cancelled()
    from . import realtime_proxy
    realtime_proxy.reconcile_unused()
    last_reconcile=time.monotonic()
    threading.Thread(target=heartbeat,daemon=True).start()
    with core.db() as c:
        c.execute("UPDATE jobs SET status='failed',error=? WHERE status='running'",('Сервер дахин ассан. Давхар үүсгэлтээс сэргийлж дахин илгээгээгүй. Хэрэглээг админ шалгана.',))
    while not stop.is_set():
        if time.monotonic()-last_reconcile>=60:
            realtime_proxy.reconcile_unused()
            last_reconcile=time.monotonic()
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE')
            job = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if job:
                c.execute("UPDATE jobs SET status='running' WHERE id=?",(job['id'],))
        if job:
            run_job(job)
        if stop.is_set(): break
        creative=durable_jobs.claim_next()
        if creative:
            asyncio.run(durable_jobs.execute(creative))
        if not job and not creative:
            stop.wait(1)

if __name__ == '__main__':
    core.init()
    logging.basicConfig(level=logging.INFO)
    loop()
