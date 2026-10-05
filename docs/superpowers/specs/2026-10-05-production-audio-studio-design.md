# RAINY Монгол аудио студи — production design
Date: 2026-10-05
Status: Written design awaiting user review; implementation has not been completed.

## 1. Agreed outcome
RAINY is a paid, Mongolian-first audio studio for content creators, small businesses, educators and audio professionals. The user selected the full audio studio scope. It includes all practical audio creation/editing capabilities from ElevenLabs: speech, voice cloning/design/remixing, dialogue, music, sound effects, transcription, realtime transcription, isolation, voice changing, dubbing and subtitle alignment. Telephone agents and image/video generation are outside this selected scope; uploading video for dubbing is included.

The user requires 200% markup. Selling price equals modeled cost × 3. This is different from a 200% margin. The pricing system must preserve at least three times modeled cost after the configured payment and overhead reserves. Provider cost, FX and payment fees remain configuration inputs, not guarantees about accounting profit.

## 2. Current verified state
- FastAPI backend, SQLite, server-side ElevenLabs SDK/HTTP adapter, vanilla JS frontend and FFmpeg.
- Railway runs web and worker together through app.railway.
- TTS SDK context-manager handling fixed in PR #2 and deployed.
- 39 unit tests passed for that fix; GitHub CI passed.
- Provider authentication works, but the connected account rejects built-in shared voices with paid_plan_required.
- Railway has no persistent volume. Existing filesystem data must be preserved before attaching a new storage mount.
- Wire credentials and webhook secret were absent in the inspected service variables.
- BILLING_ENABLED was absent; code defaults to unmetered behavior. This must be corrected before a paid public launch.
- Most existing creative tools run inside the HTTP request rather than a durable worker queue.
- Password recovery, account deletion, voice design/remix and forced alignment are missing.
- Several visible navigation labels remain English.
- Realtime token billing needs bounded session accounting; client-submitted durations cannot be trusted.
- Railway runtime BILLING_TARGET_MARKUP has been set to 3.0. Default source configuration still needs updating.

## 3. User experience
Keep the existing site identity and build a polished responsive Mongolian interface. Mongolian is the default for navigation, help, validation, errors and payment screens; provider model IDs are retained only in relevant advanced settings.
Navigation groups:
1. Дуу бүтээх: text to speech, podcast/dialogue, music, sound effects.
2. Хоолой: voice library, instant clone, professional clone, voice design, voice remix.
3. Аудио боловсруулах: STT, realtime STT, noise isolation, supported-language voice changing.
4. Видео ба хадмал: dubbing, forced alignment, subtitle export.
5. Миний студи: history, credits/subscription, account.
Each tool has a Mongolian explanation, realistic sample input, format/size/duration limits, cost estimate, provider availability, progress, retry guidance, preview and downloads.
Examples target Mongolian ads, reels, lessons, audiobooks, interviews and business presentations. No unsupported language capability is promised. Provider plan or language restrictions are shown before users start an expensive job.

## 4. Capability requirements
| Capability | Required behavior |
| --- | --- |
| TTS | Mongolian voices, verified model/language settings, speed and pronunciation controls, text/SRT input, WAV/MP3, bounded long-text chunking |
| Dialogue | Multiple named speakers, voice selection, reorder/edit script, MP3 output |
| Instant clone | Ownership/consent affirmation, sample validation, per-user ownership and slot limits |
| Professional clone | Owner verification, samples, CAPTCHA handoff, training status and entitlement checks |
| Voice design | Prompt and sample text, audio previews, choose and save a generated voice to the user's library |
| Voice remix | Owned voice selection, supported prompt transformations, preview and explicitly save a new voice |
| Music | Prompt, supported duration/model, instrumental controls and downloadable audio |
| SFX | Prompt, duration/loop controls and downloadable audio |
| STT | Mongolian default, custom vocabulary, speaker labels, editable transcript, original transcript preserved, TXT/JSON/SRT/VTT |
| Realtime STT | Microphone start/stop, permission handling, live transcript, server-bounded provider session, history save |
| Isolation | Uploaded audio/video, validated duration, extracted speech preview and download |
| Voice changer | Supported source-language guidance and owned/shared target voices |
| Dubbing | Upload or validated public URL, source/target language, tracked provider job, audio/video output, subtitles where supported |
| Forced alignment | Uploaded audio + user transcript, word timings, SRT/VTT without falsely describing it as transcription |
| Library/history | User-owned records, accessible preview, download, clear failed-job status, pagination and deletion |

Endpoint paths, payloads, model support, plan entitlements and pricing for new capabilities must be checked against official ElevenLabs documentation before implementation. Unsupported endpoints stay unavailable with a clear explanation rather than being represented as working tools.

## 5. Architecture and boundaries
Retain FastAPI and existing authentication routes. Organize new code around provider adapters, job execution, pricing, storage, account lifecycle and administrative reporting.
Use the current single-service Railway architecture for the initial launch: one web process and one worker, one persistent volume, one SQLite database in WAL mode. Do not split services or add replicas while database/artifacts remain local.
Extend a durable job system for long-running creative jobs. Queue records include user, capability, validated payload, status, timestamps, provider request ID, charge/reservation ID and result artifacts. Large files are persisted privately; queue payloads contain references rather than raw blobs.
Job states: queued → running → completed/failed/cancelled. Provider dubbing/PVC states are tracked separately. Cancellation after an upstream request starts does not promise cancellation of provider charges.
Retries are limited to known retryable failures. Do not blindly repeat an expensive provider generation after an ambiguous timeout. Record request IDs and mark uncertain charges for operator review.
Artifacts require per-user authorization; output paths are server-generated. Inputs, temporary files and retained outputs have documented retention and storage limits.

## 6. Pricing and payment
Keep the current plan price ladder initially, recalculate allowances at markup multiplier 3.0 and publish the actual dynamic allowance. Under current assumptions:
| Plan | Monthly price MNT | Monthly RAINY credits |
| --- | ---: | ---: |
| Starter | 39,900 | 1,600 |
| Creator | 69,900 | 3,700 |
| Pro | 139,900 | 8,700 |
| Studio | 259,900 | 17,300 |
| Agency | 499,900 | 34,400 |
These budgets use the existing modeled costs and may change when provider rates, fixed cost allocation, FX or reserves change. RAINY credits are not ElevenLabs workspace credits.
Default and minimum target markup become 3.0; tests verify every published paid plan covers at least 3× modeled total cost. Keep trial generation at zero unless explicitly funded.
Update pricing for every supported capability and provider surcharge; include shared-voice multipliers. Cost display uses the same validated inputs and pricing code as charging.
Reserve credits atomically before provider work, prevent negative balances and duplicate charges, finalize on completion and refund once on known failure before useful output. Record manual adjustments in an auditable ledger.
Wire checkout uses server-created payment intents, stable idempotency keys and a signed webhook. Verify exact amount/currency/paid state server-side before atomically granting the plan once. Never activate using browser success redirects.
Subscription lifecycle includes expiry, renewal rules and plan changes without granting duplicate monthly credits. Existing paid allowances are not silently reduced mid-cycle.
Realtime usage must be bounded by server-issued authorization and reconciled from authoritative provider usage when available. Otherwise reserve the full permitted window and disclose the billing basis; no unrestricted token issuance.

## 7. Accounts, administration and security
Add account settings, password change, password reset via a configured transactional email provider, and account deletion with explicit confirmation and documented handling of billing records and provider-owned clones.
Reset tokens are single use, short lived and stored hashed. Requests return a generic response to avoid account enumeration; sensitive account changes invalidate sessions.
Maintain HttpOnly secure cookies, same-origin/CSRF validation, per-user artifact authorization and server-only credentials.
Add structured admin access through configured roles/emails, with usage/cost summaries, job errors, reconciliation and storage/provider health. Never expose provider keys or raw customer audio to unrelated users.
Validate media content as well as extensions, enforce upload/duration quotas and add subprocess timeouts. Provider URL fetches must reject internal/private destinations and revalidate redirects.
Avoid logging secrets, cookies, clone recordings or full customer transcripts. Keep operational IDs and safe error classifications.

## 8. Deployment and data protection
Before adding a volume, establish whether non-test data exists and export the SQLite database and retained files consistently. Restore them into the volume and verify row counts/artifact availability before switching traffic.
Configure DATA_DIR=/data, correct volume permissions, /api/health, supervisor startup and one replica. Readiness must report worker/database/storage status without leaking secrets.
Schedule backups using SQLite's backup API, copy retained artifacts to off-host storage and verify a restore into an isolated test environment.
Enable billing before public paid use; require live Wire credentials and a paid eligible ElevenLabs account. Do not purchase provider plans or fabricate secrets.
Dependencies should be pinned to tested versions; CI runs full tests, syntax checks and relevant integration fixtures.
Observe disk consumption, failed jobs, oldest queued job, payment reconciliation, provider quota and abnormal credit spending.

## 9. Validation and release acceptance
- Mongolian account registration/login/logout, reset/change/delete flows verified.
- TTS generates a real Mongolian WAV and MP3 and both downloads work.
- Each enabled tool has a successful provider smoke test with bounded test input and valid output inspection.
- Unsupported source languages, insufficient credits and missing plan permissions have accurate Mongolian errors.
- Queue restart/recovery, concurrency, failed/ambiguous requests and duplicate webhook deliveries tested.
- Cross-user reads/downloads and forged payment confirmations rejected.
- Storage survives redeployment; backup restore succeeds.
- Plan budgets meet 200% markup under explicit cost assumptions.
- Desktop/mobile flows checked for readable labels, accessible controls, progress and error recovery.
- Public release is only labeled complete when live payment, paid-provider generation and storage/restore checks pass. Mock-based tests alone do not establish production readiness.

## 10. Implementation order
1. Storage/data preservation, pricing guard, billing enablement, provider diagnostics and deployment checks.
2. Durable creative-job queue and trustworthy credit lifecycle.
3. Mongolian UI and complete existing tool flows.
4. Voice design/remix and forced alignment; integrate shared library/history/credits.
5. Account lifecycle, email configuration and administration.
6. Full integration, mobile/accessibility, payment and backup/restore checks; release.

## 11. External inputs
The owner must activate an eligible paid ElevenLabs plan, configure live Wire API/webhook credentials, and select/configure a transactional email sender. These are external setup requirements; code and offline checks can continue independently after the design is approved.

