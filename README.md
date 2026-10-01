# RAINY Voice Studio

RAINY is a Mongolian-first creative audio studio built on ElevenLabs APIs.

## Tools

- **Text to Speech** — Eleven v4, 12 built-in Mongolian voices, clone voices, Text/SRT, WAV + MP3.
- **Voice Clone** — Instant Voice Clone from 1–10 consented audio samples.
- **Podcast / Dialogue** — multi-speaker Text to Dialogue with up to 10 unique voices per generation.
- **Music** — Music v2.5 by default, v2/v1 selector, instrumental mode, 3 seconds to 5 minutes.
- **Sound Effects** — Sound Effects v2 with duration, seamless loop and prompt-influence controls.
- **Speech to Text** — Scribe v2 batch transcription with TXT, JSON and SRT artifacts.
- **Realtime STT** — browser microphone to Scribe v2 Realtime using a server-issued single-use token, with transcript save to History.
- **Voice Changer** — uploaded speech transformed to a selected ElevenLabs voice.
- **Dubbing / Movie** — Dubbing v2 from upload or public URL; uploaded video can be muxed with the completed dubbed audio into MP4.
- **Voice Library** — 12 Mongolian voices plus user-created clones with preview.
- **Analytics** — ElevenLabs subscription/usage plus local RAINY 30-day usage.
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
| Starter | ₮29,900 | ~3,200 | 1 |
| Creator | ₮59,900 | ~6,400 | 2 |
| Pro | ₮129,900 | ~13,900 | 5 |
| Studio | ₮249,900 | ~26,800 | 10 |

\* Credit budgets are calculated at runtime, not hard-coded. With the default guard RAINY reserves 3% for payment processing, 10% for hosting/support overhead, 10% for FX movement, and requires at least 2× coverage of modeled upstream API cost. Change `BILLING_USD_MNT_RATE` when the operating FX assumption changes; plan credit allowances automatically adjust downward or upward to preserve the margin floor.

Usage rates currently modeled from ElevenAPI public API rates:

- TTS / Dialogue: 100 RAINY credits per 1,000 standard-rate characters.
- Scribe v2 STT: 220 credits per hour.
- Realtime STT: 100 credits per 15-minute token window.
- Music: 150 credits per minute.
- Voice Changer / Sound Effects: 120 credits per minute.
- Dubbing v2: 2,200 credits per source minute.
- Instant Voice Clone: 1,000-credit platform charge plus plan clone-slot limits.

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

Recommended ElevenLabs provider setup for an early commercial launch is **Starter ($6/month) + PAYG/top-ups**. Voice Library API access is not available to free-tier users, and a PAYG balance does not remove subscription-tier voice-slot/API restrictions. Starting on the lowest paid tier minimizes fixed cost; move to Creator/Pro/Scale only when concurrency, custom-voice slots or other plan limits require it. Keep provider credentials and PAYG controls server-side. Customer RAINY credit pricing remains independent of the provider subscription tier.

This margin guard protects modeled gross unit economics; it cannot guarantee accounting profit because taxes, refunds, chargebacks, infrastructure, support, changing provider prices and actual payment fees can differ from the configured reserves.
