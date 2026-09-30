# Model integration and commercial release gate

The app never returns mock speech. The base image deliberately has **no model dependencies** and shows a not-ready state until a reviewed engine is installed. No model weights are bundled.

## Candidate: Oron / F5-TTS

Sources reviewed on 2026-09-29:
- https://huggingface.co/btsee/oron-tts
- https://github.com/btseee/oron-tts
- https://github.com/SWivid/F5-TTS

The Oron model card labels its weights CC-BY-4.0 and documents two supplied voices, `use_ema=False`, and `MongolianNormalizer(..., strict=True)`. This is **not a completed legal review** of the full dependency chain. F5 upstream pretrained checkpoints can have different terms. Confirm exactly which base weights, Vocos weights, source data and reference voices are used. Preserve required attribution. Do not assume a permissive code license also covers weights or voice identity rights.

The adapter follows the model card's F5TTS API, explicitly sets `device='cpu'`, and uses raw rather than EMA tensors. Model weights have been downloaded for integration checks. A real CPU inference smoke test passed. Voice quality, clone quality and commercial readiness remain **unverified**; see VERIFICATION.md for the exact test result.

## Cloud provider: ElevenLabs Eleven v4

Added on 2026-10-01 using the official ElevenLabs server-side Text to Speech API. The adapter calls `POST /v1/text-to-speech/:voice_id` with `model_id=eleven_v4`, requests `pcm_24000`, and keeps `ELEVENLABS_API_KEY` out of browser code.

Official references:
- https://elevenlabs.io/docs/overview/models
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert
- https://elevenlabs.io/docs/eleven-api/quickstart

Eleven v4 lists Mongolian among its 90+ supported languages. The app sends `ELEVENLABS_LANGUAGE_CODE=mn` by default for the API language hint. Choose a voice recorded or cloned in Mongolian for the best native accent and pronunciation.

Required environment values:

```env
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
ELEVENLABS_VOICE_LABEL=Монгол · Eleven v4
ELEVENLABS_LANGUAGE_CODE=mn
ELEVENLABS_STABILITY=0.5
ELEVENLABS_SIMILARITY_BOOST=0.8
```

The API key is used only by the server/worker. Do not place it in static JavaScript or commit a real key. ElevenLabs account usage, billing, voice rights and cloning consent remain the operator's responsibility. The existing local upload/clone workflow still routes to Oron; this integration does not automatically upload user reference recordings to ElevenLabs.

## Install in a reviewed CPU worker image

1. Select and record exact immutable commits for `SWivid/F5-TTS` and `btseee/oron-tts`. Review dependencies and licenses before installation; do not blindly install moving main branches in production.
2. Install CPU PyTorch, compatible torchaudio, F5-TTS, oron-tts, huggingface-hub and soundfile in a derived worker image. The normalizer package must also be available to the web container, because readiness is checked there. Use the same derived image for both services.
3. Download an immutable revision of `btsee/oron-tts` into `/models/oron` with these files:

```
model.safetensors
vocab.txt
voices/male.wav
voices/male.txt
voices/female.wav
voices/female.txt
vocos/config.yaml
vocos/pytorch_model.bin
```

4. Download the pinned Vocos dependency into `/models/oron/vocos` (the provided download script does this). Verify the license and hashes. Set `HF_HUB_OFFLINE=1` only after a successful cold start with the full cache. If the upstream API changes, adapt `app/engine.py` and retest.
5. Record revisions and SHA256 hashes in your deployment's model manifest. Only after the commercial review set `MODEL_LICENSE_APPROVED=true`.
6. Run the benchmark below before enabling registrations or `ENABLE_EXPERIMENTAL_CLONING=true`.

## Required evaluation

- At least 50 unseen Mongolian sentences: vowel length, Ө/Ү, names, dialogue, punctuation, glossary expansions. Numbers currently require explicit words rather than an unverified morphology guess.
- Listen with native Mongolian speakers. Record intelligibility, omitted/repeated words, naturalness and identity consistency.
- Record actual CPU model, RAM, peak memory, cold/warm generation latency and real-time factor (generation seconds / output seconds).
- Test male and female builtins separately. Test custom references only with consent, exact reference transcripts, 3–12 second clean audio. The upload length is an application constraint, **not an upstream optimal-length guarantee**.
- Test SRT timing. Overruns are reported; overlaps fail instead of overwriting speech. There is no lip-sync promise.
- Reference audio conditioning is experimental. No validated emotion labels, voice design or instruction-based acting are exposed. Add those capabilities only after evaluating a suitable commercially usable model.

## Excluded defaults

Meta MMS Mongolian and the researched Mongolian Kitten Teacher checkpoints are CC-BY-NC-4.0. They are not included as commercial providers. Different license terms require explicit rights-holder permission; modifying their code does not remove the weight restriction.

## Reproducible candidate setup

`Dockerfile.model` pins the two source repositories to reviewed API revisions and selects a matching CPU PyTorch/torchaudio pair. The integration environment is recorded in `requirements-model.constraints.txt`; verify it during the target Docker build. The upstream Oron package requires **Python 3.12 or newer**.

```bash
docker compose -f compose.yaml -f compose.model.yaml build
docker compose -f compose.yaml -f compose.model.yaml run --rm worker python scripts/download_model.py
# Complete license review, then edit .env accordingly.
docker compose -f compose.yaml -f compose.model.yaml up -d
```

The download script pins the model revision and writes a SHA256 manifest. The script also downloads a pinned Vocos revision for local loading; no generation-time model download is intended. Full Docker/model installation is not certified until built and exercised on the target server.
