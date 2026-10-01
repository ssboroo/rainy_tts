import os
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv(dotenv_path=".env.local", override=False)
load_dotenv(dotenv_path=".env", override=False)

api_key=(os.getenv("ELEVENLABS_API_KEY") or "").strip()
if not api_key:
    raise SystemExit("ELEVENLABS_API_KEY .env.local эсвэл .env дотор алга.")

voice_id=os.getenv("ELEVENLABS_TEST_VOICE_ID","WgH4JH8sD6a2SIrujiKn").strip()
model_id=os.getenv("ELEVENLABS_TTS_MODEL","eleven_v4").strip() or "eleven_v4"

client=ElevenLabs(api_key=api_key)
audio=client.text_to_speech.convert(
    voice_id=voice_id,
    text="Сайн байна уу. Энэ бол RAINY Voice Монгол хэлний API туршилт.",
    model_id=model_id,
    output_format="mp3_44100_128",
    language_code="mn",
)

output=Path("elevenlabs-test.mp3")
output.write_bytes(b"".join(audio))
print(f"OK: {output.resolve()} | voice={voice_id} | model={model_id}")
