import json
import logging
import shutil
import subprocess
import threading
from . import core, billing
from .engine import ElevenLabsEngine, assemble

log = logging.getLogger(__name__)
engine = ElevenLabsEngine()
stop = threading.Event()

def run_job(job):
    payload = json.loads(job['payload'])
    folder = core.DATA / 'tmp' / job['id']
    folder.mkdir(exist_ok=True)
    output = core.DATA / 'outputs' / (job['id'] + '.wav')
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
        texts = [cue['text'] for cue in cues] if cues else core.chunks(payload['text'])
        parts = []
        for i, text in enumerate(texts):
            part = folder / f'{i}.wav'
            engine.synthesize(text, part, payload['speed'], resolved_voice_id, trusted_voice=True)
            parts.append(part)
            with core.db() as c:
                c.execute('UPDATE jobs SET progress=? WHERE id=?', (round((i+1)/len(texts)*90),job['id']))
        warnings = assemble(parts, output, cues)
        subprocess.run(
            ['ffmpeg','-nostdin','-v','error','-y','-i',str(output),'-codec:a','libmp3lame','-q:a','2',str(output.with_suffix('.mp3'))],
            check=True, timeout=120, capture_output=True
        )
        with core.db() as c:
            c.execute("UPDATE jobs SET status='done',progress=100,result=? WHERE id=?", (json.dumps({'warnings':warnings},ensure_ascii=False),job['id']))
    except Exception as exc:
        log.exception('Job %s failed',job['id'])
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
        billing.refund(job['user_id'],billing_info.get('charge_id'),'tts_failed')
        with core.db() as c:
            c.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (message,job['id']))
    finally:
        shutil.rmtree(folder, ignore_errors=True)

def loop():
    with core.db() as c:
        c.execute("UPDATE jobs SET status='queued',progress=0 WHERE status='running'")
    while not stop.is_set():
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE')
            job = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if job:
                c.execute("UPDATE jobs SET status='running' WHERE id=?",(job['id'],))
        if job:
            run_job(job)
        else:
            stop.wait(1)

if __name__ == '__main__':
    core.init()
    logging.basicConfig(level=logging.INFO)
    loop()
