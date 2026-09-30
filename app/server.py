"""RAINY Voice FastAPI server: TTS plus ElevenLabs Creative tools."""
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import threading
import time

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
import uvicorn

from . import core
from .engine import ElevenLabsEngine
from .eleven_tools import ElevenAPIError, ElevenTools

STATIC = Path(__file__).parent / "static"
ORIGIN = os.getenv("PUBLIC_ORIGIN","http://localhost:8080").rstrip("/")
SECURE = ORIGIN.startswith("https://")
RATE = {}
RATE_LOCK = threading.Lock()
AUDIO_EXTS={".mp3",".wav",".m4a",".aac",".flac",".ogg",".webm",".mp4"}
VIDEO_EXTS={".mp4",".mov",".mkv",".avi",".mpeg",".mpg"}
MEDIA_EXTS=AUDIO_EXTS|VIDEO_EXTS
MAX_AUDIO_MB=int(os.getenv("MAX_AUDIO_UPLOAD_MB","100"))
MAX_DUB_MB=int(os.getenv("MAX_DUB_UPLOAD_MB","500"))

app=FastAPI(title="RAINY Voice API",docs_url=None,redoc_url=None)
tools=ElevenTools()

@app.on_event("startup")
def startup():
    core.init()

@app.middleware("http")
async def security_headers(request:Request, call_next):
    response=await call_next(request)
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="same-origin"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Content-Security-Policy"]=(
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "media-src 'self' blob: https:; connect-src 'self' https://api.elevenlabs.io wss://api.elevenlabs.io; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return response

def throttle(key, limit=30, seconds=900):
    now=time.time()
    with RATE_LOCK:
        for stale in [k for k,v in RATE.items() if now-v[0]>seconds]:
            del RATE[stale]
        start,count=RATE.get(key,(now,0))
        if now-start>seconds:
            start,count=now,0
        if count>=limit:
            raise HTTPException(429,"Түр хүлээгээд дахин оролдоно уу.")
        RATE[key]=(start,count+1)

def session(request:Request, required=True):
    raw=request.cookies.get("session","")
    token=hashlib.sha256(raw.encode()).hexdigest()
    with core.db() as c:
        row=c.execute(
            "SELECT sessions.*,users.email FROM sessions JOIN users ON users.id=sessions.user_id "
            "WHERE token=? AND expires>?",(token,time.time())
        ).fetchone()
    if not row and required:
        raise HTTPException(401,"Эхлээд нэвтэрнэ үү.")
    return row

def allowed_origins(request:Request):
    configured={ORIGIN.rstrip("/")}
    configured.update(
        item.strip().rstrip("/")
        for item in os.getenv("PUBLIC_ORIGINS","").split(",")
        if item.strip()
    )
    host=request.headers.get("host","").strip()
    if host:
        configured.add(f"{request.url.scheme}://{host}".rstrip("/"))
    local_aliases=set()
    for origin in configured:
        match=re.fullmatch(r"(https?)://(localhost|127\.0\.0\.1)(:\d+)?",origin,re.IGNORECASE)
        if match:
            scheme,_,port=match.groups()
            local_aliases.add(f"{scheme}://localhost{port or ''}")
            local_aliases.add(f"{scheme}://127.0.0.1{port or ''}")
    configured.update(local_aliases)
    return configured

def mutation_guard(request:Request, sess=None):
    origin=(request.headers.get("origin") or "").rstrip("/")
    if not origin or origin not in allowed_origins(request):
        raise HTTPException(403,"Хүсэлтийн эх сурвалж зөвшөөрөгдөөгүй.")
    if sess and not secrets.compare_digest(request.headers.get("x-csrf-token",""),sess["csrf"]):
        raise HTTPException(403,"Хуудсаа шинэчлээд дахин оролдоно уу.")

async def json_body(request:Request):
    try:
        data=await request.json()
    except Exception:
        raise HTTPException(400,"JSON хүсэлт буруу байна.")
    if not isinstance(data,dict):
        raise HTTPException(400,"JSON хүсэлт буруу байна.")
    return data

def allowed_voice_ids(user_id=None):
    ids={voice["id"] for voice in ElevenLabsEngine.configured_voices()}
    if user_id:
        with core.db() as c:
            ids.update(row["id"] for row in c.execute("SELECT id FROM voices WHERE user_id=?",(user_id,)))
    return ids

def validate_upload(upload:UploadFile, extensions, max_mb):
    ext=Path(upload.filename or "").suffix.lower()
    if ext not in extensions:
        raise HTTPException(422,"Файлын төрөл дэмжигдэхгүй байна.")
    size=getattr(upload,"size",None)
    if size is not None and size>max_mb*1024*1024:
        raise HTTPException(413,f"Файл {max_mb} MB-аас их байна.")

def api_exception(exc):
    if isinstance(exc,ElevenAPIError):
        status=exc.status if 400<=exc.status<500 else 502
        return HTTPException(status,str(exc))
    if isinstance(exc,ValueError):
        return HTTPException(422,str(exc))
    logging.exception("ElevenLabs tool failed")
    return HTTPException(502,"ElevenLabs үйлдэл амжилтгүй боллоо.")

def create_artifact_bytes(user_id,job_id,kind,filename,mime,data):
    ext=Path(filename).suffix
    storage=core.DATA/"artifacts"/(core.uid()+ext)
    storage.write_bytes(data)
    artifact_id=core.add_artifact(job_id,user_id,kind,filename,mime,storage)
    return artifact_id

def create_artifact_text(user_id,job_id,kind,filename,mime,text):
    return create_artifact_bytes(user_id,job_id,kind,filename,mime,text.encode("utf-8"))

def public_tool_job_with_artifacts(row):
    data=core.public_tool_job(row)
    data["artifacts"]=core.tool_artifacts(row["id"],row["user_id"])
    return data

async def persist_upload(upload:UploadFile, destination:Path):
    await upload.seek(0)
    with destination.open("wb") as target:
        while True:
            chunk=await upload.read(1024*1024)
            if not chunk:
                break
            target.write(chunk)
    await upload.seek(0)

def mux_dubbed_video(source:Path, dubbed_audio:Path, output:Path):
    copy_command=[
        "ffmpeg","-nostdin","-v","error","-y",
        "-i",str(source),"-i",str(dubbed_audio),
        "-map","0:v:0","-map","1:a:0",
        "-c:v","copy","-c:a","aac","-b:a","192k","-shortest",str(output)
    ]
    try:
        subprocess.run(copy_command,check=True,timeout=600,capture_output=True)
    except subprocess.CalledProcessError:
        subprocess.run(
            [
                "ffmpeg","-nostdin","-v","error","-y",
                "-i",str(source),"-i",str(dubbed_audio),
                "-map","0:v:0","-map","1:a:0",
                "-c:v","libx264","-preset","fast","-crf","20",
                "-c:a","aac","-b:a","192k","-shortest",str(output)
            ],
            check=True,timeout=1200,capture_output=True
        )

def srt_from_words(words):
    tokens=words or []
    def stamp(seconds):
        ms=max(0,round(float(seconds)*1000))
        h,rem=divmod(ms,3600000); m,rem=divmod(rem,60000); s,ms=divmod(rem,1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    cues=[]; group=[]; start=None; end=None; word_count=0
    for token in tokens:
        token_start=token.get("start"); token_end=token.get("end")
        if start is None and token_start is not None:
            start=float(token_start)
        if token_end is not None:
            end=float(token_end)
        if start is None and not group:
            continue
        group.append(token)
        if token.get("type")=="word":
            word_count+=1
        if start is not None and end is not None and (word_count>=9 or end-start>=4):
            cues.append((start,end,group)); group=[]; start=None; end=None; word_count=0
    if group and start is not None and end is not None:
        cues.append((start,end,group))
    blocks=[]
    for i,(start,end,group) in enumerate(cues,1):
        text="".join(str(token.get("text","")) for token in group).strip()
        if text:
            blocks.append(f"{i}\n{stamp(start)} --> {stamp(end)}\n{text}")
    return "\n\n".join(blocks)

@app.get("/")
def root():
    return FileResponse(STATIC/"index.html",media_type="text/html")

@app.get("/{name}")
def static_file(name:str):
    if name not in {"app.js","style.css","favicon.svg"}:
        raise HTTPException(404,"Хуудас олдсонгүй.")
    media={"app.js":"text/javascript","style.css":"text/css","favicon.svg":"image/svg+xml"}[name]
    return FileResponse(STATIC/name,media_type=media)

@app.get("/api/health")
def health():
    ready,reason=ElevenLabsEngine().readiness()
    return {
        "ok":True,"engine_ready":ready,"engine_message":reason,"provider":"elevenlabs",
        "capabilities":{
            "tts":True,"voice_cloning":True,"dialogue":True,"music":True,"sound_effects":True,
            "speech_to_text":True,"realtime_stt":True,"voice_changer":True,"dubbing":True,"analytics":True
        },
        "limitations":{
            "voice_changer_mongolian_source":"ElevenLabs multilingual STS v2 одоогоор Монгол source speech-ийг албан ёсны supported language жагсаалтдаа оруулаагүй."
        },
        "registration_open":os.getenv("ALLOW_REGISTRATION","false")=="true"
    }

@app.get("/api/me")
def me(request:Request):
    sess=session(request,False)
    return {"user":{"email":sess["email"],"csrf":sess["csrf"]} if sess else None}

@app.post("/api/register")
@app.post("/api/login")
async def auth(request:Request):
    mutation_guard(request)
    throttle("auth:"+request.client.host,30)
    data=await json_body(request)
    email=str(data.get("email","")).strip().lower()
    password=str(data.get("password",""))
    if not re.fullmatch(r"[^\s@]{1,64}@[^\s@]{1,180}\.[^\s@]{2,30}",email) or not 12<=len(password)<=128:
        raise HTTPException(422,"Зөв имэйл, 12–128 тэмдэгттэй нууц үг оруулна уу.")
    is_register=request.url.path.endswith("/register")
    with core.db() as c:
        if is_register:
            if os.getenv("ALLOW_REGISTRATION","false")!="true":
                raise HTTPException(403,"Одоогоор туршилтын бүртгэл хаалттай байна.")
            try:
                c.execute("INSERT INTO users VALUES(?,?,?,?)",(core.uid(),email,core.hash_password(password),time.time()))
            except sqlite3.IntegrityError:
                raise HTTPException(409,"Энэ имэйлээр бүртгэл үүсгэх боломжгүй байна.")
        user=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if not user or not core.verify_password(password,user["password"]):
            raise HTTPException(401,"Имэйл эсвэл нууц үг буруу байна.")
        raw,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        c.execute("DELETE FROM sessions WHERE expires<?",(time.time(),))
        c.execute("INSERT INTO sessions VALUES(?,?,?,?)",(hashlib.sha256(raw.encode()).hexdigest(),user["id"],csrf,time.time()+86400*7))
    response=JSONResponse({"user":{"email":email,"csrf":csrf}})
    response.set_cookie("session",raw,max_age=604800,httponly=True,samesite="strict",secure=SECURE,path="/")
    return response

@app.post("/api/logout")
def logout(request:Request):
    sess=session(request)
    mutation_guard(request,sess)
    with core.db() as c:
        c.execute("DELETE FROM sessions WHERE token=?",(sess["token"],))
    response=JSONResponse({})
    response.delete_cookie("session",path="/",httponly=True,samesite="strict",secure=SECURE)
    return response

@app.get("/api/voices")
def voices(request:Request):
    sess=session(request,False)
    result=[dict(v) for v in ElevenLabsEngine.configured_voices()]
    if sess:
        with core.db() as c:
            for row in c.execute("SELECT id,name,transcript,created FROM voices WHERE user_id=? ORDER BY created DESC",(sess["user_id"],)):
                result.append({"id":row["id"],"name":row["name"],"description":row["transcript"],"created":row["created"],"builtin":False})
    return {"voices":result}

@app.post("/api/voices/clone")
async def clone_voice(
    request:Request,
    name:str=Form(...),
    description:str=Form(""),
    remove_background_noise:bool=Form(False),
    consent:bool=Form(False),
    files:list[UploadFile]=File(...)
):
    sess=session(request); mutation_guard(request,sess); throttle("clone:"+sess["user_id"],8,3600)
    if not consent:
        raise HTTPException(422,"Хоолой эзэмшигчийн зөвшөөрөл шаардлагатай.")
    if not 1<=len(files)<=10:
        raise HTTPException(422,"1–10 аудио sample оруулна уу.")
    for upload in files:
        validate_upload(upload,AUDIO_EXTS,MAX_AUDIO_MB)
    job_id=core.create_tool_job(sess["user_id"],"voice_clone",name,{"files":[f.filename for f in files]})
    try:
        result=await tools.clone_voice(name,files,description,remove_background_noise)
        voice_id=result.get("voice_id")
        if not voice_id:
            raise ValueError("ElevenLabs Voice ID буцаасангүй.")
        with core.db() as c:
            c.execute(
                "INSERT OR REPLACE INTO voices(id,user_id,name,transcript,created) VALUES(?,?,?,?,?)",
                (voice_id,sess["user_id"],name[:100],description[:1000],time.time())
            )
        core.update_tool_job(job_id,"done",result=result)
        return {"job_id":job_id,**result}
    except Exception as exc:
        core.update_tool_job(job_id,"failed",error=str(exc))
        raise api_exception(exc)

@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id:str,request:Request):
    sess=session(request); mutation_guard(request,sess)
    with core.db() as c:
        row=c.execute("SELECT * FROM voices WHERE id=? AND user_id=?",(voice_id,sess["user_id"])).fetchone()
    if not row:
        raise HTTPException(404,"Хувийн clone voice олдсонгүй.")
    try:
        await tools.delete_voice(voice_id)
    except Exception as exc:
        raise api_exception(exc)
    with core.db() as c:
        c.execute("DELETE FROM voices WHERE id=? AND user_id=?",(voice_id,sess["user_id"]))
    return {"ok":True}

@app.get("/api/voices/{voice_id}/preview")
async def voice_preview(voice_id:str,request:Request):
    sess=session(request,False)
    allowed=allowed_voice_ids(sess["user_id"] if sess else None)
    if voice_id not in allowed:
        raise HTTPException(404,"Voice олдсонгүй.")
    try:
        info=await tools.get_voice(voice_id)
        url=info.get("preview_url")
        if not url:
            raise ValueError("Preview байхгүй байна.")
        audio,mime=await tools.download_url(url)
        return Response(audio,media_type=mime)
    except Exception as exc:
        raise api_exception(exc)

@app.post("/api/prepare")
async def prepare(request:Request):
    sess=session(request); mutation_guard(request,sess)
    data=await json_body(request)
    try:
        return {"text":core.prepare_text(str(data.get("text","")),data.get("glossary",{}))}
    except ValueError as exc:
        raise HTTPException(422,str(exc))

@app.get("/api/jobs")
def jobs(request:Request):
    sess=session(request)
    with core.db() as c:
        rows=[core.public_job(row) for row in c.execute("SELECT * FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT 50",(sess["user_id"],))]
    return {"jobs":rows}

@app.post("/api/jobs")
async def create_tts(request:Request):
    sess=session(request); mutation_guard(request,sess); throttle("tts:"+sess["user_id"],40)
    data=await json_body(request)
    voice_id=str(data.get("voice_id","")).strip()
    if voice_id not in allowed_voice_ids(sess["user_id"]):
        raise HTTPException(422,"Сонгосон ElevenLabs voice тохиргоонд байхгүй байна.")
    ready,reason=ElevenLabsEngine().readiness()
    if not ready: raise HTTPException(503,reason)
    title=str(data.get("title","Шинэ бүтээл")).strip()[:100] or "Шинэ бүтээл"
    try: speed=float(data.get("speed",1))
    except Exception: raise HTTPException(422,"Хурд буруу байна.")
    if not .8<=speed<=1.2: raise HTTPException(422,"Хурд 0.8–1.2 хооронд байна.")
    glossary=data.get("glossary",{})
    if not isinstance(glossary,dict) or len(glossary)>100:
        raise HTTPException(422,"Дуудлагын толь буруу байна.")
    payload={"speed":speed}
    try:
        if data.get("srt"):
            cues=core.parse_srt(str(data["srt"]))
            for cue in cues:
                cue["text"]=core.prepare_text(cue["text"],glossary)
                if len(cue["text"])>240: raise ValueError("Нэг SRT реплик 240 тэмдэгтээс хэтрэхгүй байна.")
            payload["cues"]=cues
            count=sum(len(cue["text"]) for cue in cues)
        else:
            payload["text"]=core.prepare_text(str(data.get("text","")),glossary)
            count=len(payload["text"])
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    if count>12000: raise HTTPException(422,"Нэг ажил 12000 тэмдэгтээс хэтрэхгүй байна.")
    with core.db() as c:
        active=c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running')",(sess["user_id"],)).fetchone()[0]
        if active>=3: raise HTTPException(429,"Зэрэг 3-аас олон TTS ажил үүсгэхгүй.")
        job_id=core.uid()
        c.execute(
            "INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)",
            (job_id,sess["user_id"],voice_id,title,json.dumps(payload,ensure_ascii=False),"queued",time.time())
        )
    return JSONResponse({"id":job_id},status_code=202)

@app.get("/api/jobs/{job_id}")
def get_tts_job(job_id:str,request:Request):
    sess=session(request)
    with core.db() as c:
        row=c.execute("SELECT * FROM jobs WHERE id=? AND user_id=?",(job_id,sess["user_id"])).fetchone()
    if not row: raise HTTPException(404,"Бүтээл олдсонгүй.")
    return core.public_job(row)

@app.delete("/api/jobs/{job_id}")
def delete_tts_job(job_id:str,request:Request):
    sess=session(request); mutation_guard(request,sess)
    with core.db() as c:
        row=c.execute("SELECT * FROM jobs WHERE id=? AND user_id=?",(job_id,sess["user_id"])).fetchone()
        if not row: raise HTTPException(404,"Бүтээл олдсонгүй.")
        if row["status"]=="running": raise HTTPException(409,"Ажил дууссаны дараа устгана уу.")
        c.execute("DELETE FROM jobs WHERE id=?",(job_id,))
    for ext in ("wav","mp3"):
        (core.DATA/"outputs"/f"{job_id}.{ext}").unlink(missing_ok=True)
    return {"ok":True}

@app.get("/api/jobs/{job_id}/{fmt}")
def tts_file(job_id:str,fmt:str,request:Request):
    if fmt not in {"wav","mp3"}: raise HTTPException(404)
    sess=session(request)
    with core.db() as c:
        row=c.execute("SELECT * FROM jobs WHERE id=? AND user_id=?",(job_id,sess["user_id"])).fetchone()
    if not row: raise HTTPException(404,"Бүтээл олдсонгүй.")
    if row["status"]!="done": raise HTTPException(409,"Дуу хараахан бэлэн болоогүй.")
    path=core.DATA/"outputs"/f"{job_id}.{fmt}"
    return FileResponse(path,media_type="audio/wav" if fmt=="wav" else "audio/mpeg",filename=f"rainy-voice.{fmt}")

async def run_binary_tool(request,sess,tool_type,title,runner,filename,mime,payload):
    throttle("tool:"+sess["user_id"],30)
    job_id=core.create_tool_job(sess["user_id"],tool_type,title,payload)
    try:
        data=await runner()
        artifact_id=create_artifact_bytes(sess["user_id"],job_id,"audio",filename,mime,data)
        result={"artifact_id":artifact_id}
        core.update_tool_job(job_id,"done",result=result)
        return {"job_id":job_id,**result}
    except Exception as exc:
        core.update_tool_job(job_id,"failed",error=str(exc))
        raise api_exception(exc)

@app.post("/api/tools/dialogue")
async def dialogue(request:Request):
    sess=session(request); mutation_guard(request,sess)
    data=await json_body(request)
    inputs=data.get("inputs")
    if not isinstance(inputs,list) or not 2<=len(inputs)<=30:
        raise HTTPException(422,"Podcast/Dialogue-д 2–30 мөр шаардлагатай.")
    total=0; voices_used=set(); clean=[]
    allowed=allowed_voice_ids(sess["user_id"])
    for item in inputs:
        if not isinstance(item,dict): raise HTTPException(422,"Dialogue бүтэц буруу байна.")
        voice_id=str(item.get("voice_id","")).strip(); text=str(item.get("text","")).strip()
        if voice_id not in allowed or not text: raise HTTPException(422,"Speaker voice эсвэл текст буруу байна.")
        total+=len(text); voices_used.add(voice_id); clean.append({"voice_id":voice_id,"text":text})
    if total>2000 or len(voices_used)>10:
        raise HTTPException(422,"Dialogue нийт 2000 тэмдэгт, 10 unique voice-аас хэтрэхгүй.")
    title=str(data.get("title","Podcast / Dialogue"))[:100]
    language=str(data.get("language_code","mn"))[:12]
    return await run_binary_tool(
        request,sess,"dialogue",title,
        lambda:tools.dialogue(clean,language),"rainy-dialogue.mp3","audio/mpeg",
        {"inputs":len(clean),"voices":len(voices_used),"language":language}
    )

@app.post("/api/tools/music")
async def music(request:Request):
    sess=session(request); mutation_guard(request,sess)
    data=await json_body(request)
    prompt=str(data.get("prompt","")).strip()
    try: length_ms=int(data.get("music_length_ms",30000))
    except Exception: raise HTTPException(422,"Music duration буруу байна.")
    if not prompt or len(prompt)>4100 or not 3000<=length_ms<=600000:
        raise HTTPException(422,"Music prompt 1–4100 тэмдэгт, хугацаа 3 секунд–10 минут байна.")
    model_id=str(data.get("model_id","music_v2_5"))
    if model_id not in {"music_v1","music_v2","music_v2_5"}:
        raise HTTPException(422,"Music model буруу байна.")
    force_instrumental=bool(data.get("force_instrumental",False))
    title=str(data.get("title","RAINY Music"))[:100]
    return await run_binary_tool(
        request,sess,"music",title,
        lambda:tools.music(prompt,length_ms,model_id,force_instrumental),"rainy-music.mp3","audio/mpeg",
        {"prompt":prompt[:300],"music_length_ms":length_ms,"model_id":model_id,"force_instrumental":force_instrumental}
    )

@app.post("/api/tools/sound-effects")
async def sound_effects(request:Request):
    sess=session(request); mutation_guard(request,sess)
    data=await json_body(request)
    prompt=str(data.get("text","")).strip()
    if not prompt or len(prompt)>2000: raise HTTPException(422,"Sound effect prompt буруу байна.")
    duration=data.get("duration_seconds")
    if duration in ("",None):
        duration=None
    else:
        try: duration=float(duration)
        except Exception: raise HTTPException(422,"Sound effect duration буруу байна.")
        if not .5<=duration<=30:
            raise HTTPException(422,"Sound effect duration 0.5–30 секунд байна.")
    try: influence=float(data.get("prompt_influence",.3))
    except Exception: raise HTTPException(422,"Prompt influence буруу байна.")
    if not 0<=influence<=1:
        raise HTTPException(422,"Prompt influence 0–1 хооронд байна.")
    loop=bool(data.get("loop",False))
    title=str(data.get("title","Sound Effect"))[:100]
    return await run_binary_tool(
        request,sess,"sound_effects",title,
        lambda:tools.sound_effect(prompt,duration,loop,influence),"rainy-sfx.mp3","audio/mpeg",
        {"prompt":prompt[:300],"duration_seconds":duration,"loop":loop,"prompt_influence":influence}
    )

@app.post("/api/tools/stt")
async def speech_to_text(
    request:Request,
    file:UploadFile=File(...),
    language_code:str=Form("")
):
    sess=session(request); mutation_guard(request,sess); throttle("stt:"+sess["user_id"],20)
    validate_upload(file,MEDIA_EXTS,MAX_AUDIO_MB)
    job_id=core.create_tool_job(sess["user_id"],"speech_to_text",file.filename or "Transcript",{"language":language_code or "auto"})
    try:
        result=await tools.speech_to_text(file,language_code or None)
        text=str(result.get("text",""))
        create_artifact_text(sess["user_id"],job_id,"transcript","transcript.txt","text/plain",text)
        create_artifact_text(sess["user_id"],job_id,"json","transcript.json","application/json",json.dumps(result,ensure_ascii=False,indent=2))
        srt=srt_from_words(result.get("words"))
        if srt:
            create_artifact_text(sess["user_id"],job_id,"subtitle","transcript.srt","application/x-subrip",srt)
        summary={"text":text,"language_code":result.get("language_code"),"language_probability":result.get("language_probability")}
        core.update_tool_job(job_id,"done",result=summary)
        return {"job_id":job_id,**summary}
    except Exception as exc:
        core.update_tool_job(job_id,"failed",error=str(exc))
        raise api_exception(exc)

@app.post("/api/tools/voice-changer")
async def voice_changer(
    request:Request,
    file:UploadFile=File(...),
    voice_id:str=Form(...),
    remove_background_noise:bool=Form(False)
):
    sess=session(request); mutation_guard(request,sess)
    validate_upload(file,AUDIO_EXTS,MAX_AUDIO_MB)
    if voice_id not in allowed_voice_ids(sess["user_id"]):
        raise HTTPException(422,"Target voice буруу байна.")
    title="Voice Changer"
    return await run_binary_tool(
        request,sess,"voice_changer",title,
        lambda:tools.voice_changer(file,voice_id,remove_background_noise),
        "rainy-voice-changer.mp3","audio/mpeg",{"voice_id":voice_id,"source":file.filename}
    )

@app.post("/api/tools/realtime-token")
async def realtime_token(request:Request):
    sess=session(request); mutation_guard(request,sess); throttle("realtime:"+sess["user_id"],20,3600)
    try:
        return await tools.realtime_token()
    except Exception as exc:
        raise api_exception(exc)

@app.post("/api/tools/realtime-save")
async def realtime_save(request:Request):
    sess=session(request); mutation_guard(request,sess)
    data=await json_body(request)
    text=str(data.get("text","")).strip()
    if not text or len(text)>100000:
        raise HTTPException(422,"Realtime transcript хоосон эсвэл хэт урт байна.")
    title=str(data.get("title","Realtime Transcript")).strip()[:100] or "Realtime Transcript"
    job_id=core.create_tool_job(sess["user_id"],"realtime_stt",title,{"characters":len(text)},status="done")
    artifact_id=create_artifact_text(sess["user_id"],job_id,"transcript","realtime-transcript.txt","text/plain",text)
    core.update_tool_job(job_id,"done",result={"text":text,"artifact_id":artifact_id})
    return {"job_id":job_id,"artifact_id":artifact_id}

@app.post("/api/tools/dubbing")
async def dubbing(
    request:Request,
    file:UploadFile|None=File(None),
    source_url:str=Form(""),
    reference:str=Form("RAINY Dubbing"),
    source_language:str=Form(""),
    target_language:str=Form(...)
):
    sess=session(request); mutation_guard(request,sess); throttle("dubbing:"+sess["user_id"],10,3600)
    if file and source_url:
        raise HTTPException(422,"Файл эсвэл URL-ын аль нэгийг сонгоно уу.")
    if file:
        validate_upload(file,MEDIA_EXTS,MAX_DUB_MB)
    if not file and not source_url.strip():
        raise HTTPException(422,"Видео/аудио файл эсвэл URL шаардлагатай.")
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?",target_language):
        raise HTTPException(422,"Target language code буруу байна.")
    payload={"source":file.filename if file else source_url,"source_language":source_language or None,"target_language":target_language}
    job_id=core.create_tool_job(sess["user_id"],"dubbing",reference,payload,status="queued")
    source_path=None
    try:
        result=await tools.create_dubbing(file,source_url.strip() or None,reference,source_language or None,target_language)
        if file and Path(file.filename or "").suffix.lower() in VIDEO_EXTS:
            source_path=core.DATA/"tmp"/f"{job_id}-source{Path(file.filename).suffix.lower()}"
            await persist_upload(file,source_path)
            payload["source_path"]=str(source_path)
            with core.db() as c:
                c.execute("UPDATE tool_jobs SET payload=?,updated=? WHERE id=?",(json.dumps(payload,ensure_ascii=False),time.time(),job_id))
        core.update_tool_job(job_id,result=result,status=result.get("status","queued"))
        return {"job_id":job_id,**result}
    except Exception as exc:
        if source_path:
            source_path.unlink(missing_ok=True)
        core.update_tool_job(job_id,"failed",error=str(exc))
        raise api_exception(exc)

@app.get("/api/tools/dubbing/{job_id}")
async def dubbing_status(job_id:str,request:Request):
    sess=session(request)
    with core.db() as c:
        row=c.execute("SELECT * FROM tool_jobs WHERE id=? AND user_id=? AND tool_type='dubbing'",(job_id,sess["user_id"])).fetchone()
    if not row: raise HTTPException(404,"Dubbing project олдсонгүй.")
    payload=json.loads(row["payload"] or "{}")
    result=json.loads(row["result"] or "{}")
    project_id=result.get("project_id")
    if not project_id: return public_tool_job_with_artifacts(row)
    try:
        project=await tools.get_dubbing_project(project_id)
        language_data=await tools.list_dubbing_languages(project_id)
        languages=language_data.get("languages",[])
        status=project.get("status","queued")
        if languages:
            statuses=[x.get("status") for x in languages]
            if "failed" in statuses: status="failed"
            elif any(x in {"completed","stale"} for x in statuses): status="done"
            elif any(x=="processing" for x in statuses): status="processing"
            else: status="queued"
        merged={"project_id":project_id,"project":project,"languages":languages}
        with core.db() as c:
            artifact_count=c.execute("SELECT COUNT(*) FROM artifacts WHERE job_id=?",(job_id,)).fetchone()[0]
        if status=="done" and not artifact_count:
            for lang in languages:
                if lang.get("status") not in {"completed","stale"}: continue
                for kind,url in (lang.get("outputs") or {}).items():
                    if not isinstance(url,str) or not url.startswith("http"): continue
                    data,mime=await tools.download_url(url)
                    ext=mimetypes.guess_extension(mime.split(";")[0]) or (".flac" if "audio" in mime else ".bin")
                    create_artifact_bytes(sess["user_id"],job_id,kind,f"dubbing-{lang.get('target_language','target')}{ext}",mime,data)
            source_path=Path(payload["source_path"]) if payload.get("source_path") else None
            if source_path and source_path.is_file():
                with core.db() as c:
                    audio_row=c.execute(
                        "SELECT * FROM artifacts WHERE job_id=? AND user_id=? AND mime LIKE 'audio/%' ORDER BY created LIMIT 1",
                        (job_id,sess["user_id"])
                    ).fetchone()
                if audio_row:
                    video_path=core.DATA/"artifacts"/(core.uid()+".mp4")
                    try:
                        mux_dubbed_video(source_path,Path(audio_row["path"]),video_path)
                        core.add_artifact(job_id,sess["user_id"],"dubbed_video","rainy-dubbed-video.mp4","video/mp4",video_path)
                    finally:
                        source_path.unlink(missing_ok=True)
        if status=="failed" and payload.get("source_path"):
            Path(payload["source_path"]).unlink(missing_ok=True)
        core.update_tool_job(job_id,status,result=merged,error="Dubbing failed" if status=="failed" else None)
        with core.db() as c:
            row=c.execute("SELECT * FROM tool_jobs WHERE id=?",(job_id,)).fetchone()
        return public_tool_job_with_artifacts(row)
    except Exception as exc:
        raise api_exception(exc)

@app.get("/api/tool-jobs")
def tool_jobs(request:Request):
    sess=session(request)
    with core.db() as c:
        rows=c.execute("SELECT * FROM tool_jobs WHERE user_id=? ORDER BY created DESC LIMIT 100",(sess["user_id"],)).fetchall()
    return {"jobs":[public_tool_job_with_artifacts(row) for row in rows]}

@app.delete("/api/tool-jobs/{job_id}")
def delete_tool_job(job_id:str,request:Request):
    sess=session(request); mutation_guard(request,sess)
    with core.db() as c:
        row=c.execute("SELECT * FROM tool_jobs WHERE id=? AND user_id=?",(job_id,sess["user_id"])).fetchone()
        if not row: raise HTTPException(404,"Project олдсонгүй.")
        artifacts=c.execute("SELECT path FROM artifacts WHERE job_id=?",(job_id,)).fetchall()
        try:
            payload=json.loads(row["payload"] or "{}")
        except Exception:
            payload={}
        c.execute("DELETE FROM tool_jobs WHERE id=?",(job_id,))
    for artifact in artifacts:
        Path(artifact["path"]).unlink(missing_ok=True)
    if payload.get("source_path"):
        Path(payload["source_path"]).unlink(missing_ok=True)
    return {"ok":True}

@app.get("/api/artifacts/{artifact_id}")
def artifact(artifact_id:str,request:Request):
    sess=session(request)
    with core.db() as c:
        row=c.execute("SELECT * FROM artifacts WHERE id=? AND user_id=?",(artifact_id,sess["user_id"])).fetchone()
    if not row: raise HTTPException(404,"Файл олдсонгүй.")
    path=Path(row["path"])
    if not path.is_file(): raise HTTPException(404,"Файл олдсонгүй.")
    return FileResponse(path,media_type=row["mime"],filename=row["filename"])

@app.get("/api/history")
def history(request:Request):
    sess=session(request)
    items=[]
    with core.db() as c:
        for row in c.execute("SELECT * FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT 50",(sess["user_id"],)):
            item=core.public_job(row); item["tool_type"]="tts"; item["source"]="tts"
            item["artifacts"]=[]
            if row["status"]=="done":
                item["artifacts"]=[
                    {"kind":"audio","filename":"rainy-voice.wav","url":f"/api/jobs/{row['id']}/wav"},
                    {"kind":"audio","filename":"rainy-voice.mp3","url":f"/api/jobs/{row['id']}/mp3"}
                ]
            items.append(item)
        for row in c.execute("SELECT * FROM tool_jobs WHERE user_id=? ORDER BY created DESC LIMIT 100",(sess["user_id"],)):
            item=public_tool_job_with_artifacts(row); item["source"]="tool"
            for art in item["artifacts"]:
                art["url"]=f"/api/artifacts/{art['id']}"
            items.append(item)
    items.sort(key=lambda x:x["created"],reverse=True)
    return {"items":items[:100]}

@app.get("/api/analytics")
async def analytics(request:Request):
    sess=session(request)
    end=int(time.time()*1000); start=end-30*86400*1000
    local={}
    with core.db() as c:
        local["tts"]=c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND created>?",(sess["user_id"],time.time()-30*86400)).fetchone()[0]
        for row in c.execute("SELECT tool_type,COUNT(*) count FROM tool_jobs WHERE user_id=? AND created>? GROUP BY tool_type",(sess["user_id"],time.time()-30*86400)):
            local[row["tool_type"]]=row["count"]
    result={"local_30d":local}
    try:
        result["subscription"]=await tools.subscription()
        result["usage"]=await tools.usage(start,end,86400)
    except ElevenAPIError as exc:
        result["eleven_error"]=str(exc)
    return result

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    core.init()
    uvicorn.run("app.server:app",host=os.getenv("HOST","127.0.0.1"),port=int(os.getenv("PORT","8080")),reload=False)
