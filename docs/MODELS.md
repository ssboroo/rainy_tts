# ElevenLabs provider

RAINY Voice currently uses **ElevenLabs Eleven v4 only**.

## Runtime

The server-side adapter in `app/engine.py` calls the ElevenLabs Text to Speech API with:

- `model_id=eleven_v4`
- `language_code=mn`
- configured `ELEVENLABS_VOICE_ID`
- `pcm_24000` output

The returned PCM is written to WAV. The worker also exports MP3 through FFmpeg.

## Required environment values

```env
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
ELEVENLABS_VOICE_LABEL=Монгол · Eleven v4
ELEVENLABS_LANGUAGE_CODE=mn
ELEVENLABS_STABILITY=0.5
ELEVENLABS_SIMILARITY_BOOST=0.8
```

The API key is server-side only and must not be added to static JavaScript, Git commits or public logs.

## Voice policy

The current app exposes one server-configured ElevenLabs voice. Local reference upload and Oron/F5 voice conditioning are disabled.

If voice cloning is added later, only voices the operator/user has the rights and consent to use should be uploaded to ElevenLabs.

## Production checks

Before a paid public launch:

- Confirm the ElevenLabs plan supports the intended commercial use and volume.
- Confirm rights for the configured voice.
- Measure Mongolian pronunciation quality with native speakers.
- Test names, Ө/Ү, long vowels, punctuation and glossary replacements.
- Track API errors, rate limits, latency and credit usage.
- Add billing/credit controls before allowing large public workloads.
