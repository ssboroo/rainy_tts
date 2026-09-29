# Deployment / Серверт байрлуулах

## Local Windows developer check (no GPU)

Install Python 3.12+ and FFmpeg, then in PowerShell:

```powershell
$env:PUBLIC_ORIGIN="http://localhost:8080"
$env:ALLOW_REGISTRATION="true"
python -m app.server
```

In another terminal: `python -m app.worker`. Open http://localhost:8080. The UI, accounts, uploads and persistent history work without a model. Real generation remains disabled until the model integration described in MODELS.md is completed. This is a developer check; end users use a browser only.

## CPU Linux server with Docker

```bash
cp .env.example .env
# Edit PUBLIC_ORIGIN to https://your-new-domain.example.
# Registration stays disabled until you choose to open a pilot.
docker compose up -d --build
```

Use `deploy/Caddyfile` with the new domain on the host; point DNS at the server, allow only 80/443 publicly, and provision HTTPS through Caddy. Port 8080 binds to localhost. Do not expose the Python HTTP server directly to the Internet. Set the exact HTTPS `PUBLIC_ORIGIN` before accepting users; this enables Secure cookies and origin checks. External HTTPS termination is required.

The application uses only Python's standard library, SQLite and FFmpeg for the non-model stack. It has one web process and **exactly one worker** sharing the same persistent volume. Do not scale the worker service: startup recovery assumes a single worker. Model weights/cache use a separate persistent volume. No hosted TTS API or per-user API keys are needed.

## Before charging customers

- Complete actual inference and licensing evaluation (MODELS.md). Test cold starts and CPU saturation.
- Benchmark simultaneous jobs; size RAM/CPU from measurements, not an advertised speed claim.
- Add verified email/password recovery and account deletion. Current pilot uses password login with no recovery flow.
- Integrate a payment provider and a transaction-safe credit ledger. Verify payment server-to-server and handle duplicate webhooks idempotently. No payment button or credit deduction is faked in this release.
- Add global request throttling/connection limits at the reverse proxy, storage quotas, retention policy and operational alerts. Application limits alone do not protect against denial of service.
- Add a disk-space monitor, inference watchdog and worker heartbeat; process crash recovery exists, but a hung model call currently needs worker restart.
- Test restoration of backups. Set account/audio retention terms and a voice-consent policy. No user voices are used for training by this app.
- Have security review before a public paid launch. This repository is an engineering pilot, not a certified production service.

## Backup

Back up the SQLite database with SQLite's online backup API and copy voice/output directories to encrypted off-host storage. Keep model revisions reproducible. Test restoration to a separate server. Do not copy a live `.db` without its WAL or a consistent snapshot. Protect backup access as strictly as live private voice data.

## What is intentionally absent

No domain has been purchased, no hosted endpoint provisioned, no external provider keys stored. New voice design, automatic acting and multi-character SRT assignment are roadmap items. Current SRT jobs use one chosen voice per file; split by character until a speaker-track editor is added.

## Windows local evaluation launcher

The commercial release flag must not be set merely to dismiss a message. Local evaluation has a separate mode which only works when `PUBLIC_ORIGIN` is loopback. Install Python 3.12, Git and FFmpeg, then:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1 -InstallModel
```

This process-specific policy applies only to this checked-in launcher; it does not change the machine's execution policy. Review the script before running it. The first run installs the CPU environment and downloads model weights; it can take time and several GB of disk. Afterwards run the same command without `-InstallModel`. The launcher runs both web and worker; Ctrl+C stops the web and its worker. First stop any older web/worker instances. The Windows launcher has not been executed on Windows in this Linux development environment.

`TTS_USAGE_MODE=local-evaluation` is not commercial rights clearance. Public deployments still require the commercial review flag. Merely enabling evaluation does not install the model or start a worker.
