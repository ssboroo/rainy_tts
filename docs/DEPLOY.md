# Deployment / Серверт байрлуулах

RAINY Voice currently uses **ElevenLabs Eleven v4 only**. No local model or GPU is required.

## Local Windows

Install Python 3.12+ and FFmpeg. Copy `.env.example` to `.env`, add your ElevenLabs API key and `ELEVENLABS_VOICES_JSON` voice catalog, then start two terminals:

```powershell
python -m app.server
```

```powershell
python -m app.worker
```

Open http://localhost:8080.

## Docker server

```bash
cp .env.example .env
# Set PUBLIC_ORIGIN, ELEVENLABS_API_KEY and ELEVENLABS_VOICES_JSON.
docker compose up -d --build
```

Use `deploy/Caddyfile` with the production domain and expose only 80/443 publicly. Port 8080 remains bound to localhost.

The web and worker containers share one persistent `studio-data` volume. There is no model volume.

## Secrets

Store the real ElevenLabs key only in `.env` or your deployment secret manager. Do not put it in GitHub, frontend JavaScript or screenshots.

## Before charging customers

- Confirm ElevenLabs commercial/account terms for the intended workload.
- Add payment and a transaction-safe credit ledger.
- Add password recovery and account deletion.
- Add reverse-proxy rate limits, retention policy, storage quotas and monitoring.
- Track ElevenLabs API latency, failures, rate limits and credit usage.
- Test backups and restoration.
- Run a security review before a public paid launch.

## Backup

Back up the SQLite database using a consistent SQLite backup and copy generated outputs to encrypted off-host storage if you need retention. Never back up or publish the real `.env` file with the API key.
