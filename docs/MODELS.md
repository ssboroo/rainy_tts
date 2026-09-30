# ElevenLabs providers used by RAINY

RAINY is an ElevenLabs Creative Studio, not a local-model runtime.

## Models and APIs

- Text to Speech: `eleven_v4`, Mongolian language hint `mn`, PCM 24 kHz → WAV/MP3.
- Podcast / Dialogue: `eleven_v3` Text to Dialogue.
- Music: `music_v2_5` by default, with `music_v2` and `music_v1` selectable.
- Sound Effects: `eleven_text_to_sound_v2`.
- Speech to Text: `scribe_v2`.
- Realtime STT: `scribe_v2_realtime` via browser WebSocket and a single-use token.
- Voice Changer: `eleven_multilingual_sts_v2`.
- Dubbing: `dubbing_v2`.
- Voice Clone: Instant Voice Cloning API.

## Voice catalog

RAINY ships with 12 configured Mongolian ElevenLabs voice IDs. A user-created Instant Voice Clone is stored in the local `voices` table after ElevenLabs returns its Voice ID, then becomes available in TTS, Dialogue and Voice Changer selectors.

`ELEVENLABS_VOICES_JSON` can override the built-in catalog.

## Mongolian notes

TTS uses Eleven v4 with `language_code=mn`.

Scribe v2 accepts ISO-639-1 or ISO-639-3 language codes and is used with `mn` in the UI; automatic detection can be used by leaving the language field empty.

Voice Changer uses `eleven_multilingual_sts_v2`. Mongolian is not currently in that model's documented supported-source-language list, so RAINY shows a warning rather than claiming Mongolian speech-to-speech support.

## Security

`ELEVENLABS_API_KEY` is server-side only. Normal browser requests never receive it. Realtime STT uses an ElevenLabs single-use token instead.

Voice cloning requires a user consent/right confirmation before files are sent to ElevenLabs.
