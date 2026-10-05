# Production Audio Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Complete a Mongolian-first paid audio studio with 200% markup and honest production readiness.
**Architecture:** Retain FastAPI, SQLite, vanilla JavaScript, FFmpeg and one Railway web/worker service. Add focused modules for account lifecycle, new audio tools, operations and durable jobs without widening access to provider credentials.
**Tech Stack:** Python 3.12, FastAPI, SQLite, httpx, ElevenLabs SDK, FFmpeg.
**Spec:** docs/superpowers/specs/2026-10-05-production-audio-studio-design.md

## Global Constraints
- 200% markup means selling price = modeled cost × 3; default and minimum multiplier 3.0.
- Mongolian default navigation, validation, examples and help.
- One worker/service/replica while SQLite and artifacts are local.
- Paid provider, live Wire credentials and email sender remain external requirements; never invent keys or buy subscriptions.
- Existing account data must not be hidden by mounting an empty volume.
- Every generated artifact is authorized per user and every paid action is server-metered.

## Review Focus
- Cross-user voice/artifact references must fail before provider work.
- Ambiguous provider timeouts and worker restarts must not silently duplicate expensive work.
- Concurrent debit, retry and refund must preserve nonnegative balances and grant once.
- Deletion and cleanup must not remove active job input/output or orphan another user's files.
- Price displays must use server-calculated usage and return meaningful provider-plan errors.

## Task 1: Pricing, provider diagnostics and operations
Files: app/billing.py, app/engine.py, app/operations.py, tests/test_operations.py, tests/test_billing_wire.py, .env.example, README.md, requirements.txt.
Interfaces: operations.inspect_readiness() -> dict; backup_database(destination: Path) -> Path; cleanup_retained(now: float) -> dict.
- [ ] Write failing tests for markup default/floor 3.0, configured allowances, provider paid-plan error, consistent SQLite backup and active artifact cleanup exclusions.
- [ ] Run focused tests and confirm missing behavior.
- [ ] Implement 3.0 guard; diagnostics based on configuration/storage/worker heartbeat; safe backups and explicit retention; pin tested dependencies.
- [ ] Run full unittest suite and commit.

## Task 2: Account lifecycle and admin module
Files: app/accounts.py, tests/test_accounts.py, later server module registration.
Interfaces: register_routes(app, session, mutation_guard, throttle) adds /api/account, /api/account/password, /api/account/reset/request, /api/account/reset/confirm, /api/account/delete, /api/admin/overview.
- [ ] Write failing tests for one-use hashed reset tokens, enumeration-safe response, password/session invalidation, cross-user protection and explicit deletion confirmation.
- [ ] Implement SMTP-configured email sender, account routes, soft deletion and authenticated administration with no raw audio/secrets.
- [ ] Test without sending real mail; run account suite, full suite and commit.

## Task 3: New audio capabilities
Files: app/audio_extensions.py, tests/test_audio_extensions.py. No shared server edits until integration.
Interfaces: register_routes(app, session, mutation_guard, throttle, provider, allowed_voice_ids, charge, create_artifact_bytes, create_artifact_text) adds voice design preview/save, owned-voice remix preview/save, forced alignment, /api/tool-jobs/{id}, subtitle VTT conversion.
- [ ] Verify endpoint payloads against official provider documentation.
- [ ] Write failing tests for ownership, preview/save isolation, duration/text limits, conservative charging, output formats and provider failure refunds.
- [ ] Implement endpoints and outputs through existing shared storage/credit helpers.
- [ ] Run focused/full suites and commit.

## Task 4: Durable creative jobs and bounded realtime
Files: app/durable_jobs.py, app/worker.py, app/server.py, app/core.py, tests/test_durable_jobs.py.
Interfaces: enqueue_binary(user_id, tool_type, title, payload, upload_path, credits) -> job id; claim_next() -> row; run_tool_job(row) -> None; recover_interrupted() -> int.
- [ ] Test queued/running/done/failed transitions, restart uncertainty, single claiming, limits, refund once and cancellation safety.
- [ ] Move long-running binary creation to persistent uploads/job payloads and worker execution; expose per-user polling.
- [ ] Retain explicit provider workflows for dubbing/PVC. Bound realtime tokens using server-validated session/reservations.
- [ ] Test failure modes, full suite and commit.

## Task 5: Mongolian UI and integration
Files: app/static/index.html, app/static/app.js, app/static/style.css, server route registration, tests/test_production_integration.py.
Interfaces: existing api() helper, new queue polling, account routes, audio extension routes.
- [ ] Translate visible navigation, labels, account/help and status copy; retain exact API parameter names.
- [ ] Add design/remix/alignment, account settings/reset/admin, provider availability/cost/progress, VTT exports and complete history flows.
- [ ] Keep UI responsive, keyboard accessible and semantic; prevent duplicate form submissions.
- [ ] Verify browser desktop/mobile states and JS/Python syntax; test API routes and commit.

## Task 6: Review, release and external configuration
Files: docs/DEPLOY.md, docs/PRODUCTION.md, CI workflow.
- [ ] Run full suite, compilation, JS syntax and integration fixtures; review whole branch in fresh context and fix important findings with regression tests.
- [ ] Preserve existing deployment data before mounting storage; if export is unavailable, document a precise blocker instead of hiding data.
- [ ] Merge/deploy only verified code; turn metering on before paid public use.
- [ ] Verify public health/plans, login and provider errors. Paid-provider generation, live Wire payment and email/restore remain unverified until real credentials/plan are configured.
- [ ] Record exact completed work and external blockers; never label incomplete live verification as production complete.

