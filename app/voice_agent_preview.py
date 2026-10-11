"""Admin-gated ElevenAgents live voice preview.

This is NOT an unmetered customer product. Signed URLs are issued only to
authorized admins, only when enabled and an approved agent is configured.
The provider account is billed outside RAINY's TTS wallet.
"""
import os
import re
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException, Request

def enabled():
    agent=os.getenv("ELEVENLABS_AGENT_ID","").strip()
    return (os.getenv("LIVE_AGENT_ADMIN_PREVIEW_ENABLED","false").lower()=="true"
        and bool(re.fullmatch(r"[A-Za-z0-9_-]{5,100}",agent))
        and bool(os.getenv("ELEVENLABS_API_KEY","").strip()))

def register_routes(app,admin_user,mutation_guard,throttle):
    @app.get("/api/production/agent-status")
    def agent_status(request:Request):
        admin_user(request)
        return {"enabled":enabled(),"adminOnly":True,
            "message":"Туршилтын agent-ийг зөвхөн админ ашиглана. ElevenLabs-ийн минутын төлбөр RAINY credit wallet-д холбогдоогүй. Provider эрх болон Agent ID баталгаажсаны дараа идэвхжүүлнэ."}

    @app.post("/api/production/agent-session")
    async def agent_session(request:Request):
        user=admin_user(request);mutation_guard(request,user)
        throttle("agent-preview:"+user["user_id"],4,3600)
        if not enabled():
            raise HTTPException(503,"AI agent туршилт хараахан идэвхгүй байна.")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(18,connect=8),follow_redirects=False,trust_env=False) as client:
                r=await client.get("https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
                    params={"agent_id":os.environ["ELEVENLABS_AGENT_ID"]},
                    headers={"xi-api-key":os.environ["ELEVENLABS_API_KEY"]})
            if r.status_code!=200:
                raise HTTPException(503,"ElevenAgents эрх эсвэл агентын тохиргоо баталгаажаагүй байна.")
            url=r.json().get("signed_url")
            parsed=urlsplit(url) if isinstance(url,str) else None
            if not parsed or parsed.scheme!="wss" or parsed.hostname!="api.elevenlabs.io" or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("signed websocket URL invalid")
            return {"signed_url":url,"providerBilled":True,"adminOnly":True}
        except HTTPException:raise
        except Exception:raise HTTPException(503,"AI agent холболт түр боломжгүй байна.")
