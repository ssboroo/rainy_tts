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
| Starter | ₮39,900 | ~3,000 | 1 |
| Creator | ₮69,900 | ~6,200 | 2 |
| Pro | ₮139,900 | ~13,700 | 5 |
| Studio | ₮259,900 | ~26,600 | 10 |
| Agency | ₮499,900 | ~52,300 | 20 |

\* Credit budgets are calculated at runtime, not hard-coded. The default multi-user model uses a shared ElevenLabs backend, allocates a conservative $1.25 fixed provider cost per active paying user, reserves 3% for payment processing, 10% for hosting/support overhead, 10% for FX movement, and requires at least 2× coverage of modeled total cost. This is 100% markup on modeled cost, equivalent to roughly 50% gross margin before taxes/refunds/chargebacks. Change `BILLING_USD_MNT_RATE` when the operating FX assumption changes; plan credit allowances automatically adjust downward or upward to preserve the margin floor.

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
BILLING_TARGET_MARKUP=2.0
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
