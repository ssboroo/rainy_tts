"""Real CPU inference only. No simulated speech or silent fallback."""
from array import array
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import subprocess
import wave
from urllib.parse import urlparse

class OronEngine:
    def __init__(self):
        self.model = None
        self.root = Path(os.getenv('MODEL_DIR', './models/oron')).resolve()

    def readiness(self):
        required = ['model.safetensors', 'vocab.txt', 'voices/male.wav', 'voices/male.txt', 'voices/female.wav', 'voices/female.txt', 'vocos/config.yaml', 'vocos/pytorch_model.bin']
        missing = [name for name in required if not (self.root / name).is_file()]
        purpose = os.getenv('TTS_USAGE_MODE', 'commercial')
        local_evaluation = (purpose == 'local-evaluation' and
                            urlparse(os.getenv('PUBLIC_ORIGIN', '')).hostname in ('localhost', '127.0.0.1', '::1'))
        if os.getenv('MODEL_LICENSE_APPROVED') != 'true' and not local_evaluation:
            return False, 'Арилжааны горим нээгдээгүй. Хувийн туршилтад scripts/run-local.ps1 ашиглана уу.'
        if missing:
            return False, 'Дууны загвар суулгагдаагүй. scripts/run-local.ps1 -InstallModel ажиллуулна уу.'
        try:
            import importlib.util
            if not all(importlib.util.find_spec(m) for m in ('f5_tts', 'oron_tts', 'soundfile')):
                return False, 'Дуу үүсгэх хөдөлгүүрийн суулгалт дутуу байна.'
        except (ImportError, ValueError):
            return False, 'Дуу үүсгэх хөдөлгүүрийн суулгалт дутуу байна.'
        return True, 'CPU хөдөлгүүр бэлэн'

    def synthesize(self, text, voice_path, transcript, output, speed=1.0):
        ready, reason = self.readiness()
        if not ready:
            raise RuntimeError(reason)
        import soundfile as sf
        from f5_tts.api import F5TTS
        from oron_tts.text import MongolianNormalizer
        if self.model is None:
            self.model = F5TTS(model='F5TTS_v1_Base', ckpt_file=str(self.root / 'model.safetensors'),
                              vocab_file=str(self.root / 'vocab.txt'), use_ema=False, device='cpu', vocoder_local_path=str(self.root / 'vocos'))
        normalized = MongolianNormalizer().normalize(text, strict=True)
        # The pinned upstream prints reference transcripts and retains temporary WAVs.
        # A single worker owns inference, so suppress its stdout and clear those caches.
        from f5_tts.infer import utils_infer
        try:
            with open(os.devnull, 'w') as sink, redirect_stdout(sink):
                wav, sr, _ = self.model.infer(ref_file=str(voice_path), ref_text=transcript,
                                            gen_text=normalized, nfe_step=32, cfg_strength=2.0,
                                            sway_sampling_coef=-1.0, seed=0, speed=speed,
                                            show_info=lambda *args: None)
            sf.write(str(output), wav, sr, subtype='PCM_16')
        finally:
            for cached in utils_infer._ref_audio_cache.values():
                Path(cached).unlink(missing_ok=True)
            utils_infer._ref_audio_cache.clear()
            utils_infer._ref_text_cache.clear()

    def builtin(self, voice_id):
        name = voice_id.removeprefix('builtin-')
        if name not in ('male', 'female'):
            raise ValueError('Хоолой олдсонгүй.')
        return self.root / f'voices/{name}.wav', (self.root / f'voices/{name}.txt').read_text().strip()

def convert_reference(source, destination):
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(source),'-t','13','-vn','-ac','1','-ar','24000','-c:a','pcm_s16le',str(destination)], check=True, timeout=45, capture_output=True)
    with wave.open(str(destination)) as audio:
        duration = audio.getnframes() / audio.getframerate()
        samples = array('h', audio.readframes(audio.getnframes()))
        rms = (sum(value * value for value in samples) / max(1, len(samples))) ** .5
        if rms < 50:
            raise ValueError('Бичлэг хэт сул эсвэл чимээгүй байна.')
        if not 3 <= duration <= 12:
            raise ValueError('Жишээ бичлэг 3–12 секунд байх ёстой.')
    return duration

def assemble(parts, output, cues=None):
    """Preserve cue starts; flag overruns, never overlap speech silently."""
    warnings = []
    with wave.open(str(parts[0]), 'rb') as first:
        params = first.getparams()
    rate, channels, width = params.framerate, params.nchannels, params.sampwidth
    cursor = 0
    with wave.open(str(output), 'wb') as target:
        target.setnchannels(channels); target.setsampwidth(width); target.setframerate(rate)
        for i, part in enumerate(parts):
            with wave.open(str(part), 'rb') as source:
                if (source.getframerate(),source.getnchannels(),source.getsampwidth()) != (rate,channels,width):
                    raise ValueError('Аудионы формат зөрүүтэй байна.')
                frames = source.readframes(source.getnframes())
                duration = source.getnframes() / rate
            if cues:
                desired = round(cues[i]['start'] * rate)
                if desired < cursor:
                    raise ValueError('Реплик дараагийн хугацаатай давхцлаа. Текстээ богиносгож дахин үүсгэнэ үү.')
                silence = desired - cursor
                if duration > cues[i]['end'] - cues[i]['start']:
                    warnings.append(f'{i+1}-р реплик хугацаанаас {duration-(cues[i]["end"]-cues[i]["start"]):.2f} секунд хэтэрсэн.')
            else:
                silence = int(rate * .25) if i else 0
            # bounded writes even for long subtitle gaps
            while silence > 0:
                count = min(silence, rate)
                target.writeframes(b'\0' * count * channels * width)
                silence -= count; cursor += count
            target.writeframes(frames); cursor += len(frames) // (channels * width)
    return warnings
