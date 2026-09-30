import json
import logging
from pathlib import Path
import shutil
import subprocess
import threading
import time
from . import core
from .engine import ElevenLabsEngine, OronEngine, assemble

log = logging.getLogger(__name__)
engine = OronEngine()
eleven_engine = ElevenLabsEngine()
stop = threading.Event()

def run_job(job):
    payload = json.loads(job['payload'])
    folder = core.DATA / 'tmp' / job['id']
    folder.mkdir(exist_ok=True)
    output = core.DATA / 'outputs' / (job['id'] + '.wav')
    try:
        if job['voice_id'] == ElevenLabsEngine.builtin_id:
            selected_engine, reference, transcript = eleven_engine, None, None
        elif job['voice_id'].startswith('builtin-'):
            selected_engine = engine
            reference, transcript = engine.builtin(job['voice_id'])
        else:
            selected_engine = engine
            with core.db() as c:
                voice = c.execute('SELECT * FROM voices WHERE id=? AND user_id=?', (job['voice_id'],job['user_id'])).fetchone()
            if not voice:
                raise ValueError('Хоолой устгагдсан байна.')
            reference, transcript = core.DATA / 'voices' / (voice['id']+'.wav'), voice['transcript']
        cues = payload.get('cues')
        texts = [cue['text'] for cue in cues] if cues else core.chunks(payload['text'])
        parts = []
        for i, text in enumerate(texts):
            part = folder / f'{i}.wav'
            selected_engine.synthesize(text, reference, transcript, part, payload['speed'])
            parts.append(part)
            with core.db() as c:
                c.execute('UPDATE jobs SET progress=? WHERE id=?', (round((i+1)/len(texts)*90),job['id']))
        warnings = assemble(parts, output, cues)
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(output),'-codec:a','libmp3lame','-q:a','2',str(output.with_suffix('.mp3'))], check=True, timeout=120, capture_output=True)
        with core.db() as c:
            c.execute("UPDATE jobs SET status='done',progress=100,result=? WHERE id=?", (json.dumps({'warnings':warnings},ensure_ascii=False),job['id']))
    except Exception as exc:
        log.exception('Job %s failed',job['id'])
        output.unlink(missing_ok=True); output.with_suffix('.mp3').unlink(missing_ok=True)
        message = str(exc) if isinstance(exc, ValueError) else 'Дуу үүсгэж чадсангүй. Серверийн админд ажлын дугаарыг өгнө үү.'
        with core.db() as c:
            c.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (message,job['id']))
    finally:
        shutil.rmtree(folder, ignore_errors=True)

def loop():
    # Single worker process per data directory. Recover interrupted jobs durably.
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
    core.init(); logging.basicConfig(level=logging.INFO); loop()
