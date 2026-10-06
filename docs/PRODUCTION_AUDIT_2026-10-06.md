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

114 offline tests passed, including real FFmpeg video rendering, 40 simultaneous queue attempts (exactly 3 accepted, 30 credits debited), quote/charge agreement, user ownership, unknown provider outcome and local-render refunds. Python compilation and JavaScript syntax checked. Provider requests are mocked in automated tests. These results do not prove live voice quality, paid-plan entitlements, real payment webhooks, SMTP delivery or internet-scale throughput.

History is user-scoped in SQLite; audio/video remain on DATA_DIR. Permanent retention still requires an attached persistent volume, a backup of both database and artifacts, and a restore drill. A consistent pre-migration SQLite + DATA_DIR backup was downloaded and its integrity verified (1 user, 0 jobs/artifacts). Railway volume 50afb444-73b3-4d25-a508-75565dcb049f is attached at /data. The original SQLite database was restored with matching user identities and integrity check ok; the voice catalog and migration archive are retained on the volume. Runtime UID 10001 and os.path.ismount(/data)=True were checked in the live container. Daily SQLite snapshots keep seven days on this same volume; these do not substitute for an off-site backup of audio/video. Railway platform backups/PITR are unavailable on the current Railway plan (Pro required). Never mount an empty volume over existing /data without exporting current data first. Current deployment uses a single serial worker; scale requires capacity measurements and a different shared storage/queue architecture.

Actual invoices, taxes, failed requests, current exchange rates, retention costs, support and the actual number of paying customers can exceed assumed reserves. Reconcile provider usage headers/request IDs with invoices. Do not automatically refund an accepted or uncertain dubbing project: creation prepays at least its first language. Admin review must determine the outcome.

## Official references reviewed

- https://elevenlabs.io/docs/api-reference/text-to-speech/convert
- https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices
- https://elevenlabs.io/docs/api-reference/dubbing/create-project
- https://elevenlabs.io/pricing/api

Tags depend on voice training and delivery. Eleven v4 does not use SSML break tags. Emotion presets are direction tags, not an LLM that rewrites the script. Continuity and tags improve control but require listening tests in Mongolian. Additional ElevenLabs image/video/agent products are not advertised as enabled merely because they exist: access, metering and pricing must be verified before exposing them as paid customer tools.

## Live configuration verification

The real ElevenLabs subscription API returned Starter / active. Payment (Wire live credentials + webhook secret) and SMTP are absent, so production readiness remains false. The provider plan is set to starter; expected active paying users to 1 for conservative launch economics, and the paid-plan verification flag to true after this read-only API check. Existing plan prices stay fixed; plans below the protected cost floor are hidden. Reassess allowances when provider tier, invoice rates, hosting expenses or active customers change. No payment or email delivery has been verified.

A bounded real Eleven v4 request with a happy audio tag, Mongolian narration and adjacent-text context returned a valid 24 kHz WAV, 2.96 seconds long. This verifies the real TTS transport/PCM path; it is not a listening-based guarantee of accent, expression or every tool entitlement.
