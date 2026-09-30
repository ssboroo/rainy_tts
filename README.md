# RAINY Voice · Монгол TTS студи

RAINY Voice is a browser-based Mongolian text-to-speech studio. The current runtime uses **ElevenLabs Eleven v4 only**.

## Current architecture

Browser → same-origin Python API → SQLite queue → worker → ElevenLabs Eleven v4 → WAV/MP3

There is no local speech model, no Oron/F5 runtime, and no GPU requirement in the current setup.

## Features

- Монгол интерфэйс.
- Text and SRT input.
- Server-side ElevenLabs API integration.
- API key never exposed to browser JavaScript.
- One configured ElevenLabs voice exposed as the current RAINY voice.
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
ELEVENLABS_VOICE_ID=your_voice_id
ELEVENLABS_VOICE_LABEL=Монгол · Eleven v4
ELEVENLABS_LANGUAGE_CODE=mn
ELEVENLABS_STABILITY=0.5
ELEVENLABS_SIMILARITY_BOOST=0.8
```

Never commit a real API key.

## Run locally

Python 3.12+ and FFmpeg are required.

```bash
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

RAINY currently sends TTS jobs to `eleven_v4` using the configured `ELEVENLABS_VOICE_ID`. ElevenLabs billing, rate limits, voice rights and account permissions apply to production use.

See [Deployment](docs/DEPLOY.md) and [ElevenLabs provider](docs/MODELS.md).

## Ownership

Application code authored for **ssboroo / RAINY Voice**. Copyright © 2026 ssboroo. All rights reserved unless separately licensed. Third-party APIs, voices and services remain subject to their own terms and rights.
