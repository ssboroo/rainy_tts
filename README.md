# RAINY Voice · Монгол TTS студи

RAINY Voice is a browser-based Mongolian text-to-speech studio. The current runtime uses **ElevenLabs Eleven v4 only**.

## Current architecture

Browser → same-origin Python API → SQLite queue → worker → ElevenLabs Eleven v4 → WAV/MP3

There is no local speech model, no Oron/F5 runtime, and no GPU requirement in the current setup.

## Features

- Монгол интерфэйс.
- Text and SRT input.
- Server-side official ElevenLabs Python SDK integration.
- API key never exposed to browser JavaScript.
- Multiple configured ElevenLabs voices exposed in the RAINY voice selector.
- Speed control, pronunciation glossary and long-text chunking.
- Durable job queue and progress.
- WAV/MP3 export.
- Login, HttpOnly session, CSRF/origin checks and per-user history.

## Configure

Copy `.env.example` to `.env` and set:

```env
PUBLIC_ORIGIN=http://localhost:8080
ALLOW_REGISTRATION=true

ELEVENLABS_API_KEY=your_server_side_key
ELEVENLABS_VOICES_JSON=[{"id":"WgH4JH8sD6a2SIrujiKn","name":"RAINY Voice 01"},{"id":"SECOND_VOICE_ID","name":"RAINY Voice 02"}]
ELEVENLABS_LANGUAGE_CODE=mn
ELEVENLABS_STABILITY=0.5
ELEVENLABS_SIMILARITY_BOOST=0.8
```

Never commit a real API key.

## Run locally

Python 3.12+ and FFmpeg are required. RAINY uses the official ElevenLabs Python SDK.

```bash
pip install -r requirements.txt
python -m app.server
# second terminal
python -m app.worker
```

Open http://localhost:8080.

## Docker

```bash
docker compose up -d --build
```

The current Docker image contains only the web/worker runtime and FFmpeg. Model weights and model volumes are not required.

## Notes

RAINY sends TTS jobs to `eleven_v4` using the voice selected from `ELEVENLABS_VOICES_JSON`. If that variable is empty, the legacy `ELEVENLABS_VOICE_ID` value is used as a single-voice fallback. ElevenLabs billing, rate limits, voice rights and account permissions apply to production use.

See [Deployment](docs/DEPLOY.md) and [ElevenLabs provider](docs/MODELS.md).

## Ownership

Application code authored for **ssboroo / RAINY Voice**. Copyright © 2026 ssboroo. All rights reserved unless separately licensed. Third-party APIs, voices and services remain subject to their own terms and rights.


## ElevenLabs Quickstart alignment

RAINY follows the official SDK authentication pattern:

```python
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
import os

load_dotenv()
client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
audio = client.text_to_speech.convert(
    text="Сайн байна уу.",
    voice_id="WgH4JH8sD6a2SIrujiKn",
    model_id="eleven_v4",
    output_format="pcm_24000",
    language_code="mn",
)
```

The official quickstart commonly shows `mp3_44100_128` plus local speaker playback. RAINY requests `pcm_24000` because its worker joins long-text/SRT chunks as WAV, then exports the finished result as both WAV and MP3.
