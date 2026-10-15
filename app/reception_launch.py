"""Connection readiness and explicit, *illustrative* ElevenAgents business economics.

No provider calls are made while quoting or reading status. Agent linking makes
a live provider GET to prove the workspace key can read the agent; it does NOT
provision telephony or start a billable call.
"""
import math
import os
import re
import time
import httpx
from fastapi import HTTPException, Request
from . import core

PLANS={
    "free":{"usd":0.0,"minutes":15,"calls":4},
    "starter":{"usd":6.0,"minutes":75,"calls":6},
    "creator":{"usd":22.0,"minutes":275,"calls":10},
    "pro":{"usd":99.0,"minutes":1238,"calls":20},
    "scale":{"usd":299.0,"minutes":3738,"calls":30},
    "business":{"usd":990.0,"minutes":12375,"calls":40},
}
EXTRA_MINUTE_USD=0.08
BURST_MINUTE_USD=0.16
MARKUP_PERCENT=70
DOC_URL="https://elevenlabs.io/pricing/agents"

def ensure_schema():
    with core.db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS reception_agents(
          user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          agent_id TEXT NOT NULL, agent_name TEXT NOT NULL,
          language TEXT NOT NULL, phone_count INTEGER NOT NULL DEFAULT 0,
          checked_at REAL NOT NULL
        )""")

def current_agent(user_id):
    ensure_schema()
    with core.db() as db:
        row=db.execute(
            "SELECT agent_id,agent_name,language,phone_count,checked_at FROM reception_agents WHERE user_id=?",
            (user_id,)).fetchone()
    return dict(row) if row else None

def agent_id(user_id):
    row=current_agent(user_id)
    return row["agent_id"] if row else os.getenv("ELEVENLABS_AGENT_ID","").strip()

def agent_ready(user_id):
    key=bool(os.getenv("ELEVENLABS_API_KEY","").strip())
    feature=os.getenv("LIVE_AGENT_ADMIN_PREVIEW_ENABLED","false").lower()=="true"
    aid=agent_id(user_id)
    valid=bool(re.fullmatch(r"[A-Za-z0-9_-]{5,100}",aid))
    return key and feature and valid

def launch_status(user_id,origin):
    from . import reception_booking,reception_knowledge,reception_public
    ensure_schema()
    business=reception_knowledge.read_business(user_id)
    services=reception_booking.list_services(user_id)
    sources=reception_knowledge.list_sources(user_id)["items"]
    google=reception_knowledge.google_status()
    booking=reception_public.link_status(user_id,origin)
    agent=current_agent(user_id)
    key=bool(os.getenv("ELEVENLABS_API_KEY","").strip())
    preview=os.getenv("LIVE_AGENT_ADMIN_PREVIEW_ENABLED","false").lower()=="true"
    connected=bool(agent and agent["checked_at"]>time.time()-86400)
    voice=connected and key and preview
    phone=bool(connected and agent["phone_count"]>0)
    steps={
        "business":{"ready":bool(business["name"].strip()),"detail":business["name"] or "Байгууллагын нэр, хаяг, цагийг бүртгэнэ."},
        "services":{"ready":any(not s["id"].startswith("default-") for s in services),"detail":str(len(services))+" үйлчилгээ"},
        "knowledge":{"ready":bool(sources),"detail":str(len(sources))+" эх сурвалж"},
        "google_sheets":{"ready":any(x["kind"]=="sheet" for x in sources),"detail":google["mode"]},
        "booking_link":{"ready":booking["enabled"],"detail":"Идэвхтэй" if booking["enabled"] else "Холбоос идэвхгүй"},
        "voice_agent":{"ready":voice,"detail":("Туршигдах боломжтой" if voice else "ElevenAgents ID + API эрх + админы live зөвшөөрөл шаардлагатай")},
        "telephony":{"ready":phone,"detail":("Агент дээр дугаар холбогдсон; бодит дуудлага шалгана" if phone else "Монгол операторын SIP / Twilio дугаар холбох")},
    }
    ready_count=sum(bool(v["ready"]) for v in steps.values())
    return {"mode":"ready" if ready_count==len(steps) else "partial" if ready_count else "setup",
            "ready_steps":ready_count,"total_steps":len(steps),"steps":steps,
            "agent_name":agent["agent_name"] if agent else None,
            "agent_id":agent["agent_id"] if agent else None,
            "agent_language":agent["language"] if agent else None,
            "agent_last_verified":agent["checked_at"] if agent else None,
            "agent_phone_count":agent["phone_count"] if agent else 0,
            "voice_key_present":key,"voice_preview_allowed":preview,
            "google_mode":google["mode"],"google_service_account_email":google.get("account_email"),
            "booking_url":booking["url"],"price_source":DOC_URL,
            "important":"Статус нь тохиргооны шалгалт; бодит утасны дуудлага, Монгол ярианы чанарыг батлахгүй."}

def _number(payload,key,low,high,integer=False):
    value=payload.get(key)
    if (type(value) not in (int,float) or not math.isfinite(value) or
        value<low or value>high or (integer and type(value) is not int)):
        raise HTTPException(422,key+" талбарын утга зөв биш байна.")
    return value

def estimate(payload):
    if not isinstance(payload,dict) or payload.get("plan") not in PLANS:
        raise HTTPException(422,"ElevenAgents-ийн багц буруу байна.")
    plan=PLANS[payload["plan"]]
    calls=_number(payload,"calls",0,100000,True)
    avg=_number(payload,"avg_minutes",0.5,120)
    llm=_number(payload,"llm_usd_per_min",0,10)
    telecom=_number(payload,"telephony_usd_per_min",0,10)
    hosting=_number(payload,"hosting_usd_per_month",0,100000)
    fx=_number(payload,"fx_mnt_per_usd",1,1000000)
    minutes=round(calls*avg,2)
    beyond=max(0,minutes-plan["minutes"])
    ai=round(plan["usd"]+beyond*EXTRA_MINUTE_USD,4)
    llm_cost=round(minutes*llm,4)
    telecom_cost=round(minutes*telecom,4)
    total=round(ai+llm_cost+telecom_cost+hosting,4)
    mnt=math.ceil(total*fx)
    # Round upward so whole-tugrik pricing never falls below the fixed markup.
    revenue=(mnt*(100+MARKUP_PERCENT)+99)//100
    return {
        "plan":payload["plan"],"total_minutes":minutes,"included_minutes":plan["minutes"],
        "extra_minutes":round(beyond,2),"agent_usd":ai,"llm_usd":llm_cost,
        "telephony_usd":telecom_cost,"hosting_usd":hosting,
        "total_usd":total,"total_mnt":mnt,"sale_price_mnt":revenue,"markup_percent":MARKUP_PERCENT,
        "profit_mnt":revenue-mnt,
        "margin_percent":round((round(revenue)-mnt)/revenue*100,1) if revenue>0 else None,
        "illustrative":True,"taxes_included":False,
        "note":"Тооцоолол: 2026-10 ElevenAgents monthly list price + $0.08 нэмэлт минут. Provider LLM/телеком/hosting нь таны оруулсан таамаглал. Багцын дундын хэрэглээг бизнес тус бүрд хуваарилахгүй; burst, FX, татвар, үнэгүй web захиалга, credit cashback ороогүй.",
        "plan_options":[{"id":id,"monthly_usd":x["usd"],"minutes":x["minutes"],"concurrency":x["calls"]} for id,x in PLANS.items()]
    }

async def check_provider_agent(requested_id):
    if not isinstance(requested_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}",requested_id):
        raise HTTPException(422,"ElevenLabs Agent ID буруу байна.")
    key=os.getenv("ELEVENLABS_API_KEY","").strip()
    if not key:
        raise HTTPException(503,"ElevenLabs API key Railway-д тохируулаагүй байна.")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(18,connect=8),follow_redirects=False,trust_env=False) as client:
            resp=await client.get("https://api.elevenlabs.io/v1/convai/agents/"+requested_id,
                                  headers={"xi-api-key":key})
        if resp.status_code!=200:
            raise HTTPException(502,"Энэ ElevenLabs API эрх agent-д хандаж чадсангүй. Agent ID болон API key-н эрхийг шалгана уу.")
        data=resp.json()
        if not isinstance(data,dict) or data.get("agent_id")!=requested_id:
            raise HTTPException(502,"ElevenLabs agent ID-г баталгаажуулж чадсангүй.")
        conf=data.get("conversation_config") or {}
        agent=conf.get("agent") or {}
        phones=data.get("phone_numbers") or []
        return {"id":requested_id,"name":str(data.get("name") or "ElevenAgents AI")[:120],
                "language":str(agent.get("language") or "unknown")[:16],
                "phone_count":len(phones) if isinstance(phones,list) else 0}
    except HTTPException:raise
    except (httpx.HTTPError,ValueError,TypeError) as exc:
        raise HTTPException(502,"ElevenLabs-тай холбогдож чадсангүй. Эрх ба сүлжээг шалгаарай.") from exc

async def verify_agent(user_id,body):
    aid=body.get("agent_id") if isinstance(body,dict) else None
    if not isinstance(aid,str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}",aid):
        raise HTTPException(422,"Agent ID формат буруу байна.")
    result=await check_provider_agent(aid)
    if result["id"]!=aid:raise HTTPException(502,"Баталгаажуулсан agent ID тохирохгүй байна.")
    ensure_schema()
    with core.db() as db:
        db.execute("""INSERT INTO reception_agents(user_id,agent_id,agent_name,language,phone_count,checked_at)
                      VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                      agent_id=excluded.agent_id,agent_name=excluded.agent_name,
                      language=excluded.language,phone_count=excluded.phone_count,checked_at=excluded.checked_at""",
                   (user_id,aid,result["name"],result["language"],result["phone_count"],time.time()))
    return {"agent_id":aid,"agent_name":result["name"],"language":result["language"],
            "phone_count":result["phone_count"],"verified":True,
            "note":"API-гаар agent уншигдсан. Дуудлага амжилттай хүлээн авдаг эсэхийг тусад нь турших шаардлагатай."}

def register_routes(app,admin_user,mutation_guard,json_body,throttle,origin_provider):
    @app.get("/api/reception/launch")
    def readiness(request:Request):
        user=admin_user(request)
        return launch_status(user["user_id"],origin_provider())
    @app.post("/api/reception/launch/estimate")
    async def pricing(request:Request):
        user=admin_user(request);mutation_guard(request,user)
        throttle("reception-estimate:"+user["user_id"],120,3600)
        return estimate(await json_body(request))
    @app.post("/api/reception/launch/agent")
    async def register_agent(request:Request):
        user=admin_user(request);mutation_guard(request,user)
        throttle("reception-verify-agent:"+user["user_id"],5,3600)
        return await verify_agent(user["user_id"],await json_body(request))
