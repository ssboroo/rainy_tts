"""Real visual-frame review through an optional consent-gated multimodal provider.
No AI aesthetic judgement is claimed when the provider is unavailable.
"""
import base64
import json
import os
import subprocess
from pathlib import Path
import httpx

def available():
    return (os.getenv("RAINY_MOVIE_AI_QA_ENABLED","false").lower()=="true" and
            bool(os.getenv("OPENAI_API_KEY","")))

def frames(video,work):
    images=[]
    probe=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                          "-of","default=noprint_wrappers=1:nokey=1",str(video)],
                         check=True,capture_output=True,text=True,timeout=20)
    duration=float(probe.stdout.strip())
    if not 0.5<=duration<=60: raise ValueError("QA clip хугацаа буруу.")
    for index, fraction in enumerate((0.15,0.50,0.85)):
        output=work/("review-%s.jpg"%index)
        # Only local FFmpeg reads; sample three distinct timestamps.
        subprocess.run(["ffmpeg","-nostdin","-v","error","-y",
                        "-ss",str(round(duration*fraction,3)),"-i",str(video),
                        "-vf","scale=512:-2","-frames:v","1",str(output)],
                       check=True,capture_output=True,timeout=60)
        if output.stat().st_size>1_000_000:
            raise ValueError("AI QA зураг 1 MB-аас хэтэрлээ.")
        images.append(output)
    return images

async def inspect_video(video:Path,work:Path,consent:bool):
    if not consent:
        return {"status":"not_requested","note":"Агуулгыг гадаад AI QA руу илгээх зөвшөөрөл өгөөгүй."}
    if not available():
        return {"status":"not_available","note":"AI visual QA provider идэвхгүй, шалгалт хийсэн гэж мэдэгдэхгүй."}
    shots=frames(video,work)
    parts=[{"type":"input_text","text":
        "Examine these sampled frames from a generated commercial. Return ONLY compact JSON "
        "{\"pass\":boolean,\"score\":number,\"defects\":string[],\"uncertainty\":string}. "
        "Find obvious garbling, duplicated limbs, unnatural faces, unreadable on-screen text, "
        "object deformation and black/frozen-looking frames. Score 0-100. "
        "Three stills are insufficient to certify motion, lip-sync, audio or full continuity. "
        "If uncertain explain why. No claim of perfection."}]
    for shot in shots:
        b64=base64.b64encode(shot.read_bytes()).decode("ascii")
        parts.append({"type":"input_image","image_url":"data:image/jpeg;base64,"+b64,"detail":"low"})
    body={"model":os.getenv("RAINY_MOVIE_QA_MODEL","gpt-4.1-mini"),
          "input":[{"role":"user","content":parts}],"max_output_tokens":350,"store":False}
    try:
        async with httpx.AsyncClient(timeout=100,trust_env=False) as client:
            resp=await client.post("https://api.openai.com/v1/responses",
              headers={"Authorization":"Bearer "+os.environ["OPENAI_API_KEY"],"Content-Type":"application/json"},
              json=body)
            resp.raise_for_status()
            data=resp.json()
        candidates=[item.get("text","") for out in data.get("output",[])
                    for item in out.get("content",[]) if item.get("type")=="output_text"]
        raw="".join(candidates).strip()
        if raw.startswith("&#96;"):
            raise ValueError("Invalid JSON response")
        result=json.loads(raw)
        score=result.get("score")
        if not isinstance(score,(int,float)) or isinstance(score,bool) or not 0<=score<=100:
            raise ValueError("Invalid vision QA score")
        defects=result.get("defects",[])
        if not isinstance(defects,list):defects=[]
        return {"status":"reviewed","score":int(score),"passed":bool(result.get("pass",False)) and score>=75,
                "defects":[str(x)[:160] for x in defects[:8]],
                "uncertainty":str(result.get("uncertainty",""))[:300],
                "samples":len(shots),"model":body["model"],
                "note":"Хүрээний түүвэр AI үнэлгээ. 100% scene review, lip-sync, continuity баталгаа биш."}
    except Exception:
        return {"status":"provider_unavailable","note":"AI QA-г баттай хийж чадсангүй; хүрээний семантик чанар баталгаажаагүй."}
