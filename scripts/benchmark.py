"""Real local CPU inference smoke test; no mock provider."""
import json
import os
from pathlib import Path
import platform
import sys
import time
import wave
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine import OronEngine

engine = OronEngine()
ready, reason = engine.readiness()
if not ready:
    raise SystemExit(reason)
output = Path(os.getenv('BENCHMARK_OUTPUT', './data/benchmark.wav'))
output.parent.mkdir(parents=True, exist_ok=True)
reference, transcript = engine.builtin('builtin-female')
started = time.perf_counter()
engine.synthesize('Сайн байна уу. Өнөөдөр сайхан өдөр байна.', reference, transcript, output)
elapsed = time.perf_counter() - started
with wave.open(str(output)) as audio:
    seconds = audio.getnframes() / audio.getframerate()
report = {'engine':'Oron/F5-TTS','device':'cpu','python':platform.python_version(),
          'generation_seconds':round(elapsed,3),'audio_seconds':round(seconds,3),
          'real_time_factor':round(elapsed/seconds,3),'human_quality_review':'not performed'}
output.with_suffix('.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
