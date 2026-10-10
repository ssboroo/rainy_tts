"""User-scoped voice design/remix and forced alignment.

Provider contracts verified against ElevenLabs official API reference:
https://elevenlabs.io/docs/api-reference/text-to-voice/design
https://elevenlabs.io/docs/api-reference/text-to-voice/remix
https://elevenlabs.io/docs/api-reference/text-to-voice/create
https://elevenlabs.io/docs/api-reference/forced-alignment/create

Credit estimates are conservative platform policies using existing declared rates,
not claims about ElevenLabs retail prices. These endpoints do not auto-retry.
"""
import asyncio
import difflib
import re
import unicodedata
import base64
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import quote

import httpx
from fastapi import File, Form, HTTPException, Request, UploadFile
from . import billing, core
from .engine import friendly_elevenlabs_error

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ALIGNMENT_SECONDS = 3600
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.m4a', '.ogg', '.flac', '.aac', '.webm'}


def text_field(value, name, minimum, maximum):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise HTTPException(422, f'{name}: {minimum}–{maximum} тэмдэгт оруулна уу.')
    return value.strip()


async def validate_media(upload):
    """Bound input bytes and verify an actual audio stream and finite duration."""
    suffix = Path(upload.filename or '').suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise HTTPException(422, 'WAV, MP3, M4A, OGG, FLAC, AAC эсвэл WEBM аудио оруулна уу.')
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as target:
            path = Path(target.name)
            size = 0
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, 'Аудио файлын хэмжээ 50 MB-аас хэтэрч болохгүй.')
                target.write(chunk)
        if not size:
            raise HTTPException(422, 'Аудио файл хоосон байна.')
        process = await asyncio.to_thread(subprocess.run, [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
            '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
        data = json.loads(process.stdout) if process.returncode == 0 else {}
        duration = float(data.get('format', {}).get('duration', 0))
        if not any(s.get('codec_type') == 'audio' for s in data.get('streams', [])) or not math.isfinite(duration) or not 0 < duration <= MAX_ALIGNMENT_SECONDS:
            raise HTTPException(422, 'Бодит аудио, 1 цаг хүртэлх хугацаатай файл шаардлагатай.')
        return duration
    except FileNotFoundError:
        raise HTTPException(503, 'Аудио шалгах FFmpeg тохируулаагүй байна.')
    except (ValueError, subprocess.TimeoutExpired):
        raise HTTPException(422, 'Аудио файлыг шалгаж чадсангүй.')
    finally:
        if path:
            path.unlink(missing_ok=True)
        await upload.seek(0)


def stamp(seconds, vtt=False):
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02}{"." if vtt else ","}{millis:03}'


def subtitle_exports(words):
    """Group provider word timings into short readable cues; preserve exact timings."""
    cues = []
    group = []
    previous = 0
    for word in words:
        text = str(word.get('text', '')).strip()
        start, end = float(word.get('start', 0)), float(word.get('end', 0))
        if not all(math.isfinite(v) for v in (start, end)) or start < 0 or end < start or start < previous:
            raise ValueError('Хадмалын хугацааны өгөгдөл буруу байна.')
        previous = start
        if not text:
            continue
        if group and (end - group[0]['start'] > 5 or len(' '.join(x['text'] for x in group)) + len(text) > 70):
            cues.append(group); group = []
        group.append({'text': text, 'start': start, 'end': end})
    if group:
        cues.append(group)
    if not cues:
        raise ValueError('Үгийн хугацааны өгөгдөл хоосон байна.')
    def export(vtt):
        lines = ['WEBVTT', ''] if vtt else []
        for i, cue in enumerate(cues, 1):
            lines.extend([str(i), f'{stamp(cue[0]["start"], vtt)} --> {stamp(max(x["end"] for x in cue), vtt)}', ' '.join(x['text'] for x in cue).replace('-->', '→'), ''])
        return '\n'.join(lines) + '\n'
    return export(False), export(True)


def estimate_credits(kind, *, chars=0, seconds=0):
    if kind in {'voice_design', 'voice_remix'}:
        # The provider produces multiple previews: reserve at least clone-flat or
        # ten TTS equivalents. No unverified provider currency conversion.
        return max(billing.estimate('voice_clone'), billing.estimate('tts', chars=chars) * 10)
    if kind == 'alignment':
        return max(billing.estimate('speech_to_text', seconds=seconds), billing.estimate('voice_isolator', seconds=seconds))
    raise ValueError('Unknown extension tool')


def provider_error(exc):
    if isinstance(exc, HTTPException):
        return exc
    status = getattr(exc, 'status', 502)
    if status not in {400, 401, 402, 403, 404, 409, 422, 429, 503}:
        status = 502
    return HTTPException(status, friendly_elevenlabs_error(exc))


def subtitle_words_from_scribe(result, duration):
    """Use word-level Scribe timestamps, never fabricate timings for missing words."""
    entries = result.get('words', []) if isinstance(result, dict) else []
    if not isinstance(entries, list) or len(entries) > 20000:
        raise ValueError('Монгол ярианы үгийн хугацааны өгөгдөл буруу байна.')
    words = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Танигдсан үгийн мэдээлэл буруу байна.')
        if entry.get('type', 'word') != 'word':
            continue  # Scribe can also return spacing and non-speech events.
        text = str(entry.get('text') or '').strip()
        if not text:
            continue
        start, end = entry.get('start'), entry.get('end')
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError('Монгол үгийн хугацаа тодорхойгүй тул буруу хадмал гаргахгүй.')
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end > duration + 2:
            raise ValueError('Монгол үгийн хугацаа аудионы урттай таарахгүй байна.')
        if words and start < words[-1]['start']:
            raise ValueError('Үгийн хугацааны дараалал буруу байна.')
        words.append({'text': text, 'start': float(start), 'end': float(end)})
    if not words:
        raise ValueError('Монгол хэлний үг, хугацаа олдсонгүй. Аудио болон хэлээ шалгана уу.')
    return words


def transcript_similarity(reference, recognized):
    """Diagnostic only: NEVER pretend Scribe has forcibly aligned the reference."""
    def normalize(text):
        text = unicodedata.normalize('NFC', text).casefold()
        return ' '.join(re.findall(r'[\w]+', text, flags=re.UNICODE))
    a, b = normalize(reference), normalize(recognized)
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3) if a and b else None


async def execute_alignment(user_id, job_id, upload, text, duration, credits, *,
                            language_code='en', provider=None, create_artifact_text=None):
    """Create timed subtitles. Mongolian uses Scribe v2, NOT unsupported Forced Alignment.

    Preserve old English/non-Mongolian queued jobs and their provider behavior.
    Store transcription discrepancies for explicit customer review before publication.
    """
    if provider is None or create_artifact_text is None:
        from . import server
        provider = provider or server.tools
        create_artifact_text = create_artifact_text or server.create_artifact_text
    useful_output = False
    language = (language_code or '').strip().lower()
    mongolian = language in {'mn', 'mon', 'mn-mn'}
    try:
        await upload.seek(0)
        if mongolian:
            result = await provider.speech_to_text(
                upload, 'mn', keyterms=None, polish=False, diarize=False,
                num_speakers=1, no_verbatim=False)
            if not isinstance(result, dict):
                raise ValueError('Монгол яриаг таньсан хариултын формат буруу байна.')
            words = subtitle_words_from_scribe(result, duration)
            recognized = str(result.get('text') or '').strip() or ' '.join(w['text'] for w in words)
            score = transcript_similarity(text, recognized) if text else None
            warnings = ['Scribe v2 Монгол хэл дэмждэг ч автоматаар таньсан үг, нэр, тоо болон цагийг нийтлэхээс өмнө хянана уу.']
            if score is not None and score < .83:
                warnings.append('Оруулсан эх текст танигдсан ярианаас зөрж байна. Хадмалыг танигдсан үгсээс үүсгэсэн; таны эх тексттэй яг тааруулсан гэж үзэхгүй.')
            detected = str(result.get('language_code') or '').lower()
            if detected and detected not in {'mn', 'mon', 'mn-mn'}:
                warnings.append('Ярианы таньсан хэл Монгол биш байна (' + detected[:12] + '). Бэлэн хадмалыг заавал шалгана уу.')
            srt, vtt = subtitle_exports(words)
            output = {k:v for k,v in result.items() if k != '_provider_usage'}
            output['alignment_method'] = 'scribe_v2_word_timestamps'
            output['reference_similarity'] = score
            output['review_required'] = True
            output['warnings'] = warnings
            transcript = recognized
        else:
            if not text:
                raise ValueError('Монгол хэлнээс бусад Forced Alignment-д бэлэн эх бичвэр шаардлагатай.')
            response = await provider._request('POST', '/v1/forced-alignment',
                files={'file': (Path(upload.filename).name, upload.file, upload.content_type or 'application/octet-stream')},
                data={'text': text}, timeout=240)
            result = response.json()
            srt, vtt = subtitle_exports(result.get('words', []))
            output = {**result, 'alignment_method':'elevenlabs_forced_alignment',
                      'review_required':True, 'warnings':['Хадмал болон нэр томьёог нийтлэхээс өмнө шалгана уу.']}
            transcript = text
        exports = {
            'txt': ('text/plain', transcript),
            'json': ('application/json', json.dumps(output, ensure_ascii=False)),
            'srt': ('application/x-subrip', srt),
            'vtt': ('text/vtt', vtt),
        }
        if mongolian and text and text != transcript:
            exports['reference'] = ('text/plain', text)
        artifacts = {}
        for ext, (mime, content) in exports.items():
            name = 'alignment-reference.txt' if ext == 'reference' else 'alignment.' + ext
            artifacts[ext] = create_artifact_text(user_id, job_id, 'alignment', name, mime, content)
            useful_output = True
        return {
            'artifacts': artifacts, 'credits_used': credits, 'duration_seconds': duration,
            'language_code': 'mn' if mongolian else language,
            'alignment_method': output['alignment_method'],
            'review_required': True,
            'reference_similarity': output.get('reference_similarity'),
            'warnings': output['warnings'],
        }
    except Exception as exc:
        if useful_output:
            exc.useful_output = True
        raise


def register_routes(app, session, mutation_guard, throttle, provider, allowed_voice_ids,
                    charge, create_artifact_bytes, create_artifact_text):
    # Lock before checking slots, hold through upstream save and local insertion.
    # The documented deployment uses one web process. DB save state prevents
    # replay after a restart; an ambiguous result requires operator reconciliation.
    save_locks = {}

    def guard(request, capability):
        sess = session(request)
        mutation_guard(request, sess)
        throttle(capability + ':' + sess['user_id'], 8, 3600)
        return sess['user_id']

    async def json_body(request):
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(422, 'JSON хүсэлтийн өгөгдөл буруу байна.')
        if not isinstance(data, dict):
            raise HTTPException(422, 'Хүсэлтийн өгөгдөл буруу байна.')
        return data

    def record_failure(user, job, charge_id, exc, useful_output=False):
        uncertain = isinstance(exc, (httpx.TimeoutException, httpx.TransportError)) or (getattr(exc, 'status_code', getattr(exc, 'status', 0)) or 0) >= 500
        if not uncertain and not useful_output and not getattr(exc, 'useful_output', False):
            billing.refund(user, charge_id, 'provider_failed')
        core.update_tool_job(job, 'failed', error='Үйлчилгээний үр дүн тодорхойгүй. Дахин төлбөртэй хүсэлт үүсгэхээс өмнө тусламж авна уу.' if uncertain else friendly_elevenlabs_error(exc))

    async def previews(request, remix=False):
        user = guard(request, 'voice_remix' if remix else 'voice_design')
        data = await json_body(request)
        prompt = text_field(data.get('prompt'), 'Хоолойн тайлбар', 5 if remix else 20, 1000)
        text = text_field(data.get('text'), 'Жишээ текст', 100, 1000)
        payload = {'prompt': prompt, 'text': text}
        path = '/v1/text-to-voice/design'
        if remix:
            voice = text_field(data.get('voice_id'), 'Хоолойн ID', 1, 100)
            with core.db() as db:
                owned = db.execute('SELECT id FROM voices WHERE id=? AND user_id=?', (voice, user)).fetchone()
            if not owned:
                raise HTTPException(404, 'Таны эзэмшдэг хоолой олдсонгүй.')
            payload['voice_id'] = voice
            path = '/v1/text-to-voice/' + quote(voice, safe='') + '/remix'
        kind = 'voice_remix' if remix else 'voice_design'
        credits = estimate_credits(kind, chars=len(text))
        job = core.create_tool_job(user, kind, prompt, payload)
        charge_id = None
        useful_output = False
        try:
            charge_id = charge(user, credits, kind, job, {'basis': 'platform_preview_reserve', 'chars': len(text)})
            response = await provider._request('POST', path, json={'voice_description': prompt, 'text': text, 'stream_previews': False}, params={'output_format': 'mp3_44100_128'})
            result = response.json()
            source = result.get('previews', [])
            if not isinstance(source, list) or not 1 <= len(source) <= 10:
                raise ValueError('Хоолойн жишээ буцаж ирсэнгүй.')
            # Validate every upstream item before persisting any useful output.
            decoded = []
            for preview in source:
                generated = text_field(preview.get('generated_voice_id'), 'Жишээний ID', 1, 100)
                raw = preview.get('audio_base_64', '')
                if not isinstance(raw, str) or len(raw) > 20 * 1024 * 1024:
                    raise ValueError('Хоолойн жишээний хэмжээ буруу байна.')
                audio = base64.b64decode(raw, validate=True)
                if not audio:
                    raise ValueError('Хоолойн жишээ хоосон байна.')
                decoded.append((generated, audio))
            outputs = []
            for index, (generated, audio) in enumerate(decoded):
                artifact = create_artifact_bytes(user, job, 'audio', f'voice-preview-{index + 1}.mp3', 'audio/mpeg', audio)
                useful_output = True
                outputs.append({'generated_voice_id': generated, 'artifact_id': artifact})
            output = {'previews': outputs, 'credits_used': credits, 'text': result.get('text', text)}
            core.update_tool_job(job, 'done', result=output)
            return {'job_id': job, **output}
        except Exception as exc:
            record_failure(user, job, charge_id, exc, useful_output)
            raise provider_error(exc)

    @app.post('/api/tools/voice-design')
    async def design(request: Request):
        return await previews(request)

    @app.post('/api/tools/voice-remix')
    async def remix(request: Request):
        return await previews(request, True)

    async def save(request, kind):
        user = guard(request, kind + '_save')
        data = await json_body(request)
        job = text_field(data.get('job_id'), 'Ажлын ID', 1, 100)
        generated = text_field(data.get('generated_voice_id'), 'Жишээний ID', 1, 100)
        name = text_field(data.get('name'), 'Хоолойн нэр', 1, 100)
        lock = save_locks.setdefault(user, asyncio.Lock())
        async with lock:
            with core.db() as db:
                row = db.execute('SELECT * FROM tool_jobs WHERE id=? AND user_id=? AND tool_type=?', (job, user, kind)).fetchone()
            if not row:
                raise HTTPException(404, 'Хоолойн жишээ олдсонгүй.')
            result = json.loads(row['result'] or '{}')
            if generated not in {p['generated_voice_id'] for p in result.get('previews', [])}:
                raise HTTPException(422, 'Энэ жишээ тухайн ажилд хамаарахгүй байна.')
            saved = result.get('saved_voices', {}).get(generated)
            if saved:
                return {'job_id': job, 'voice': saved}
            if result.get('save_pending'):
                raise HTTPException(409, 'Хадгалах үр дүнг шалгах шаардлагатай. Тусламж авна уу.')
            account = billing.wallet(user)
            sub = account.get('subscription') or {}
            plan = billing.get_plan(sub.get('plan_id')) or {}
            with core.db() as db:
                count = db.execute('SELECT COUNT(*) FROM voices WHERE user_id=?', (user,)).fetchone()[0]
            if billing.billing_enabled() and not billing.admin_test_mode(user):
                limit = int(plan.get('clone_limit', 0))
                if sub.get('status') != 'active' or limit <= 0:
                    raise HTTPException(402, 'Хоолой хадгалах эрхтэй идэвхтэй багц шаардлагатай.')
                if count >= limit:
                    raise HTTPException(409, f'Таны багц {limit} хоолой хадгалах эрхтэй.')
            payload = json.loads(row['payload'])
            description = payload['prompt']
            if len(description) < 20:
                description = 'Remixed voice: ' + description
            result['save_pending'] = generated
            core.update_tool_job(job, result=result)
            try:
                response = await provider._request('POST', '/v1/text-to-voice', json={'voice_name': name, 'voice_description': description, 'generated_voice_id': generated})
                upstream = response.json()
                voice_id = text_field(upstream.get('voice_id'), 'Хоолойн ID', 1, 100)
                voice = {'id': voice_id, 'name': name}
                with core.db() as db:
                    # INSERT avoids overwriting another user's provider voice ID.
                    db.execute('INSERT INTO voices(id,user_id,name,transcript,created) VALUES(?,?,?,?,?)', (voice_id, user, name, payload['prompt'], time.time()))
                result.setdefault('saved_voices', {})[generated] = voice
                result.pop('save_pending', None)
                core.update_tool_job(job, result=result)
                return {'job_id': job, 'voice': voice}
            except Exception as exc:
                # Known rejection is safe to retry. Transport failures and local
                # persistence failures remain pending to avoid duplicate saves.
                if getattr(exc, 'status', None) in {400, 401, 402, 403, 404, 409, 422, 429, 503}:
                    result.pop('save_pending', None)
                    core.update_tool_job(job, result=result)
                raise provider_error(exc)

    @app.post('/api/tools/voice-design/save')
    async def save_design(request: Request):
        return await save(request, 'voice_design')

    @app.post('/api/tools/voice-remix/save')
    async def save_remix(request: Request):
        return await save(request, 'voice_remix')

    @app.post('/api/tools/alignment')
    async def alignment(request: Request, file: UploadFile = File(...), text: str = Form(''),
                        title: str = Form('Монгол хадмал'), language_code: str = Form('mn')):
        user = guard(request, 'alignment')
        language = (language_code or '').strip().lower()
        if language not in {'mn', 'mon', 'mn-mn', 'en', 'ja', 'ko', 'es', 'fr', 'de', 'zh', 'ru'}:
            raise HTTPException(422, 'Хэлний сонголт буруу. Монгол, англи, япон зэрэг дэмжигдэх хэлээ сонгоно уу.')
        if language in {'mn', 'mon', 'mn-mn'}:
            text = text.strip()
            if len(text) > 20000:
                raise HTTPException(422, 'Монгол эх бичвэр 20,000 тэмдэгтээс хэтрэхгүй.')
        else:
            text = text_field(text, 'Бэлэн эх текст', 1, 20000)
        title = text_field(title, 'Гарчиг', 1, 100)
        duration = await validate_media(file)
        credits = estimate_credits('alignment', seconds=duration)
        if os.getenv('DURABLE_TOOLS_ENABLED', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}:
            from . import server
            return await server.enqueue_tool(
                {'user_id': user}, 'forced_alignment', title,
                {'method': 'forced_alignment', 'args': [text, duration, credits, language]},
                'alignment.json', 'application/json', credits, file)
        job = core.create_tool_job(user, 'alignment', title, {'text': text, 'duration_seconds': duration, 'language_code': language})
        charge_id = None
        useful_output = False
        try:
            charge_id = charge(user, credits, 'alignment', job, {'basis': 'platform_alignment_reserve', 'duration_seconds': duration})
            output = await execute_alignment(user, job, file, text, duration, credits, provider=provider, create_artifact_text=create_artifact_text, language_code=language)
            useful_output = True
            core.update_tool_job(job, 'done', result=output)
            return {'job_id': job, **output}
        except Exception as exc:
            record_failure(user, job, charge_id, exc, useful_output)
            raise provider_error(exc)
        finally:
            await file.close()
