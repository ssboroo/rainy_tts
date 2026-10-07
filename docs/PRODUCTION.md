# Production operations

Production completion requires live paid-provider generation, signed live payment activation, email delivery, persistent storage and an isolated restore check. Offline tests and the readiness endpoint do not establish these facts.

## Required configuration

Run one service with one web process and one worker, one shared volume, and one replica. Start with `python -m app.railway`. Install Python 3.12, FFmpeg and the pinned requirements. Use HTTPS and set `PUBLIC_ORIGIN` to the actual domain.

Set `ELEVENLABS_API_KEY` from an eligible paid ElevenLabs account. `ELEVENLABS_PROVIDER_PLAN` is a cost-model declaration, not proof of entitlement; validate each enabled capability using a bounded real request. Free account shared-library errors explicitly require a paid plan. The operator must activate the plan; the application cannot do so.

Set `BILLING_ENABLED=true`, `BILLING_TARGET_MARKUP=2.2`, live `WIRE_MN_API_KEY`, and `WIRE_MN_WEBHOOK_SECRET`. Remove `sandbox` from `WIRE_MN_ALLOWED_OPERATORS` for live payments; use connected operator IDs or an empty value. Configure the gateway webhook at `https://YOUR_DOMAIN/api/billing/wire/webhook`. Verify a real payment's exact MNT amount and plan activation, then replay its signed event to confirm no duplicate grant.

Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` and `SMTP_TLS` for the selected transactional sender. Verify delivery and a single-use reset link without publishing secrets. Readiness checks configuration only; SMTP can be unauthenticated for a trusted relay, so credentials are not universally required.

Public packages sell exactly 1,500 / 6,400 / 16,000 / 40,000 credits. With verified Starter account data, at least five expected active users, FX 3700, 3% payment reserve, 10% overhead reserve, 10% FX buffer and observed factor 1, protected prices are 20,000 / 80,000 / 200,000 / 500,000 MNT. Prices grow with modeled cost while credit quantities remain fixed. The total-cost markup condition is P >= 2.2 * (provider cost + P * reserve), where reserve = 1 - .97*.90 = .127. Thus the pricing denominator is .7206, not .873. Reject nonpositive denominators. Existing subscriptions and paid quotes retain their stored allowances. Actual accounting profit depends on actual fees, taxes, hosting and upstream invoices.

## Preserve storage before attaching a volume

Mounting an empty `/data` can hide an existing data directory. Establish the current `DATA_DIR`, account counts, job counts and retained file inventory first. Do not classify real accounts or audio as disposable test data without evidence.

1. Pause registration and generation, drain or stop the worker, and stop writes. Keep the original storage available until validation is complete.
2. Run `python -m app.operations backup /export/studio.db`. This uses SQLite's backup API and refuses to overwrite an existing destination. Use a new export directory outside the mounted destination. Copy `outputs`, `artifacts`, `voices`, `tmp` and any persisted upload directories, preserving paths and permissions. Include queued-job inputs; do not include real environment secrets.
3. Transfer the verified database and file snapshot to encrypted off-host storage. Record file checksums and the `verify` row-count report. Export must succeed before mounting. If the platform cannot access the old filesystem, recovery is blocked; do not proceed with an empty mount.
4. Attach the volume at `/data`, restore `studio.db` and the retained directories, set `DATA_DIR=/data`, and give the runtime write permission. Railway's volume may require the documented `RAILWAY_RUN_UID=0` configuration.
5. Run `python -m app.operations verify /data/studio.db`. Compare row counts and checksums, then verify account access and representative authorized downloads. Start the service/worker and verify newly created data survives a redeploy.
6. Set `PERSISTENT_STORAGE_CONFIRMED=true` only after those checks. Keep the off-host snapshot and old data until migration acceptance.

## Backups and isolated restore

Run `python -m app.operations backup /backups/studio-YYYYMMDD.db` on the server with its configured `DATA_DIR`. Schedule this through the deployment platform or an operator-managed scheduler; this repository does not automatically configure an off-host backup service. The backup contains customer and billing data and must remain private.

The SQLite backup is consistent while the database is active. It does not snapshot media files atomically. For a full restore point, pause writes and drain workers while capturing the database and retained files together. Copy snapshots off-host with encryption and access controls.

Restore into a separate directory with no production traffic. Run `python -m app.operations verify /restore/studio.db`; it opens the database read-only and reports integrity, foreign-key violations and table row counts. Compare against the snapshot inventory, then start an isolated instance with `DATA_DIR=/restore`, nonproduction credentials and no real payment/provider calls. Verify accounts, ownership and downloads. The `verify` command deliberately never replaces the live database.

## Retention and monitoring

Cleanup runs only when `RETENTION_POLICY_ENABLED=true` and the operator explicitly invokes `python -m app.operations cleanup`. Default unreferenced-file ages are 30 days for outputs/artifacts and 7 days for temporary files. Override with `RETENTION_OUTPUTS_DAYS`, `RETENTION_ARTIFACTS_DAYS`, `RETENTION_TMP_DAYS`; zero or negative values disable that category. This conservative policy preserves all referenced job/artifact files, including completed history, all voice recordings, symlinks, and accounting records. User deletion is separate from retention. Monitor retained history growth and impose explicit storage quotas rather than silently deleting referenced customer audio.

`python -m app.operations readiness` checks configuration, database integrity, writable storage, persistent-storage confirmation and a fresh worker heartbeat. It returns no credentials and never performs expensive provider calls. `/api/health` is process liveness; readiness is separate. Worker heartbeats must remain fresh during long provider jobs; `WORKER_HEARTBEAT_MAX_AGE_SECONDS` defaults to 120.

Observe disk usage, failed/uncertain jobs, oldest queued jobs, provider quota and payment reconciliation. An ambiguous upstream timeout requires operator review before retrying an expensive request. Do not describe release as production complete until the live acceptance checks above succeed.

## Admin access

Admin uses the ordinary site login with an existing account. Configure `ADMIN_EMAILS` as a comma-separated list of verified operator account emails. Login and `/api/me` return the server-computed role; the Admin menu appears immediately. Provider status, shared voice synchronization and operational diagnostics are admin-only. Public registration cannot create an account whose email is already reserved by `ADMIN_EMAILS`; create and verify the intended operator account before adding it to the allowlist. Never accept a user-supplied admin flag.

Customer-facing payment text uses QPay as requested. The existing backend remains the Wire.mn hosted checkout integration; this UI change does not add or verify direct QPay API support. Live checkout remains unavailable until provider credentials and webhook acceptance are completed.

Admin testing: `ADMIN_TEST_MODE=true` lets authenticated `ADMIN_EMAILS` accounts exercise creative tools without RAINY credit reservations or local subscription/clone-slot requirements. It grants no customer credit and does not simulate payment success. Provider costs, provider plan limits, ownership verification and request/concurrency limits remain in force. Keep this disabled if operators should use normal billing.
# Admin account recovery

When reset email is unavailable, an operator can provision or recover an allowlisted admin using `ADMIN_BOOTSTRAP_EMAIL` and `ADMIN_BOOTSTRAP_PASSWORD_HASH` (the output of `core.hash_password`). Store the hash only in deployment secrets, never in source. Startup atomically creates the account or resets its password without changing its user ID, wallet or history, and invalidates existing sessions and reset tokens. Each hash applies once per database; subsequent password changes survive restarts. Remove both bootstrap variables after verifying access. A database lost on ephemeral storage is a separate persistence problem; this mechanism does not restore customer data.

## Live provider cost reconciliation

The admin overview includes the private provider account snapshot and header-cost reconciliation. Use the “ElevenLabs багц, үлдэгдэл шинэчлэх” admin button after changing the upstream plan. Snapshot refresh is read-only and never enables provider overage, upgrades subscriptions or charges the owner. Failed, stale, suspended or free snapshots block new checkout after integration is established. A configured API key with no verified snapshot also blocks checkout. Existing wallets and all pending quotes count against upstream remaining capacity; abandoned pending quotes are retained conservatively until the provider order is cancelled/reconciled. Do not remove reservations for payable payment intents.

Provider credit-to-USD conversion is a conservative allocation estimate, not a request invoice. Verify recurring quota, currency, taxes and actual marginal overage charges against invoices before enabling extra spending. Current code does not assume a quoted overage rate or allow speculative overage sales. Public plan allowances may change for new orders after account sync or a higher observed cost factor. Sold orders retain their quoted credit allowance.
