"""Safe, bounded MP4 assembly for completed RAVS video clips and Voice jobs.

The RAVS and Voice sites remain independent. No provider API key crosses this
boundary. Media URLs are untrusted, so an operator allowlist is mandatory.
"""
import asyncio
import ipaddress
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from urllib.parse import urlsplit

import httpx
from . import core, billing, durable_jobs
from . import movie_mastering, movie_visual_qa

MAX_CLIPS = 120
MAX_CLIP_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 900 * 1024 * 1024
MAX_MOVIE_SECONDS = 3600
RATIOS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}

def trusted_hosts():
    return {host.strip().lower() for host in os.getenv("RAINY_MOVIE_MEDIA_HOSTS", "").split(",")
            if host.strip() and not any(c in host for c in "/:@*? " )}

def public_ip_resolves(host):
    try:
        records=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError("Видео CDN DNS олдсонгүй.")
    if not records:
        raise ValueError("Видео CDN DNS олдсонгүй.")
    for record in records:
        ip=ipaddress.ip_address(record[4][0])
        if not ip.is_global:
            raise ValueError("Дотоод, local, multicast IP рүү видео татахгүй.")
    return True

def validate_video_url(value, resolve=False):
    if not isinstance(value,str) or not 12<=len(value)<=3000:
        raise ValueError("Видео URL буруу байна.")
    try:
        url=urlsplit(value)
        permitted=(url.scheme=="https" and bool(url.hostname) and
                   not url.username and not url.password and not url.fragment and url.port in (None,443))
    except ValueError:
        permitted=False
    if not permitted:
        raise ValueError("Видео зөвхөн HTTPS, 443 порттой URL байх ёстой.")
    host=url.hostname.lower()
    if not trusted_hosts() or host not in trusted_hosts():
        raise ValueError("Видео URL баталгаатай CDN allowlist-д байхгүй байна.")
    try: ipaddress.ip_address(host)
    except ValueError: pass
    else: raise ValueError("IP хаягаар шууд татах хориотой.")
    if resolve: public_ip_resolves(host)
    return value

def quote_movie(video_urls, target_seconds, aspect_ratio, voice_job_id=None, user_id=None, options=None):
    if not isinstance(video_urls,list) or not 1<=len(video_urls)<=MAX_CLIPS:
        raise ValueError("1–120 бэлэн видео клип оруулна.")
    for url in video_urls:
        validate_video_url(url)
    if len(set(video_urls))!=len(video_urls):
        raise ValueError("Клипийн URL давхардсан байна.")
    if type(target_seconds) not in (int,float) or not math.isfinite(target_seconds) or not 4<=target_seconds<=MAX_MOVIE_SECONDS:
        raise ValueError("Эцсийн кино 4–3600 секундийн хооронд байна.")
    if aspect_ratio not in RATIOS:
        raise ValueError("Хэмжээ: 9:16, 16:9 эсвэл 1:1 байна.")
    if voice_job_id is not None:
        if not isinstance(voice_job_id,str) or len(voice_job_id)>80 or not user_id:
            raise ValueError("Voice job ID буруу байна.")
        with core.db() as c:
            voice=c.execute("SELECT status FROM jobs WHERE id=? AND user_id=?",(voice_job_id,user_id)).fetchone()
        if not voice or voice["status"]!="done":
            raise ValueError("Voice audio хараахан бэлэн биш эсвэл таны бүтээл биш байна.")
    master=movie_mastering.master_settings(options,target_seconds,aspect_ratio)
    if user_id:
        movie_mastering.owned_artifact(user_id,master["music_artifact_id"],"audio")
        movie_mastering.owned_artifact(user_id,master["subtitle_artifact_id"],"subtitle")
    rate=int(os.getenv("RAINY_MOVIE_ASSEMBLY_CREDITS_PER_MIN", "20"))
    if not 0<=rate<=100000:
        raise ValueError("Видео эвлүүлгийн кредитийн тохиргоо буруу байна.")
    credits=max(0,math.ceil(target_seconds/60)*rate)
    return {"credits":credits,"clipCount":len(video_urls),"targetSeconds":target_seconds,
            "aspectRatio":aspect_ratio,"voiceAudioAttached":bool(voice_job_id),
            "outputQuality":master["quality"],"dimensions":master["dimensions"],
            "native4KRequired":master["quality"]=="4k",
            "maxMovieSeconds":MAX_MOVIE_SECONDS,
            "note":"Урьдчилсан эвлүүлгийн кредит. Видео болон Voice генерацын кредит тусдаа; media CDN allowlist зайлшгүй."}

def enqueue_movie(user_id, urls, seconds, ratio, voice_job_id, key, payload_hash, credits, options=None):
    """Atomically reserve compute credits, queue local work and the replay key."""
    billing.ensure_wallet(user_id)
    billing._expire_if_needed(user_id)
    durable_jobs.ensure_schema()
    job_id=core.uid()
    now=__import__("time").time()
    paid=billing.billing_enabled() and not billing.admin_test_mode(user_id)
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        prior=c.execute("SELECT job,payload_hash FROM vmcp_movie_requests WHERE uid=? AND request_key=?",(user_id,key)).fetchone()
        if prior:
            if prior["payload_hash"]!=payload_hash:
                raise ValueError("Ижил idempotencyKey өөр movie хүсэлтэд ашиглагдсан.")
            existing=c.execute("SELECT status FROM tool_jobs WHERE id=? AND user_id=?",(prior["job"],user_id)).fetchone()
            return {"job_id":prior["job"],"status":existing["status"] if existing else "pending_reconciliation",
                    "reused":True,"credits_used":0}
        user=c.execute("SELECT email FROM users WHERE id=?",(user_id,)).fetchone()
        if not user or user["email"].endswith("@deleted.invalid"):
            raise ValueError("Бүртгэл идэвхгүй байна.")
        active=c.execute("SELECT COUNT(*) FROM tool_jobs WHERE user_id=? AND tool_type='video_assembly' AND status IN ('queued','running')",(user_id,)).fetchone()[0]
        if active>=1:
            raise ValueError("Нэг удаад зөвхөн нэг MP4 эвлүүлэг ажиллуулна.")
        charge_id=core.uid() if credits and paid else None
        if charge_id:
            wallet=c.execute("SELECT balance FROM credit_wallets WHERE user_id=?",(user_id,)).fetchone()
            if not wallet or wallet["balance"]<credits:
                raise ValueError("Credit хүрэлцэхгүй байна.")
            balance=wallet["balance"]-credits
            c.execute("UPDATE credit_wallets SET balance=?,lifetime_out=lifetime_out+?,updated=? WHERE user_id=?",
                      (balance,credits,now,user_id))
            c.execute("INSERT INTO credit_ledger VALUES(?,?,?,?,?,?,?,?,?)",
                      (charge_id,user_id,"usage",-credits,balance,"video_assembly",job_id,json.dumps({"clip_count":len(urls)}),now))
        c.execute("INSERT INTO tool_jobs(id,user_id,tool_type,title,payload,status,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                  (job_id,user_id,"video_assembly","RAINY One-Prompt Movie",json.dumps({"billing":{"credits":credits if paid else 0,"charge_id":charge_id}}),
                   "queued",now,now))
        execution={"method":"assemble_video","args":[urls,float(seconds),ratio,voice_job_id,options or {}]}
        c.execute("INSERT INTO durable_jobs VALUES(?,?,?,?,?,?,?,?,?)",
                  (job_id,json.dumps(execution,ensure_ascii=False),charge_id,credits if paid else 0,
                   "rainy-final-movie.mp4","video/mp4",None,None,None))
        c.execute("INSERT INTO vmcp_movie_requests(uid,request_key,payload_hash,job,created) VALUES(?,?,?,?,?)",
                  (user_id,key,payload_hash,job_id,now))
    return {"job_id":job_id,"status":"queued","reused":False,"credits_used":credits if paid else 0}

async def download_clip(url,output,total):
    validate_video_url(url,resolve=True)
    host=urlsplit(url).hostname
    # Redirects are forbidden. An allowlisted CDN must return the media itself.
    async with httpx.AsyncClient(timeout=httpx.Timeout(120,connect=12),follow_redirects=False,trust_env=False) as client:
        async with client.stream("GET",url,headers={"Accept":"video/mp4,application/octet-stream"}) as response:
            if response.status_code!=200:
                raise ValueError("Видео CDN таталт амжилтгүй.")
            if int(response.headers.get("content-length","0") or 0)>MAX_CLIP_BYTES:
                raise ValueError("Клип 100 MB-аас их байна.")
            mime=response.headers.get("content-type","").split(";")[0].lower().strip()
            if mime and mime not in {"video/mp4","video/quicktime","application/octet-stream","binary/octet-stream"}:
                raise ValueError("CDN видео биш файл буцаасан.")
            size=0
            with output.open("wb") as fp:
                async for chunk in response.aiter_bytes(chunk_size=262144):
                    size+=len(chunk)
                    if size>MAX_CLIP_BYTES or total[0]+size>MAX_TOTAL_BYTES:
                        raise ValueError("Медиа файлын хэмжээ дээд хязгаараас хэтэрлээ.")
                    fp.write(chunk)
            total[0]+=size
            with output.open("rb") as fp:
                head=fp.read(16)
            if len(head)<12 or head[4:8]!=b"ftyp":
                raise ValueError("MP4 container танигдсангүй.")
    return output

def probe_audio_duration(path):
    try:
        p=subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1",str(path)],
            check=True,timeout=35,capture_output=True,text=True,
        )
        duration=float(p.stdout.strip())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Дууны урт буруу.")
        return duration
    except (subprocess.SubprocessError, ValueError, TypeError):
        raise ValueError("Voice аудионы үргэлжлэх хугацааг уншиж чадсангүй.")

def run_ffmpeg(args,timeout=900):
    try:
        subprocess.run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",*args],
                       check=True,timeout=timeout,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
        raise ValueError("Видео эвлүүлэг алдаа гарлаа. Кредитийн буцаалтыг шалгана уу.")

def probe_media(path):
    try:
        p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type",
                          "-of","json",str(path)],check=True,timeout=40,capture_output=True,text=True)
        data=json.loads(p.stdout)
        duration=float(data.get("format",{}).get("duration",0))
        types={s.get("codec_type") for s in data.get("streams",[])}
        if "video" not in types or not 0.5<=duration<=60 or not math.isfinite(duration):
            raise ValueError("Клипийн хугацаа эсвэл video stream буруу байна.")
        return duration,"audio" in types
    except (ValueError,subprocess.SubprocessError,KeyError):
        raise ValueError("Клипийн кодек эсвэл хугацааг шалгаж чадсангүй.")

def probe_dimensions(path):
    try:
        p=subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
                          "-show_entries","stream=width,height","-of","json",str(path)],
                         capture_output=True,text=True,check=True,timeout=25)
        entry=json.loads(p.stdout)["streams"][0]
        return int(entry["width"]),int(entry["height"])
    except (ValueError,IndexError,KeyError,subprocess.SubprocessError):
        raise ValueError("Эх клипийн нягтаршил тодорхойгүй.")

def verify_export(path, expected_seconds, ratio, quality="720p"):
    """Measure objective output properties; do not claim semantic/cinematic quality."""
    try:
        p=subprocess.run(
            ["ffprobe","-v","error","-show_entries",
             "format=duration,size:stream=index,codec_type,codec_name,width,height,avg_frame_rate",
             "-of","json",str(path)],
            timeout=50,capture_output=True,check=True,text=True,
        )
        data=json.loads(p.stdout)
        duration=float(data.get("format",{}).get("duration",0))
        video=next((t for t in data.get("streams",[]) if t.get("codec_type")=="video"),None)
        audio=next((t for t in data.get("streams",[]) if t.get("codec_type")=="audio"),None)
        if not video or not audio:
            raise ValueError("MP4 video эсвэл audio track дутуу.")
        width,height=movie_mastering.PROFILE_DIMS[quality][ratio]
        if video.get("width")!=width or video.get("height")!=height:
            raise ValueError("Эцсийн видео харьцаа буруу байна.")
        if not math.isfinite(duration) or abs(duration-expected_seconds)>1.1:
            raise ValueError("Видео duration ба захиалсан хугацаа зөрж байна.")
        rate=video.get("avg_frame_rate","0/1").split("/")
        fps=float(rate[0])/float(rate[1]) if len(rate)==2 and float(rate[1]) else 0
        if not 23<=fps<=60:
            raise ValueError("Эцсийн MP4 frame rate шаардлага хангахгүй.")
        if path.stat().st_size<4096:
            raise ValueError("MP4 файл хоосон байна.")
        return {"status":"structural_pass","durationSeconds":round(duration,3),
                "width":width,"height":height,"fps":round(fps,3),
                "videoCodec":video.get("codec_name"),"audioCodec":audio.get("codec_name"),
                "fileBytes":path.stat().st_size,
                "semanticQuality":"not_verified",
                "note":"Structure, duration, fps, audio шалгасан. Кадрын дүр, нүүр, текст/брэнд, уран сайхны continuity болон дууны агуулгыг хүний хяналтаар шалгана."}
    except (subprocess.SubprocessError,StopIteration,KeyError,ValueError,TypeError) as exc:
        raise ValueError("Эцсийн MP4 QA шалгалт амжилтгүй: "+str(exc)[:150])

async def assemble_movie(user_id,job_id,urls,target_seconds,ratio,voice_id,options=None):
    if shutil.disk_usage(core.DATA).free < 1024*1024*1024:
        raise ValueError("Media storage-д 1 GB сул зай шаардлагатай.")
    if ratio not in RATIOS: raise ValueError("Хэмжээ буруу.")
    master=movie_mastering.master_settings(options,target_seconds,ratio)
    for url in urls: validate_video_url(url,resolve=True)
    music_file=movie_mastering.owned_artifact(user_id,master["music_artifact_id"],"audio")
    subtitle_file=movie_mastering.owned_artifact(user_id,master["subtitle_artifact_id"],"subtitle") if master["subtitle_burn_in"] else None
    voice_file=None
    if voice_id:
        with core.db() as c:
            source=c.execute("SELECT status FROM jobs WHERE id=? AND user_id=?",(voice_id,user_id)).fetchone()
        candidate=core.DATA/"outputs"/(voice_id+".wav")
        if not source or source["status"]!="done" or not candidate.is_file():
            raise ValueError("Voice аудио файл олдсонгүй.")
        audio_seconds=await asyncio.to_thread(probe_audio_duration,candidate)
        if audio_seconds > target_seconds+0.35:
            raise ValueError(f"Voice audio ({audio_seconds:.1f}s) нь хүссэн киноны урт ({target_seconds:.1f}s)-аас их; тайрч алга болгохгүй.")
        voice_file=candidate
    work=Path(tempfile.mkdtemp(prefix="movie-",dir=core.DATA/"tmp"))
    out=core.DATA/"artifacts"/(core.uid()+".mp4")
    try:
        count=[0]
        width,height=master["dimensions"]
        normalized=[]
        total_duration=0
        for i,url in enumerate(urls):
            original=work/f"source-{i:03d}.mp4"
            await download_clip(url,original,count)
            duration,has_audio=await asyncio.to_thread(probe_media,original)
            if master["ai_qa_consent"]:
                visual=await movie_visual_qa.inspect_video(original,work,True)
                if visual["status"]=="reviewed" and not visual["passed"]:
                    raise ValueError("AI QA энэ клипийг дахин боловсруулах шаардлагатай гэж үзлээ. RAVS-д scene retry зөвшөөрөх эсэхийг шийднэ.")
            if master["quality"]=="4k":
                original_size=await asyncio.to_thread(probe_dimensions,original)
                if original_size[0]<width or original_size[1]<height:
                    raise ValueError("4K гэж бичсэн боловч эх клип 4K биш. Upscale-ийг native 4K гэж зарахгүй.")
            total_duration+=duration
            converted=work/f"clip-{i:03d}.mp4"
            args=["-i",str(original)]
            if not has_audio:
                args+=["-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=48000"]
            vf=f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=24,format=yuv420p"
            args+=["-map","0:v:0","-map","0:a:0" if has_audio else "1:a:0",
                   "-vf",vf,"-c:v","libx264","-preset","medium","-crf","18",
                   "-c:a","aac","-ar","48000","-b:a","128k","-af","apad",
                   "-t",str(round(duration,3)),"-movflags","+faststart",str(converted)]
            await asyncio.to_thread(run_ffmpeg,args,300)
            normalized.append(converted)
        if total_duration+2<float(target_seconds):
            raise ValueError("Энэ нийт уртад видео клипүүд хүрэлцэхгүй. Дутуу scene-ээ нэмж үүсгэнэ үү.")
        concat_file=work/"concat.txt"
        concat_file.write_text("".join(f"file '{p.name}'\n" for p in normalized),encoding="utf-8")
        silent=work/"movie-no-voice.mp4"
        await asyncio.to_thread(run_ffmpeg,["-f","concat","-safe","0","-i",str(concat_file),
                                            "-map","0:v:0","-map","0:a:0","-c","copy",
                                            "-t",str(target_seconds),"-movflags","+faststart",str(silent)],1800)
        if voice_file or music_file or subtitle_file:
            args=["-i",str(silent)]
            voice_index=None
            music_index=None
            if voice_file:
                voice_index=len(args)//2
                args+=["-i",str(voice_file)]
            if music_file:
                music_index=1+(1 if voice_file else 0)
                args+=["-i",str(music_file)]
            graph=movie_mastering.audio_filtergraph(1 if voice_file else None,music_index,master["master_audio"])
            args+=["-filter_complex",graph,"-map","0:v:0","-map","[mix]"]
            if subtitle_file:
                local_srt=work/"subtitles.srt"
                shutil.copyfile(subtitle_file,local_srt)
                args+=["-vf","subtitles="+str(local_srt),"-c:v","libx264",
                       "-preset","medium","-crf","18"]
            else:
                args+=["-c:v","copy"]
            args+=["-c:a","aac","-b:a","192k","-t",str(target_seconds),
                   "-movflags","+faststart",str(out)]
            await asyncio.to_thread(run_ffmpeg,args,2400)
        else:
            shutil.move(str(silent),str(out))
        quality_report=await asyncio.to_thread(verify_export,out,target_seconds,ratio,master["quality"])
        artifact_id=core.add_artifact(job_id,user_id,"movie","rainy-final-movie.mp4","video/mp4",out)
        return {"artifact_id":artifact_id,"clip_count":len(urls),"requested_seconds":target_seconds,
                "voice_over":bool(voice_file),"music_added":bool(music_file),
                "subtitles_burned":bool(subtitle_file),"output_quality":master["quality"],
                "upscaling_warning":master["quality"]=="1080p",
                "vision_qa":"consent_gated" if master["ai_qa_consent"] else "not_requested",
                "quality_report":quality_report}
    except Exception:
        out.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work,ignore_errors=True)
