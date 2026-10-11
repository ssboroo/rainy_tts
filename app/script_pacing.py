"""Read-only Mongolian voice-over pacing preflight (NOT synthesized audio or a quote).

Provides grounded timing heuristics for scripts, safe segment lengths and a
clear warning when a requested duration would require an unnatural pace.
No provider API requests or credit debits occur here.
"""
import math
import re

STYLES = {
    "advertisement": {"name": "Реклам", "words_per_minute": 150},
    "narration": {"name": "Өгүүлэмж", "words_per_minute": 125},
    "podcast": {"name": "Подкаст", "words_per_minute": 135},
    "calm": {"name": "Тайван", "words_per_minute": 110},
}


def _chunks(text, limit=190):
    sentences = re.findall(r"[^.!?。！？\n]+[.!?。！？]*|\n+", text)
    chunks = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        for token in re.findall(r"\S+", sentence):
            candidate = f"{current} {token}".strip()
            if len(candidate) > limit and current:
                chunks.append(current)
                current = token
            elif len(token) > limit:
                # One exceptionally long word cannot be meaningfully voiced.
                raise ValueError("190 тэмдэгтээс урт салангид үг байна. Бичвэрээ шалгана уу.")
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def plan_pacing(text, target_seconds=None, style="narration"):
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError("Бичвэр 1–12,000 тэмдэгттэй байна.")
    if style not in STYLES:
        raise ValueError("Уншлагын хэв маяг буруу байна.")
    if target_seconds is not None and (isinstance(target_seconds, bool)
            or not isinstance(target_seconds, (int, float))
            or not math.isfinite(target_seconds)
            or target_seconds < 5 or target_seconds > 600):
        raise ValueError("Зорилтот хугацаа 5–600 секунд байна.")
    text = " ".join(text.split())
    parts = _chunks(text)
    wpm = STYLES[style]["words_per_minute"]
    estimates = []
    for part in parts:
        words = len(part.split())
        # Sentence-ending pause estimates; not guaranteed TTS timings.
        pause = 0.38 * len(re.findall(r"[.!?。！？]", part)) + 0.16 * len(re.findall(r"[,;:，；：]", part))
        seconds = max(0.35, words * 60.0 / wpm + pause)
        estimates.append({"text": part, "words": words, "estimatedSeconds": round(seconds, 2)})
    estimated = round(sum(s["estimatedSeconds"] for s in estimates), 1)
    target = float(target_seconds) if target_seconds is not None else None
    ratio = estimated / target if target else None
    if ratio is None:
        fit = "no_target"
    elif ratio > 1.2:
        fit = "shorten_script"
    elif ratio < 0.8:
        fit = "allow_more_pauses"
    else:
        fit = "approximate_fit"
    return {
        "style": style,
        "styleLabel": STYLES[style]["name"],
        "wordsPerMinuteAssumption": wpm,
        "words": len(text.split()),
        "characters": len(text),
        "estimatedSeconds": estimated,
        "targetSeconds": target,
        "fit": fit,
        "approximateSpeedFactor": round(min(1.2, max(0.8, ratio)), 2) if ratio else None,
        "segments": estimates,
        "chargeable": False,
        "note": "Хугацаа нь Монгол текстийн үгийн тоо, цэг тэмдэгт суурилсан ойролцоо төлөвлөгөө. ElevenLabs-ийн бодит унших хугацаа, үнийн санал биш. Дууны кредитийг rainy_voice_quote_tts-ээр тусад нь шалгана.",
    }
