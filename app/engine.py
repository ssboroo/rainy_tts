"""ElevenLabs-only speech engine using the official ElevenLabs Python SDK."""
import json
import os
import subprocess
import wave

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()

def friendly_elevenlabs_error(exc):
    raw=str(exc or "").strip()
    low=raw.lower()
    mappings=[
        (("invalid_api_key","authentication_error","unauthorized"),"ElevenLabs API key буруу эсвэл хүчингүй байна."),
        (("insufficient_credits","quota_exceeded","payment_required"),"ElevenLabs credit/quota хүрэлцэхгүй байна."),
        (("voice_not_found",),"Сонгосон voice ID ElevenLabs дээр олдсонгүй."),
        (("voice_access_denied","forbidden"),"Энэ voice-д таны ElevenLabs account/API key хандах эрхгүй байна. Voice Library-оос account-даа Add/Use хийж байгааг шалгана уу."),
        (("model_access_denied",),"Eleven v4 model ашиглах эрх энэ account-д байхгүй байна."),
        (("subscription_required","feature_not_available"),"Энэ ElevenLabs боломж таны одоогийн plan-д нээлтгүй байна."),
        (("rate_limit","429"),"ElevenLabs rate limit хүрсэн байна. Түр хүлээгээд дахин оролдоно уу."),
    ]
    for needles,message in mappings:
        if any(needle in low for needle in needles):
            return message
    status=getattr(exc,"status_code",None)
    if status==401:
        return "ElevenLabs API key буруу эсвэл хүчингүй байна."
    if status==402:
        return "ElevenLabs credit/quota хүрэлцэхгүй байна."
    if status==403:
        return "ElevenLabs access permission хүрэлцэхгүй байна."
    if status==404:
        return "ElevenLabs voice/model resource олдсонгүй."
    return "ElevenLabs TTS хүсэлт амжилтгүй боллоо. Worker terminal дээрх дэлгэрэнгүй log-ийг шалгана уу."

class ElevenLabsEngine:
    """Server-side ElevenLabs Eleven v4 adapter for Mongolian speech."""

    model_id = 'eleven_v4'
    legacy_builtin_id = 'builtin-eleven-v4'
    default_voice_id = 'WgH4JH8sD6a2SIrujiKn'
    default_voice_catalog = [
        {'id':'WgH4JH8sD6a2SIrujiKn','name':'Sarnai - Proud Mongolian Narrator','builtin':True},
        {'id':'6OjaeAQxnuXC0oUZXZR2','name':'Bolor - Playful Ulaanbaatar Creator','builtin':True},
        {'id':'sjPAZPn7M1KgdmdYfsuu','name':'Bataar - Calm Khalkha Narrator','builtin':True},
        {'id':'2cecqSnkajrth9sJSoEH','name':'Uyanga - Kind Khalkha Friend','builtin':True},
        {'id':'4pSHaU93d1XS027ZFhHB','name':'Oyuna - Warm Khalkha Narrator','builtin':True},
        {'id':'ztVKSTjXnQBPBYroYARn','name':'Temuulen - Upbeat Ulaanbaatar Creator','builtin':True},
        {'id':'49bcW9p7CyYxa3c0X0im','name':'Enkhtuya - Proud Ovorkhangai Ad','builtin':True},
        {'id':'DLfKtGm2VGo06slN2VJE','name':'Munkhbat - Warm Khentii Creator','builtin':True},
        {'id':'sQRZO8j8yYwJ3eCSUFy3','name':'Naran - Patient Ulaanbaatar Friend','builtin':True},
        {'id':'Die79un8ishA33PLnH1j','name':'Batbayar - Firm Khalkha Ad','builtin':True},
        {'id':'D9okmaITNQEQZq1w4Z1C','name':'Erdene - Blunt Ulaanbaatar Friend','builtin':True},
        {'id':'RbMF2tQ1nCK38TfvNGLk','name':'Ganbold - Confident Khalkha Ad','builtin':True},
    ]

    def __init__(self):
        self.api_key = os.getenv('ELEVENLABS_API_KEY', '').strip()
        self.language_code = os.getenv('ELEVENLABS_LANGUAGE_CODE', 'mn').strip() or 'mn'
        self.client = ElevenLabs(api_key=self.api_key) if self.api_key else None

    @classmethod
    def configured_voices(cls):
        """Return the public voice catalog configured by environment variables."""
        raw = os.getenv('ELEVENLABS_VOICES_JSON', '').strip()
        voices = []
        seen = set()

        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError('ELEVENLABS_VOICES_JSON буруу JSON байна.') from exc
            if not isinstance(parsed, list):
                raise RuntimeError('ELEVENLABS_VOICES_JSON нь жагсаалт байх ёстой.')
            for item in parsed[:100]:
                if not isinstance(item, dict):
                    continue
                voice_id = str(item.get('id','')).strip()
                name = str(item.get('name','')).strip()[:80]
                if not voice_id or voice_id in seen:
                    continue
                if not name:
                    name = f'RAINY Voice {len(voices)+1:02d}'
                voices.append({'id':voice_id,'name':name,'builtin':True})
                seen.add(voice_id)

        if not voices:
            voices = [dict(voice) for voice in cls.default_voice_catalog]

        return voices

    @classmethod
    def resolve_voice_id(cls, voice_id):
        voices = cls.configured_voices()
        if voice_id == cls.legacy_builtin_id and voices:
            return voices[0]['id']
        allowed = {voice['id'] for voice in voices}
        return voice_id if voice_id in allowed else None

    def readiness(self):
        if not self.api_key:
            return False, 'ELEVENLABS_API_KEY тохируулаагүй байна.'
        try:
            voices = self.configured_voices()
        except RuntimeError as exc:
            return False, str(exc)
        if not voices:
            return False, 'ElevenLabs voice тохируулаагүй байна.'
        return True, f'ElevenLabs SDK · Eleven v4 · {len(voices)} voice бэлэн'

    @staticmethod
    def _audio_bytes(audio):
        if isinstance(audio, (bytes, bytearray)):
            return bytes(audio)
        try:
            return b''.join(audio)
        except TypeError as exc:
            raise RuntimeError('ElevenLabs SDK-аас аудио өгөгдөл авч чадсангүй.') from exc

    def synthesize(self, text, output, speed=1.0, voice_id=None, trusted_voice=False):
        ready, reason = self.readiness()
        if not ready:
            raise RuntimeError(reason)

        requested_voice = voice_id or self.legacy_builtin_id
        resolved_voice = requested_voice if trusted_voice else self.resolve_voice_id(requested_voice)
        if not resolved_voice:
            raise ValueError('Сонгосон ElevenLabs voice тохиргоонд байхгүй байна.')

        try:
            audio = self.client.text_to_speech.convert(
                text=text,
                voice_id=resolved_voice,
                model_id=self.model_id,
                output_format='pcm_24000',
                language_code=self.language_code,
            )
            pcm = self._audio_bytes(audio)
        except Exception as exc:
            raise RuntimeError(friendly_elevenlabs_error(exc)) from exc

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
