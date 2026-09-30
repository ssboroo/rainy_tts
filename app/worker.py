import json
import logging
import shutil
import subprocess
import threading
from . import core
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
        if job['voice_id'] != ElevenLabsEngine.builtin_id:
            raise ValueError('Одоогоор зөвхөн ElevenLabs Eleven v4 ашиглана.')
        cues = payload.get('cues')
        texts = [cue['text'] for cue in cues] if cues else core.chunks(payload['text'])
        parts = []
        for i, text in enumerate(texts):
            part = folder / f'{i}.wav'
            engine.synthesize(text, part, payload['speed'])
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
        message = str(exc) if isinstance(exc, ValueError) else 'Дуу үүсгэж чадсангүй. Серверийн админд ажлын дугаарыг өгнө үү.'
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
