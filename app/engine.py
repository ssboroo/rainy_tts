"""ElevenLabs-only speech engine and audio assembly helpers."""
import json
import os
import subprocess
import wave
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

class ElevenLabsEngine:
    """Server-side ElevenLabs Eleven v4 adapter for Mongolian speech."""

    model_id = 'eleven_v4'
    builtin_id = 'builtin-eleven-v4'

    def __init__(self):
        self.api_key = os.getenv('ELEVENLABS_API_KEY', '').strip()
        self.voice_id = os.getenv('ELEVENLABS_VOICE_ID', '').strip()
        self.language_code = os.getenv('ELEVENLABS_LANGUAGE_CODE', 'mn').strip() or 'mn'

    def readiness(self):
        if not self.api_key:
            return False, 'ELEVENLABS_API_KEY тохируулаагүй байна.'
        if not self.voice_id:
            return False, 'ELEVENLABS_VOICE_ID тохируулаагүй байна.'
        return True, 'ElevenLabs · Eleven v4 бэлэн'

    def _setting(self, name, default):
        try:
            value = float(os.getenv(name, str(default)))
        except ValueError:
            value = default
        return max(0.0, min(1.0, value))

    def synthesize(self, text, output, speed=1.0):
        ready, reason = self.readiness()
        if not ready:
            raise RuntimeError(reason)

        payload = {
            'text': text,
            'model_id': self.model_id,
            'language_code': self.language_code,
            'voice_settings': {
                'stability': self._setting('ELEVENLABS_STABILITY', 0.5),
                'similarity_boost': self._setting('ELEVENLABS_SIMILARITY_BOOST', 0.8),
            },
        }
        endpoint = 'https://api.elevenlabs.io/v1/text-to-speech/' + quote(self.voice_id, safe='')
        endpoint += '?' + urlencode({'output_format': 'pcm_24000'})
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={
                'xi-api-key': self.api_key,
                'Content-Type': 'application/json',
                'Accept': 'audio/pcm',
            },
            method='POST',
        )
        try:
            with urlopen(request, timeout=90) as response:
                pcm = response.read(20 * 1024 * 1024 + 1)
        except HTTPError as exc:
            raise RuntimeError(f'ElevenLabs API алдаа ({exc.code}).') from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError('ElevenLabs API-д холбогдож чадсангүй.') from exc

        if not pcm or len(pcm) > 20 * 1024 * 1024 or len(pcm) % 2:
            raise RuntimeError('ElevenLabs-аас буруу аудио хариу ирлээ.')

        with wave.open(str(output), 'wb') as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(24000)
            target.writeframes(pcm)

        speed = float(speed)
        if abs(speed - 1.0) > .001:
            adjusted = output.with_name(output.stem + '.tempo.wav')
            try:
                subprocess.run(
                    ['ffmpeg','-nostdin','-v','error','-y','-i',str(output),'-filter:a',f'atempo={speed:.3f}',str(adjusted)],
                    check=True, timeout=90, capture_output=True,
                )
                adjusted.replace(output)
            finally:
                adjusted.unlink(missing_ok=True)

def assemble(parts, output, cues=None):
    """Preserve cue starts; flag overruns, never overlap speech silently."""
    warnings = []
    with wave.open(str(parts[0]), 'rb') as first:
        params = first.getparams()
    rate, channels, width = params.framerate, params.nchannels, params.sampwidth
    cursor = 0
    with wave.open(str(output), 'wb') as target:
        target.setnchannels(channels)
        target.setsampwidth(width)
        target.setframerate(rate)
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
            while silence > 0:
                count = min(silence, rate)
                target.writeframes(b'\0' * count * channels * width)
                silence -= count
                cursor += count
            target.writeframes(frames)
            cursor += len(frames) // (channels * width)
    return warnings
