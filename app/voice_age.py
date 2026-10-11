"""Perceived voice-age selection; never infers a speaker's actual age.

ElevenLabs age labels support catalog filtering. Voice Design accepts free-text
descriptors; ordinary TTS does not have a per-request numeric voice-age control.
"""
from fastapi import HTTPException

AGE_DESCRIPTORS = {
    "teen": "a youthful late-adolescent sounding voice",
    "young": "a young adult sounding voice, approximately in their 20s",
    "middle_aged": "a mature middle-aged sounding voice, approximately in their 40s to 50s",
    "old": "an older adult sounding voice, approximately 65 years or older",
}

def normalize_age(value):
    """Return a supported PERCEIVED age label or None for unknown metadata."""
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return {
        "teen": "teen", "teenager": "teen", "adolescent": "teen",
        "young": "young", "young_adult": "young",
        "middle_aged": "middle_aged", "middle_age": "middle_aged",
        "old": "old", "elderly": "old", "senior": "old",
    }.get(key)

def apply_design_age(prompt, requested_age):
    """Add provider-supported natural-language description, no fake age setting."""
    if requested_age is None or requested_age == "":
        return prompt
    if not isinstance(requested_age, str) or requested_age not in AGE_DESCRIPTORS:
        raise HTTPException(422, "Хоолойн насны ангилал буруу байна.")
    # A descriptor is not a guarantee of the generated voice's exact age.
    addition = "Perceived vocal age: " + AGE_DESCRIPTORS[requested_age] + ". Natural Mongolian pronunciation."
    if len(prompt) + len(addition) + 2 > 1000:
        raise HTTPException(422, "Хоолойн тайлбар насны тохиргоотой нийлээд 1,000 тэмдэгтээс хэтэрч байна.")
    return prompt.rstrip() + "\n" + addition
