# RAINY Voice Studio

RAINY is a Mongolian-first creative audio studio built on ElevenLabs APIs.

## Tools

- **Text to Speech** — Eleven v4, 12 built-in Mongolian voices, clone voices, Text/SRT, WAV + MP3.
- **Voice Clone** — Instant Voice Clone from 1–10 consented audio samples.
- **Podcast / Dialogue** — multi-speaker Text to Dialogue with up to 10 unique voices per generation.
- **Music** — Music v2.5 by default, v2/v1 selector, instrumental mode, 3 seconds to 10 minutes.
- **Sound Effects** — Sound Effects v2 with duration, seamless loop and prompt-influence controls.
- **Speech to Text** — Scribe v2 batch transcription with TXT, JSON and SRT artifacts.
- **Realtime STT** — browser microphone to Scribe v2 Realtime using a server-issued single-use token, with transcript save to History.
- **Voice Changer** — uploaded speech transformed to a selected ElevenLabs voice.
- **Dubbing / Movie** — Dubbing v2 from upload or public URL; uploaded video can be muxed with the completed dubbed audio into MP4.
- **Voice Library** — 12 Mongolian voices plus user-created clones with preview.
- **Analytics** — ElevenLabs subscription/usage plus local RAINY 30-day usage.
- **History** — unified outputs from TTS and every creative tool.

## Architecture

Browser → FastAPI → ElevenLabs APIs

TTS also uses the durable SQLite worker queue:

Browser → FastAPI → SQLite TTS queue → worker → ElevenLabs Eleven v4 → WAV/MP3

Creative tool outputs are stored in:

- `tool_jobs`
- `artifacts`

The ElevenLabs API key stays server-side and is never sent to normal browser JavaScript. Realtime STT receives a short-lived single-use token instead.

## Setup

Python 3.12+ and FFmpeg are required.

```bash
git pull origin main
python -m venv .venv
# Windows
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS/Linux
# .venv/bin/python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`:

```env
PUBLIC_ORIGIN=http://localhost:8080
ALLOW_REGISTRATION=true
ELEVENLABS_API_KEY=your_server_side_key
ELEVENLABS_VOICES_JSON=
ELEVENLABS_LANGUAGE_CODE=mn
MAX_AUDIO_UPLOAD_MB=100
MAX_DUB_UPLOAD_MB=500
```

Do not commit a real API key.

Start the web app:

```bash
python -m app.server
```

Start the TTS worker in a second terminal:

```bash
python -m app.worker
```

Open http://localhost:8080.

## Docker

```bash
docker compose up -d --build
```

## Built-in Mongolian voices

1. Sarnai — Proud Mongolian Narrator
2. Bolor — Playful Ulaanbaatar Creator
3. Bataar — Calm Khalkha Narrator
4. Uyanga — Kind Khalkha Friend
5. Oyuna — Warm Khalkha Narrator
6. Temuulen — Upbeat Ulaanbaatar Creator
7. Enkhtuya — Proud Ovorkhangai Ad
8. Munkhbat — Warm Khentii Creator
9. Naran — Patient Ulaanbaatar Friend
10. Batbayar — Firm Khalkha Ad
11. Erdene — Blunt Ulaanbaatar Friend
12. Ganbold — Confident Khalkha Ad

## Voice cloning

RAINY requires the user to affirm that they have the right/consent to clone the uploaded voice. Voice cloning and deletion are executed in the connected ElevenLabs workspace, so its plan limits and verification requirements apply.

## Security notes

- API key is server-side only.
- Sessions use HttpOnly cookies.
- Mutating API calls require same-origin + CSRF token.
- Clone, STT, changer and dubbing uploads are type/size checked.
- Realtime STT uses a 15-minute single-use ElevenLabs token.
- Generated files are authorized per user before download.
- Production should use HTTPS and a reverse proxy with body-size/rate limits.

## Ownership

Application code authored for **ssboroo / RAINY Voice**. Copyright © 2026 ssboroo. Third-party APIs, voices and media remain subject to their own licenses, rights, consent requirements and ElevenLabs terms.


## Current provider limitations

- ElevenLabs Scribe v2 / Realtime supports Mongolian transcription, but production quality should be evaluated with real Mongolian audio before relying on automated transcripts.
- ElevenLabs `eleven_multilingual_sts_v2` does not currently list Mongolian among its supported source languages. The Voice Changer UI remains available for supported source languages and clearly shows this limitation for Mongolian source speech.
- Dubbing, cloning, music, SFX and other endpoints consume ElevenLabs credits according to the connected workspace plan.
