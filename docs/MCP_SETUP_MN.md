# RAINY Voice Studio — ChatGPT / Claude Remote MCP

## Two independent sites

RAINY Voice and RAVS Video remain separate websites with separate accounts, databases, credits and upstream API credentials. ChatGPT/Claude can orchestrate them in one conversation only after the user connects and authorizes BOTH MCP apps independently.

Voice MCP URL: https://rainytts-production.up.railway.app/mcp
Video MCP URL: https://rainyaivideostudio-production.up.railway.app/mcp

## Railway setup

1. Deploy this branch after CI verification; set PUBLIC_ORIGIN to the verified HTTPS Voice website origin.
2. Verify a persistent DATA_DIR SQLite volume and current app/worker health.
3. Set VOICE_MCP_ENABLED=true on Voice Railway only after verifying production readiness. Default is false.
4. Verify GET /.well-known/oauth-protected-resource/mcp, GET /.well-known/oauth-authorization-server and GET /mcp/connect.
5. Connect RAINY Voice and RAVS separately in ChatGPT or Claude custom MCP connector settings. Voice uses authorization-code OAuth + PKCE S256 and its own user credentials.
6. If the first OAuth redirect appears logged out because Voice uses SameSite=Strict cookies, sign in at Voice in a separate tab and click the same-origin Continue link on the OAuth page.

## Tools

| Tool | Purpose | Billable |
|---|---|---|
| rainy_voice_voices | Mongolian built-in and user voice list | No |
| rainy_voice_wallet | User's Voice credits | No |
| rainy_voice_quote_tts | Eleven v4 / Turbo TTS quote | No |
| rainy_voice_job_status | Own job status, login-required download | No |
| rainy_voice_video_handoff | Two-site workflow plan | No |
| rainy_voice_create_tts | TTS queue creation | Yes, confirmation |

## Cross-site workflow

1. RAVS: ravs_voice_workflow_plan, ravs_list_models, ravs_model_guide, ravs_content_brief.
2. AI assistant drafts Mongolian storyboard, scene prompts and voice-over script.
3. RAVS ravs_estimate and Voice rainy_voice_quote_tts calculate different wallets' costs.
4. User independently approves both paid generations, including maxCredits and stable idempotency keys.
5. RAVS ravs_generation_status and Voice rainy_voice_job_status check completion independently.
6. Report video URL only after COMPLETED and audio only after done.

Voice download links require a Voice browser session; they are not public provider-ingest URLs. This version does NOT automatically combine video and audio, burn subtitles, or publish social posts.

## Security and testing

Opaque tokens are hashed in the Voice DB; authorization codes expire in 2 minutes, access tokens in 1 hour and refresh tokens in 30 days. Refresh uses rotation. All user actions are scoped to the Voice user. The paid tool requires confirmGeneration=true, maxCredits and a unique idempotencyKey. On uncertain submission never retry with a different key.

Registration rate limits are in-process; add Railway/proxy WAF limits for multi-instance deployments.

Run: python -m compileall -q app
Run: python -m unittest discover -s tests -p test_mcp_remote.py -v

Provider-free tests do not prove a live ChatGPT/Claude installation, end-to-end Wire payment, Railway deployment or live ElevenLabs generation.
## RAINY One-Prompt Movie (preview, production gate)

- RAVS `ravs_long_movie_plan` нэг prompt-оос 4–3600 секундийн хүрээнд кадрын хуваарь, киноны rhythm, continuity bible, video credit plan бэлдэнэ.
- Туслах (ChatGPT/Claude) scene бүрийн өөр prompt-ыг боловсруулж, **нийт видео + Voice + MP4** кредитийн таазыг нэг удаа танилцуулж зөвшөөрүүлнэ. Видео генерацын үнийг ашиглахаас өмнө `ravs_scene_batch_estimate` болон `ravs_estimate`-ээр нягтал.
- Видео бүтээл `COMPLETED`, Voice `done` болсны дараа (зөвхөн баталгаатай CDN host) `rainy_voice_movie_quote`, `rainy_voice_create_movie`, `rainy_voice_movie_status` алхмаар MP4 гаргана.
- Voice-д `RAINY_MOVIE_ENABLED=false` анхдагч. Үүнийг live болгож `RAINY_MOVIE_MEDIA_HOSTS` exact allowlist оруулахын өмнө provider completed output-ийн бодит hostname, storage volume, FFmpeg smoke-test, performance, media right, asset validity-ийг шалгах ёстой. Хоосон host list-тэй үед бүх MP4 MCP tools **санаатайгаар харагдахгүй**.
- Үүссэн MP4 Voice login session-ээр татагдана. Структур QA нь duration, fps, dimensions, video/audio codec, file size шалгана; **дүрийн нүүр, логог, continuity, Mongolian pronunciation-ийг 100% баталж чадахгүй.**
- Нэг цаг хүртэлх movie assembly нь хамгийн ихдээ 120 clip, input <= 900 MB, нэг user-д нэг зэрэг job; Railway /data volume сул байдал, compute зэргээс хамаарна. 60 минутаас дээш урт бүтээлд chapter-level storyboard, ажлын багц, safe final concatenation нэмэх ажил үлдсэн.
- **Энэ нь одоохондоо бүрэн нэг даруултаар бие даан background ажиллах producer биш.** ChatGPT/Claude нь олон paid model calls-ийг ээлжлэн удирдах шаардлагатай. Хэрэглэгч offline болсон ч кадр бүрийг backend ажиллуулдаг persistent Video batch scheduler дараагийн хөгжүүлэлт.

### Production acceptance gate

1. Бодит RAVS нэг `COMPLETED` video-д media URL domain-г шалгаж зөвшөөрөгдөх host exact allowlist-д нэм.
2. CDN TLS + public DNS, no redirects, no credentials, MIME/size, malformed media, auth scope, signed URL expiry QA хийнэ.
3. Бодит preview clip + Voice TTS-ийг өөрсдийн эрхтэй хэрэглэгчээр quote → approve → queue → MP4 → download туршина; credit refund/idempotency батална.
4. Production variable `RAINY_MOVIE_ENABLED=true` зөвхөн дээрх шалгалт PASS болсон тохиолдолд.
