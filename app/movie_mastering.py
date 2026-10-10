"""Validated mastering options for independently owned RAINY Voice MP4 renders."""
import os
from pathlib import Path
from . import core

PROFILE_DIMS={
    "720p":{"16:9":(1280,720),"9:16":(720,1280),"1:1":(720,720)},
    "1080p":{"16:9":(1920,1080),"9:16":(1080,1920),"1:1":(1080,1080)},
    "4k":{"16:9":(3840,2160),"9:16":(2160,3840),"1:1":(2160,2160)},
}
def master_settings(options,seconds,ratio):
    if options is None: options={}
    if not isinstance(options,dict): raise ValueError("MP4 mastering мэдээлэл буруу.")
    allowed={"output_quality","music_artifact_id","subtitle_artifact_id","master_audio","subtitle_burn_in"}
    if set(options)-allowed: raise ValueError("Mastering-д танихгүй параметр байна.")
    quality=options.get("output_quality","720p")
    if quality not in PROFILE_DIMS or ratio not in PROFILE_DIMS[quality]:
        raise ValueError("720p, 1080p, 4k эсвэл харьцааны сонголт буруу.")
    if quality=="4k":
        if os.getenv("RAINY_MOVIE_4K_ENABLED","false").lower() not in {"1","true","yes"}:
            raise ValueError("4K renderer туршилтын хамгаалалтаар идэвхгүй.")
        if seconds>300: raise ValueError("4K 5 минутаас урт ажилд dedicated GPU/CPU render worker шаардлагатай.")
    if quality=="1080p" and seconds>900:
        raise ValueError("1080p 15 минутаас урт киноны dedicated render worker хараахан идэвхгүй.")
    for field in ("music_artifact_id","subtitle_artifact_id"):
        value=options.get(field)
        if value is not None and (not isinstance(value,str) or len(value)>80 or not value.isalnum()):
            raise ValueError("Медиа файлын ID зөвшөөрөгдөөгүй.")
    if options.get("master_audio",True) not in (True,False):
        raise ValueError("Аудио mastering сонголт буруу.")
    if options.get("subtitle_burn_in",False) not in (True,False):
        raise ValueError("Хадмалын сонголт буруу.")
    if options.get("subtitle_burn_in") and not options.get("subtitle_artifact_id"):
        raise ValueError("Хадмалын файл шаардлагатай.")
    return {"quality":quality,"dimensions":PROFILE_DIMS[quality][ratio],
            "music_artifact_id":options.get("music_artifact_id"),
            "subtitle_artifact_id":options.get("subtitle_artifact_id"),
            "master_audio":options.get("master_audio",True),
            "subtitle_burn_in":options.get("subtitle_burn_in",False)}

def owned_artifact(user_id,artifact_id,kind):
    if not artifact_id:return None
    with core.db() as c:
        record=c.execute("SELECT path,kind,mime FROM artifacts WHERE user_id=? AND id=?",
                         (user_id,artifact_id)).fetchone()
    if not record or record["kind"]!=kind:
        raise ValueError("Таны аудио/хадмал файл олдсонгүй.")
    file=Path(record["path"]).resolve()
    base=(core.DATA/"artifacts").resolve()
    if not file.is_relative_to(base) or not file.is_file() or file.stat().st_size>100*1024*1024:
        raise ValueError("Медиа хадгалалтын эрх эсвэл хэмжээ буруу.")
    if kind=="subtitle":
        if record["mime"] not in {"application/x-subrip","text/plain"} or file.stat().st_size>1024*1024:
            raise ValueError("Зөвхөн SRT хадмалын файлыг зөвшөөрнө.")
    if kind=="audio":
        if record["mime"] not in {"audio/mpeg","audio/wav","audio/mp3","audio/flac","audio/ogg"}:
            raise ValueError("Mastering хөгжим аудио файл биш.")
    return file

def audio_filtergraph(voice_input,music_input,master_audio):
    # Tracks: 0=original video+audio, 1=voice (if supplied), next=owned music.
    chains=["[0:a:0]volume=0.14[bg]"]
    sounds=["[bg]"]
    if voice_input is not None:
        chains.append(f"[{voice_input}:a:0]volume=1.0,highpass=f=75,lowpass=f=15500[voice]")
        sounds.append("[voice]")
    if music_input is not None:
        chains.append(f"[{music_input}:a:0]volume=0.15[music]")
        sounds.append("[music]")
    if len(sounds)>1:
        chains.append("".join(sounds)+f"amix=inputs={len(sounds)}:duration=first:dropout_transition=1[pre]")
    else:
        chains.append("[bg]anull[pre]")
    if master_audio:
        chains.append("[pre]loudnorm=I=-16:TP=-1.5:LRA=11,alimiter=limit=0.95[mix]")
    else:
        chains.append("[pre]anull[mix]")
    return ";".join(chains)
