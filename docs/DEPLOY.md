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

## Production acceptance

Follow [production operations](PRODUCTION.md) before public paid launch. Configure paid ElevenLabs access, live Wire credentials and transactional SMTP; retain `BILLING_ENABLED=true` and `BILLING_TARGET_MARKUP=3.0`. Verify real generation, payment, reset email, authorization and isolated restore. Configuration readiness alone is insufficient.

For Railway use one service/replica through `python -m app.railway`, one persistent volume at `/data`, and `DATA_DIR=/data`. **Export and verify existing accounts/database/media before mounting storage.** An empty volume must never hide existing data. Keep `/api/health` as liveness; inspect readiness separately. Set `PERSISTENT_STORAGE_CONFIRMED=true` only after migration and redeploy survival checks.

## Dubbing

Dubbing project creation consumes ElevenLabs credits. Uploaded video sources are kept privately only while needed for local audio/video muxing and are deleted after the completed dub is muxed or the project fails/deletes.

## Backup

Use `python -m app.operations backup /backups/unique-snapshot.db` for a consistent SQLite snapshot. Copy retained media to encrypted off-host storage and verify an isolated restore with `python -m app.operations verify /restore/studio.db`. See the full preservation procedure in [production operations](PRODUCTION.md). Never include the real `.env` file in backups shared outside the server.
