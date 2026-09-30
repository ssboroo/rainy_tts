# Deployment / Серверт байрлуулах

RAINY uses FastAPI + Uvicorn, SQLite storage, an ElevenLabs TTS worker, FFmpeg, and ElevenLabs Creative APIs. No GPU or local speech model is required.

## Local Windows

Install Python 3.12+ and FFmpeg.

```powershell
git pull origin main
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set the server-side `ELEVENLABS_API_KEY` in `.env`.

Terminal 1:

```powershell
.\.venv\Scripts\python.exe -m app.server
```

Terminal 2:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Open http://localhost:8080.

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

The web and worker containers share the `studio-data` volume. It stores SQLite, TTS outputs, creative-tool artifacts and temporary dubbing source video while an uploaded video is being processed.

## Reverse proxy

Use HTTPS in production. The included Caddy configuration can proxy to localhost:8080. Configure proxy request-body limits high enough for your chosen `MAX_AUDIO_UPLOAD_MB` and `MAX_DUB_UPLOAD_MB` values.

Realtime STT also requires outbound WebSocket access to ElevenLabs.

## Secrets

Never commit or embed `ELEVENLABS_API_KEY` in frontend JavaScript. Store it in `.env` locally or in the deployment platform's secret manager.

## Production checklist

- Rotate any API key that was pasted into a public/shared chat or log.
- Confirm ElevenLabs plan/permissions for TTS, IVC, Music, SFX, Scribe, Speech-to-Speech, Dubbing and Analytics.
- Add payment/credit controls before opening expensive generation endpoints to the public.
- Add password recovery and account deletion.
- Add reverse-proxy rate limits, storage quotas and retention cleanup.
- Monitor API errors, credit usage and artifact disk size.
- Back up SQLite and required generated artifacts.
- Test restore procedures.
- Run a security review before a public paid launch.

## Dubbing

Dubbing project creation consumes ElevenLabs credits. Uploaded video sources are kept privately only while needed for local audio/video muxing and are deleted after the completed dub is muxed or the project fails/deletes.

## Backup

Back up SQLite consistently and copy retained outputs to encrypted off-host storage if required. Never include the real `.env` file in backups shared outside the server.
