# RAINY production review — 2026-10-06

Implemented: volume ownership repair followed by privilege drop to studio before server/worker startup; validated Eleven v4 emotion directions for TTS/SRT and per dialogue speaker; adjacent-text continuity; quotes based on actual prepared and tagged segments; atomic TTS wallet reservation and queue limit; durable local video voiceover from an owned, completed TTS job; full-length MP4 padding and fast-start; dubbing v2 keyterms; unknown provider outcomes retain reservations for reconciliation. Dubbing downloads are serialized per project in the single server process and terminal polling does not redownload.

## Cost basis

Retail plan allowances use the existing protected budget (minimum 3x markup, payment/hosting/FX reserves and allocated provider subscription). Rates use ordinary provider list prices rather than temporary discounts. Voice Library custom multipliers also apply. This is modeled unit-cost protection, not a promise of net profit.

| Tool | Reserved RAINY credits | Basis / limitation |
|---|---:|---|
| TTS v4 / Turbo | 80 / 40 per 1,000 sent characters | Rounded up; includes inserted emotion tags; voice multiplier |
| Dialogue v4 | 80 per 1,000 characters | Emotion tags and each speaker's voice multiplier |
| STT / realtime | 220 / 390 per hour | Uploaded duration or bounded realtime reservation |
| Music | 150 per minute | Requested duration |
| Voice changer / isolation | 120 per minute | Probed input duration |
| Sound effect | 120 per generation | Conservative platform reserve; not a duration-based provider price |
| Dubbing v2 | 2,200 per minute | Uploaded duration; project creation incurs minimum language charge before output |
| Voice design / remix | At least 1,000 per preview request | Conservative reserve for previews; not verified exact provider invoice |
| Alignment | Higher of STT and isolation estimates | Conservative platform reserve |
| Video voiceover | 10 per started minute, minimum 10 | Local rendering reserve; no additional TTS request; max 10 minutes |

## Validation and limits

111 offline tests passed, including real FFmpeg video rendering, 40 simultaneous queue attempts (exactly 3 accepted, 30 credits debited), quote/charge agreement, user ownership, unknown provider outcome and local-render refunds. Python compilation and JavaScript syntax checked. Provider requests are mocked in automated tests. These results do not prove live voice quality, paid-plan entitlements, real payment webhooks, SMTP delivery or internet-scale throughput.

History is user-scoped in SQLite; audio/video remain on DATA_DIR. Permanent retention still requires an attached persistent volume, a backup of both database and artifacts, and a restore drill. A consistent pre-migration SQLite + DATA_DIR backup was downloaded and its integrity verified (1 user, 0 jobs/artifacts). Railway volume attachment has been staged; deployment and restore verification are tracked separately. Never mount an empty volume over existing /data without exporting current data first. Current deployment uses a single serial worker; scale requires capacity measurements and a different shared storage/queue architecture.

Actual invoices, taxes, failed requests, current exchange rates, retention costs, support and the actual number of paying customers can exceed assumed reserves. Reconcile provider usage headers/request IDs with invoices. Do not automatically refund an accepted or uncertain dubbing project: creation prepays at least its first language. Admin review must determine the outcome.

## Official references reviewed

- https://elevenlabs.io/docs/api-reference/text-to-speech/convert
- https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices
- https://elevenlabs.io/docs/api-reference/dubbing/create-project
- https://elevenlabs.io/pricing/api

Tags depend on voice training and delivery. Eleven v4 does not use SSML break tags. Emotion presets are direction tags, not an LLM that rewrites the script. Continuity and tags improve control but require listening tests in Mongolian. Additional ElevenLabs image/video/agent products are not advertised as enabled merely because they exist: access, metering and pricing must be verified before exposing them as paid customer tools.
