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