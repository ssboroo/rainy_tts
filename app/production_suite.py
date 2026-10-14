"""RAINY independent voice-production tools.

Every planning endpoint is read-only and provider-free. TTS jobs use the
existing charged /api/jobs flow. Corrected-audio assembly can only splice two
completed, user-owned WAV assets; it cannot invoke or bill ElevenLabs.
"""
import asyncio
import math
import re
import subprocess
import wave
from pathlib import Path
from fastapi import HTTPException, Request
from . import billing, core

DIRECTOR_STYLES = {
    "cinematic": {"label": "Киноны трейлер", "tags": ("[curious]", "[whispers]", "[excited]")},
    "advertising": {"label": "Сурталчилгаа", "tags": ("[excited]", "[happy]", "[confident]")},
    "storytelling": {"label": "Уран өгүүлэмж", "tags": ("[thoughtful]", "[curious]", "[sighs]")},
    "calm": {"label": "Тайван тайлбар", "tags": ("[thoughtful]", "", "")},
    "news": {"label": "Мэдээ, мэдээлэл", "tags": ("", "", "")},
}
# Mongolian stage-direction cues reuse the existing v4 TTS model. No extra API request.
# Respect existing [emotion] tags, never delete or rewrite the customer's words.
MN_EMOTION_CUES = (
    (re.compile(r"шивн(э|эн|эж)|аяархан хэл",re.I), "[whispers]"),
    (re.compile(r"ууртай|уурла|уцаартай|хилэнтэй",re.I), "[angry]"),
    (re.compile(r"гунигтай|гуниглан|гуниглав|гунигт",re.I), "[sad]"),
    (re.compile(r"уйлан|нулимстай|уйл(ж|ах|ав)",re.I), "[crying]"),
    (re.compile(r"догдлон|догдолж|хөөрөн|сэтгэл хөөр",re.I), "[excited]"),
    (re.compile(r"баярлан|баяртайгаар|аз жаргалтай|инээмсэглэн",re.I), "[happy]"),
)
STAGE_TAG = re.compile(r"^\[[a-z][a-z \-]{1,35}\]",re.I)

MAX_BOOK_CHARS = 80000
MAX_BOOK_CHAPTERS = 20

def direct_script(text, style="storytelling"):
    if style not in DIRECTOR_STYLES:
        raise ValueError("Найруулгын хэв маяг буруу байна.")
    text=core.prepare_text(str(text or ""))
    sentences=[x.strip() for x in re.split(r'(?<=[.!?…])\s+',text) if x.strip()]
    if not sentences: sentences=[text]
    tags=DIRECTOR_STYLES[style]["tags"]
    lines=[]
    for i, sentence in enumerate(sentences):
        # One stage direction per sentence. This is creative prompting, not
        # guaranteed prosody, and does not infer mood from private user data.
        tag=tags[min(i,len(tags)-1)] if i<3 else tags[1]
        if STAGE_TAG.match(sentence):
            # User-provided v4 direction is authoritative, not duplicated.
            tag=""
        else:
            tag=next((stage for pattern,stage in MN_EMOTION_CUES if pattern.search(sentence)),tag)
        lines.append((tag+" " if tag else "")+sentence)
    script="\n".join(lines)
    if len(script)>12000:
        raise ValueError("Найруулсан текст 12,000 тэмдэгтийн хязгаараас хэтэрлээ. Эх текстээ богиносгоно уу.")
    return {
        "style":style,"label":DIRECTOR_STYLES[style]["label"],
        "original":text,"directedText":script,
        "sentences":len(sentences),"creditsCharged":0,
        "note":"Энэ нь Eleven v4-д зориулсан урьдчилсан бүтээлч тэмдэглэгээ. Дуу үүсээгүй, чанарыг батлаагүй. Текстээ шалгаад Studio-ийн энгийн кредит тооцоо/үүсгэлтээр үргэлжлүүл.",
    }

def _book_parts(text):
    if not isinstance(text,str) or not text.strip() or len(text)>MAX_BOOK_CHARS:
        raise ValueError("Номын текст 1–80,000 тэмдэгттэй байна.")
    raw=text.replace("\r\n","\n").replace("\r","\n").strip()
    paragraphs=[p.strip() for p in re.split(r"\n\s*\n+",raw) if p.strip()]
    chapters=[]
    current=""
    def push():
        nonlocal current
        if current:
            chapters.append(core.prepare_text(current))
            current=""
    for para in paragraphs:
        for word in para.split():
            if len(word)>240:
                raise ValueError("Хэт урт тасралтгүй үг байна.")
            cand=(current+" "+word).strip()
            if len(cand)>10000:
                push()
                current=word
            else:
                current=cand
        # Give paragraph endings a structural separation when near the budget.
        if len(current)>8200: push()
    push()
    if not chapters or len(chapters)>MAX_BOOK_CHAPTERS:
        raise ValueError("Номыг хамгийн ихдээ 20 бүлэгт хуваана. Текстээ хэсэгчлэн оруулна уу.")
    return chapters

def plan_book(text,title="Монгол аудио ном",model_id="eleven_v4",multiplier=1.0):
    if model_id not in {"eleven_v4","eleven_v4_turbo"}:
        raise ValueError("Зөвхөн Монгол TTS-ийн дэмжигдсэн загвар сонгоно уу.")
    if not isinstance(title,str) or not title.strip() or len(title)>100:
        raise ValueError("Номын нэр 1–100 тэмдэгт байна.")
    if not isinstance(multiplier,(int,float)) or not math.isfinite(multiplier) or multiplier<1:
        raise ValueError("Хоолойн үнийн үржүүлэгч буруу.")
    parts=_book_parts(text)
    chapters=[]
    for i,part in enumerate(parts):
        credits=max(1,math.ceil(billing.estimate("tts",chars=len(part),model_id=model_id)*multiplier))
        chapters.append({"index":i+1,"title":f"{title} · Бүлэг {i+1}","text":part,"characters":len(part),"estimatedCredits":credits})
    return {"chapters":chapters,"chapterCount":len(chapters),
      "totalEstimatedCredits":sum(c["estimatedCredits"] for c in chapters),
      "modelId":model_id,
      "note":"Энэ нь төлбөргүй төлөвлөгөө. Бүлэг бүрийг үүсгэхийн өмнө /api/jobs/quote серверийн баталгаажсан үнээр шалгаж, зөвшөөрсний дараа тус тусад нь үүсгэнэ. Нэгтгэсэн файл/фон хөгжим автоматаар хийгдээгүй.",
      "creditsCharged":0}

def _wav_duration(path):
    with wave.open(str(path),"rb") as wav:
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate()!=24000:
            raise ValueError("Эх WAV формат тохирохгүй.")
        return wav.getnframes()/24000

def _splice(source,replacement,start,end,dest):
    # All file paths are server-owned. No user-supplied URLs or ffmpeg filters.
    fc=(f"[0:a]atrim=start=0:end={start:.3f},asetpts=PTS-STARTPTS[a0];"
        f"[1:a]asetpts=PTS-STARTPTS[a1];"
        f"[0:a]atrim=start={end:.3f},asetpts=PTS-STARTPTS[a2];"
        "[a0][a1][a2]concat=n=3:v=0:a=1[out]")
    subprocess.run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        "-i",str(source),"-i",str(replacement),"-filter_complex",fc,
        "-map","[out]","-ac","1","-ar","24000","-c:a","libmp3lame","-b:a","128k",str(dest)],
        check=True,capture_output=True,timeout=120)
    if not dest.is_file() or not 200<=dest.stat().st_size<=20*1024*1024:
        raise ValueError("Зассан аудио файлын хэмжээ буруу байна.")

def register_routes(app,session,mutation_guard,throttle,allowed_voice_ids,voice_cost_multiplier):
    @app.post("/api/production/director")
    async def voice_director(request:Request):
        sess=session(request);mutation_guard(request,sess);throttle("director:"+sess["user_id"],80,3600)
        body=await request.json()
        if not isinstance(body,dict): raise HTTPException(422,"Тайлбар буруу.")
        try: return direct_script(body.get("text"),body.get("style","storytelling"))
        except ValueError as e: raise HTTPException(422,str(e))

    @app.post("/api/production/audiobook/plan")
    async def audiobook_plan(request:Request):
        sess=session(request);mutation_guard(request,sess);throttle("book:"+sess["user_id"],25,3600)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,"Тайлбар буруу.")
        voice=str(body.get("voice_id") or "")
        if voice not in allowed_voice_ids(sess["user_id"]):raise HTTPException(422,"Хоолой таны санд байхгүй.")
        try:
            multiplier=await voice_cost_multiplier(voice,sess["user_id"])
            quote=plan_book(body.get("text"),body.get("title","Монгол аудио ном"),
                body.get("model_id","eleven_v4"),multiplier)
        except ValueError as e:raise HTTPException(422,str(e))
        quote["voiceId"]=voice
        return quote

    @app.post("/api/production/audio-patch")
    async def audio_patch(request:Request):
        sess=session(request);mutation_guard(request,sess);throttle("patch:"+sess["user_id"],8,3600)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(422,"Тохиргоо буруу.")
        original=str(body.get("original_job_id") or "")
        correction=str(body.get("correction_job_id") or "")
        if not original or not correction or original==correction or len(original)>80 or len(correction)>80:
            raise HTTPException(422,"Эх бичлэг ба засварын ажлын дугаар буруу.")
        with core.db() as db:
            rows=db.execute("SELECT id,status FROM jobs WHERE id IN (?,?) AND user_id=?",
                            (original,correction,sess["user_id"])).fetchall()
        if len(rows)!=2 or any(row["status"]!="done" for row in rows):
            raise HTTPException(422,"Эх болон засах өгүүлбэр хоёулаа бэлэн, таны өөрийн бүтээл байх ёстой.")
        source=core.DATA/"outputs"/(original+".wav")
        repair=core.DATA/"outputs"/(correction+".wav")
        if not source.is_file() or not repair.is_file():
            raise HTTPException(404,"Аудионы WAV файл олдсонгүй.")
        try:
            duration=_wav_duration(source)
            patch_duration=_wav_duration(repair)
            start=float(body.get("start_seconds"))
            end=float(body.get("end_seconds"))
        except (ValueError,TypeError,EOFError,OverflowError,FileNotFoundError,wave.Error):
            raise HTTPException(422,"Аудионы хугацаа эсвэл формат буруу.")
        if not all(math.isfinite(x) for x in (start,end,duration,patch_duration)) or \
           duration>600 or not 0<=start<end<=duration or end-start>90 or patch_duration>90:
            raise HTTPException(422,"Эх бүтээл 10 минутаас, засах хэсэг 90 секундээс хэтрэхгүй. Хугацаагаа шалгана уу.")
        job=core.create_tool_job(sess["user_id"],"audio_patch","Өгүүлбэрийн засвар",
            {"original_job_id":original,"correction_job_id":correction,"start_seconds":start,"end_seconds":end})
        output=core.DATA/"artifacts"/(core.uid()+".mp3")
        try:
            await asyncio.to_thread(_splice,source,repair,start,end,output)
            artifact=core.add_artifact(job,sess["user_id"],"audio","rainy-corrected-voice.mp3","audio/mpeg",output)
            core.update_tool_job(job,"done",result={"artifact_id":artifact,"credits_used":0,
                 "replaced_seconds":round(end-start,2),"replacement_seconds":round(patch_duration,2)})
        except Exception:
            output.unlink(missing_ok=True)
            core.update_tool_job(job,"failed",error="Аудио нийлүүлэх боломжгүй байна.")
            raise HTTPException(422,"Аудио нийлүүлж чадсангүй. Эх WAV файлууд болон хугацааг шалгана уу.")
        return {"job_id":job,"artifact_id":artifact,"credits_used":0,
                "note":"Нийлүүлэлт үнэгүй. Засварласан өгүүлбэрийг TTS-ээр тусад нь үүсгэх үед хэрэглэсэн кредит бол хэвийн төлбөр."}
