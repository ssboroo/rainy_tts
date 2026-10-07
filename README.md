# RAINY Voice Studio

RAINY is a Mongolian-first creative audio studio built on ElevenLabs APIs.

## Tools

- **Text to Speech** — Eleven v4 or v4 Turbo, 12 built-in Mongolian voices, clone voices, Text/SRT, WAV + MP3, provider request/cost metadata.
- **Instant Voice Clone** — from 1–10 consented audio samples.
- **Professional Voice Clone (PVC)** — Mongolian PVC draft, samples, ownership CAPTCHA verification, training and readiness tracking.
- **Podcast / Dialogue** — multi-speaker Text to Dialogue with up to 10 unique voices per generation.
- **Music** — Music v2.5 by default, v2/v1 selector, instrumental mode, 3 seconds to 10 minutes.
- **Sound Effects** — Sound Effects v2 with duration, seamless loop and prompt-influence controls.
- **Speech to Text** — Scribe v2 batch transcription with TXT, JSON and SRT artifacts.
- **Realtime STT** — browser microphone to Scribe v2 Realtime using a server-issued single-use token, with transcript save to History.
- **Voice Isolator** — remove background noise/ambience from uploaded audio or video.
- **Voice Changer** — uploaded speech transformed to a selected ElevenLabs voice; Mongolian source speech remains experimental because the current STS v2 supported-language list does not include Mongolian.
- **Dubbing / Movie** — Dubbing v2 from upload or public URL; uploaded video can be muxed with the completed dubbed audio into MP4.
- **Voice Library** — 12 Mongolian voices plus user-created clones with preview.
- **Analytics** — ElevenLabs subscription/usage plus local RAINY 30-day usage.
- **Reception.ai** — per-user webhook URLs for lead capture, messages, quote requests and phone orders.
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

Copy `.env.example` to `.env`, or keep local secrets in `.env.local`. RAINY loads `.env.local` first and then `.env`:

```env
PUBLIC_ORIGIN=http://localhost:8080
PUBLIC_ORIGINS=
ALLOW_REGISTRATION=true
ELEVENLABS_API_KEY=your_server_side_key
ELEVENLABS_VOICES_JSON=
ELEVENLABS_LANGUAGE_CODE=mn
ELEVENLABS_TTS_MODEL=eleven_v4
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


## Registration / origin configuration

Registration and other write operations use same-origin + CSRF protection. RAINY accepts the origin the browser is actually using, and treats `localhost` / `127.0.0.1` as local aliases on the same port. For multiple production domains, add them to `PUBLIC_ORIGINS` as a comma-separated list.

Example:

```env
PUBLIC_ORIGIN=https://voice.example.com
PUBLIC_ORIGINS=https://www.voice.example.com
ALLOW_REGISTRATION=true
```

If registration is intentionally closed, keep `ALLOW_REGISTRATION=false`.


## Direct ElevenLabs smoke test

To verify the API key and a configured voice independently from the web UI and worker:

```powershell
.\.venv\Scripts\python.exe scripts\test-elevenlabs.py
```

This writes `elevenlabs-test.mp3` using the first RAINY Mongolian voice ID and `eleven_v4`.

For Mongolian generation, do not switch the default to `eleven_multilingual_v2`. ElevenLabs currently documents Multilingual v2 as a 29-language model that does not include Mongolian, and its Text-to-Speech API notes that `language_code` is ignored for Multilingual v2. RAINY therefore uses `eleven_v4` with `language_code=mn`.

The built-in voice IDs are passed directly to the ElevenLabs SDK. The Voice Library sync control is optional and is only a fallback for accounts that require saving a shared voice into the workspace.


## RAINY subscriptions, credits and Wire.mn

RAINY can meter customer usage with its own credits while keeping the ElevenLabs API key private.

Default customer plans are:

| Plan | Price | Protected monthly credits* | Clone slots |
| --- | ---: | ---: | ---: |
| Сонирхогч (Hobby) | ₮20,000 | 1,500 | 1 |
| Pro | ₮80,000 | 6,400 | 5 |
| Studio | ₮200,000 | 16,000 | 10 |
| Agency | ₮500,000 | 40,000 | 20 |

* Public credit quantities are fixed. Prices above assume a verified active Starter account, FX 3,700, 3% payment reserve, 10% overhead reserve, 10% FX buffer and observed cost factor 1.0. Prices are rounded up in 5,000 MNT steps and automatically increase when modeled cost rises. For total-cost markup, `price >= 2.2 × (provider_cost + price × reserve_fraction)`, with `reserve_fraction = 1 − (1 − payment_fee) × (1 − overhead_reserve)`. This gives a denominator of 0.7206 at default reserves. Configurations with a nonpositive denominator are not sold. The 120% markup target covers modeled costs and reserves, not guaranteed accounting profit. Existing sold quotes retain their amount and credit quantity. Stale/missing provider snapshots use the more conservative additive model. Legacy Starter/Creator IDs remain for old records and are not shown for sale.

Provider account reconciliation now refreshes `/v1/user/subscription` every five minutes server-side. Admins can force refresh and see sanitized tier, remaining quota, reset time, monthly cost basis and measured request-credit allocation. Recurring price floors exclude first-month discounts; rollover does not dilute the quota denominator. Header `character-cost` values are provider credits, not USD. Their USD allocation is an estimate using the recurring subscription quota; higher measured cost increases the conservative credit-budget factor, never reduces the normal API floor. Admin TTS test samples also calibrate the factor without debiting the admin wallet.

With a fresh active paid account, included provider usage and the base subscription are allocated once as `max(shared base allocation, budgeted usage cost)`. Without verified fresh account data, the older additive conservative budget remains. This is a modeled 120% markup target, not an accounting-profit guarantee. No automatic overage purchase is enabled. Checkout reserves all current wallets, pending order quotes and queued/recent usage against included remaining capacity. Quotes freeze the promised credits at order creation; activation honors that quote. Insufficient or unverified capacity stops new checkout. Existing subscriptions are not rewritten by account refresh. Requests without usage headers remain priced by normal conservative API rates.

Usage rates currently modeled from ElevenAPI public API rates:

- Eleven v4 / v3 / Multilingual v2: 80 RAINY credits per 1,000 characters.
- v4 Turbo / v3 Conversational / Flash / Turbo: 40 credits per 1,000 characters.
- Scribe v1/v2/Medical STT: 220 credits per hour.
- Scribe v2 Realtime: 390 credits per hour.
- Speech Engine / Agents: 80 credits per minute.
- Music: 150 credits per minute, up to 10 minutes.
- Voice Isolator / Voice Changer: 120 credits per minute.
- Sound Effects: 120 credits per generation.
- Dubbing v1: 330 credits per minute.
- Dubbing v2: 2,200 credits per source minute.
- Instant Voice Clone: 1,000-credit platform charge plus plan clone-slot limits.

The temporary Eleven v4 promotion through October 12, 2026 ($0.022/1K for v4 and $0.011/1K for v4 Turbo) is intentionally not passed through to RAINY customer rates. RAINY bills against the normal $0.08/$0.04 list prices so the promotion becomes extra temporary margin and customer pricing remains safe after it expires.

Shared Voice Library voices may have a provider credit multiplier. RAINY requests the current shared-voice `rate`, caches it, and multiplies customer credit usage accordingly. If the provider rate cannot be retrieved, `BILLING_UNKNOWN_VOICE_MULTIPLIER` is used as a conservative fallback.

Fresh registrations receive zero free generation credits by default. Set `BILLING_TRIAL_CREDITS` above zero only when you intentionally want to fund a promotional trial.

Wire.mn payment flow:

1. Customer selects a paid RAINY plan.
2. Server creates a Wire.mn PaymentIntent with a stable `Idempotency-Key`.
3. Customer is sent to Wire hosted checkout.
4. RAINY accepts only a valid signed `WirePayment-Signature` webhook (HMAC-SHA256, 5-minute tolerance), or server-side status polling.
5. Before activating the subscription RAINY retrieves the PaymentIntent from Wire and verifies **paid status + exact MNT amount + currency**.
6. Subscription and monthly credits are activated atomically. Duplicate webhook deliveries do not grant credits twice.

Configure:

```env
BILLING_ENABLED=true
BILLING_USD_MNT_RATE=3700
BILLING_TARGET_MARKUP=2.2
ELEVENLABS_PROVIDER_PLAN=pro
BILLING_EXPECTED_ACTIVE_USERS=100
BILLING_FIXED_COST_PER_ACTIVE_USER_USD=1.25
BILLING_PAYMENT_FEE_PERCENT=3
BILLING_OVERHEAD_RESERVE_PERCENT=10
BILLING_FX_BUFFER_PERCENT=10
BILLING_UNKNOWN_VOICE_MULTIPLIER=2.0
BILLING_TRIAL_CREDITS=0

WIRE_MN_API_URL=https://api.wire.mn/v1
WIRE_MN_API_KEY=
WIRE_MN_WEBHOOK_SECRET=
WIRE_MN_ALLOWED_OPERATORS=sandbox
```

For live Wire keys, do not keep `sandbox` in `WIRE_MN_ALLOWED_OPERATORS`. Use connected live operator IDs or leave the value empty if Wire should select the connected operator.

Scale the shared ElevenLabs backend by active paying users and actual usage: roughly Starter for up to 5 users, Creator for up to 20, Pro for up to 100, Scale for up to 300, and Business for up to 1,000. These thresholds intentionally keep fixed provider subscription cost near ~$1 per active user before usage. If the average customer consumes more than the included provider credits imply, enable PAYG or move up earlier. Keep provider credentials and PAYG controls server-side. Customer RAINY credit pricing remains independent of the provider subscription tier.

This margin guard protects modeled gross unit economics; it cannot guarantee accounting profit because taxes, refunds, chargebacks, infrastructure, support, changing provider prices and actual payment fees can differ from the configured reserves.


## Mongolian Speech-to-Text accuracy

RAINY uses Scribe v2 with `language_code=mn` by default. For higher-quality Mongolian transcripts it supports:

- user-supplied **keyterms** for names, brands and technical words,
- deterministic low-temperature transcription,
- optional speaker diarization only when there are multiple speakers,
- `no_verbatim` cleanup for filler words and false starts,
- optional transcript editing that explicitly keeps the text in Mongolian, does **not translate**, and only corrects obvious spelling, punctuation and formatting.

Keyterm prompting adds 20% to the upstream STT cost. Transcript editing adds 30% and has a minimum 10-second billable duration. RAINY includes these surcharges in customer credit usage so the margin guard remains intact.

When transcript editing succeeds, `transcript.txt` contains the polished Mongolian text and `transcript-raw.txt` preserves the original Scribe result. SRT timestamps remain based on the original word-aligned transcript.


## Reception.ai integration

Open **Business AI → Reception.ai** inside RAINY and click **Integration URL авах**. RAINY creates per-user webhook URLs for:

- `create_lead`
- `take_message`
- `request_quote`
- `create_order`

In Reception.ai open **Integrations → Webhook**, create a POST webhook for each tool, paste the matching RAINY URL, describe when the receptionist should call it, and define the body parameters you want Reception.ai to collect from callers. The URL contains an unguessable per-user token. Rotating the token in RAINY immediately invalidates the old URLs.

Reception.ai remains the system that handles calls, phone numbers, its own scheduling and receptionist configuration. RAINY acts as the connected business-data/tool layer for custom workflows.

## Professional Voice Clone

RAINY's PVC flow is intentionally owner-only:

1. Create a Mongolian PVC draft.
2. Upload voice samples.
3. Retrieve the ElevenLabs ownership CAPTCHA.
4. Record the voice owner reading the CAPTCHA and submit it.
5. Start training.
6. Poll status; when verification + fine-tuning are complete, RAINY automatically adds the voice to the user's Voice Library.

ElevenLabs PVC requires an eligible provider plan and only permits Professional Voice Cloning of the user's own voice.

## Provider cost metadata

TTS uses the ElevenLabs raw SDK response and persists the provider `character-cost`, `request-id`, and `x-trace-id` headers with the completed job. Voice Isolator also persists request/trace IDs. These values are available through RAINY analytics/history data for auditing actual upstream requests without exposing the ElevenLabs API key.


## Railway deployment

RAINY uses SQLite-backed queues and local artifacts, so on Railway the web process and background worker run inside the **same service/container** through `python -m app.railway`. This lets both processes share one persistent volume.

Recommended Railway setup:

1. Deploy this GitHub repository as one service. Railway will build the included Dockerfile.
2. Before mounting storage, preserve the existing database and files using the migration procedure in `docs/PRODUCTION.md`. Add a Railway Volume to the same service and mount it at `/data`.
3. The Docker bootstrap repairs `/data` volume ownership and drops to the non-root `studio` account before starting the web process and worker. Do not force `RAILWAY_RUN_UID=10001` before this bootstrap on a new root-owned volume. Confirm the application runtime UID is 10001 after deployment.
4. Set `DATA_DIR=/data` and `HOST=0.0.0.0`. Railway supplies the public `PORT` variable automatically; the app also defaults to 8080.
5. Set `PUBLIC_ORIGIN=https://YOUR_DOMAIN` after Railway or your custom domain is active.
6. Configure the ElevenLabs, billing and Wire.mn secrets as service variables. Never expose them in the frontend.
7. Set the Railway healthcheck path to `/api/health`.
8. Under Networking, generate a Railway domain first, then attach your custom domain when ready.

Do **not** create a separate worker service while RAINY is still using SQLite + local `/data`; separate Railway services do not share the same attached volume. Move the queue/database to PostgreSQL/object storage before splitting web and worker into separate services.

## Production verification

Metering defaults to enabled, and markup defaults to a minimum 2.2 multiplier (120% markup). Configure a paid eligible ElevenLabs account, live Wire credentials and transactional SMTP before launch. Read [production operations](docs/PRODUCTION.md) for preservation, backup/restore and readiness. Configuration checks do not establish successful live payments, mail delivery or generation.


### Expressive voice and video voiceover

Eleven v4 emotion presets work in TTS/SRT and per dialogue speaker. `/api/jobs/quote` includes prepared text, inserted tags and the selected voice multiplier without charging or queuing. Long-form segments carry adjacent-text context. From a completed TTS history item choose **Видеонд оруулах**, upload a video of at most 10 minutes, and receive a durable MP4 history artifact. The source sound is replaced; short narration is padded so the video retains its full duration, while narration longer than the video is rejected. Local rendering reserves 10 credits per started minute, minimum 10, and does not call TTS again.

The worker keeps seven daily SQLite snapshots in `/data/backups`; an interrupted snapshot is detected and repaired. These same-volume snapshots cover the database and cannot replace an off-site backup of media. See [the dated audit](docs/PRODUCTION_AUDIT_2026-10-06.md) for validated behavior and remaining launch requirements.
