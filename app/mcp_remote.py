"""Account-scoped OAuth 2 + Streamable HTTP MCP for the independent RAINY Voice Studio.
Activate on a persistent-volume deployment using VOICE_MCP_ENABLED=true.
No RAVS credentials, accounts or wallet records are shared.
"""
import base64
import hashlib
import html
import json
import math
import os
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from . import core, billing, voice_direction
from .engine import ElevenLabsEngine

SCOPES={"voice:read","voice:generate","offline_access"}
KEY_RE=re.compile(r"^[A-Za-z0-9_-]{16,128}$")
PKCE_RE=re.compile(r"^[A-Za-z0-9_-]{43,128}$")
ORIGINS={"https://chatgpt.com","https://claude.ai"}
RATE={}

def active():
    return os.getenv("VOICE_MCP_ENABLED","false").lower() in {"1","true","yes","on"}

def origin():
    value=os.getenv("PUBLIC_ORIGIN","http://localhost:8080").rstrip("/")
    u=urlsplit(value)
    if not u.netloc or u.scheme not in {"https","http"} or u.path or u.query or u.fragment or (u.scheme=="http" and u.hostname not in {"localhost","127.0.0.1"}):
        raise RuntimeError("PUBLIC_ORIGIN must be an HTTPS origin in production")
    return value

def resource(): return origin()+"/mcp"
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def no_cache(body,status=200): return JSONResponse(body,status_code=status,headers={"Cache-Control":"no-store"})
def error(e,status=400): return no_cache({"error":e},status)
def ready():
    if not active(): raise HTTPException(404,"MCP disabled")

def redirects_ok(uri):
    if not isinstance(uri,str) or len(uri)>1024: return False
    u=urlsplit(uri)
    return bool(u.hostname and not u.username and not u.password and not u.fragment and
        (u.scheme=="https" or (u.scheme=="http" and u.hostname in {"localhost","127.0.0.1","::1"})))

def schema():
    with core.db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS vmcp_clients(id TEXT PRIMARY KEY,name TEXT NOT NULL,redirects TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS vmcp_consent(nonce TEXT PRIMARY KEY,client TEXT NOT NULL,uid TEXT NOT NULL,redirect TEXT NOT NULL,challenge TEXT NOT NULL,scope TEXT NOT NULL,state TEXT,expiry REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS vmcp_code(hash TEXT PRIMARY KEY,client TEXT NOT NULL,uid TEXT NOT NULL,redirect TEXT NOT NULL,challenge TEXT NOT NULL,scope TEXT NOT NULL,expiry REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS vmcp_tokens(access TEXT PRIMARY KEY,refresh TEXT UNIQUE,client TEXT NOT NULL,uid TEXT NOT NULL,scope TEXT NOT NULL,access_expiry REAL NOT NULL,refresh_expiry REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS vmcp_tts_requests(uid TEXT NOT NULL,request_key TEXT NOT NULL,payload_hash TEXT NOT NULL,job TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(uid,request_key));
        """)

def grant_scopes(value):
    parts=set((value or "voice:read").split())
    if "voice:read" not in parts or not parts<=SCOPES: raise ValueError("invalid_scope")
    return " ".join(sorted(parts))

def check_resource(value): return not value or value==resource()

def principal(request):
    value=request.headers.get("authorization","")
    if not value.startswith("Bearer ") or len(value)>600: return None
    with core.db() as c:
        row=c.execute("""SELECT t.uid,t.scope,u.email FROM vmcp_tokens t JOIN users u ON t.uid=u.id
            WHERE t.access=? AND t.revoked=0 AND t.access_expiry>?""",(digest(value[7:]),time.time())).fetchone()
    return row if row and "voice:read" in row["scope"].split() and not row["email"].endswith("@deleted.invalid") else None

def require_bearer():
    return no_cache({"error":"RAINY Voice OAuth зөвшөөрөл шаардлагатай."},401)

def result(data,failed=False):
    return {"content":[{"type":"text","text":json.dumps(data,ensure_ascii=False,default=str)}],"isError":failed}

def listed(writable):
    def tool(name,title,desc,props=None,required=None,write=False):
        return {"name":name,"title":title,"description":desc,
                "inputSchema":{"type":"object","properties":props or {},**({"required":required} if required else {})},
                "annotations":{"readOnlyHint":not write,"idempotentHint":True}}
    v={"voice_id":{"type":"string"},"text":{"type":"string","maxLength":12000},
       "model_id":{"type":"string","enum":["eleven_v4","eleven_v4_turbo"]}}
    tools=[
        tool("rainy_voice_voices","Монгол хоолой","Өөрийн болон үндсэн Монгол хоолойнууд"),
        tool("rainy_voice_wallet","Voice кредит","Зөвхөн Voice сайтад өөрийн кредит"),
        tool("rainy_voice_quote_tts","TTS үнэ","Бодит дуу үүсгэлгүйгээр кредит тооцох",v,["voice_id","text"]),
        tool("rainy_voice_job_status","Дууны төлөв","Өөрийн TTS ажлын төлөв",{"job_id":{"type":"string"}},["job_id"]),
        tool("rainy_voice_video_handoff","Video + Voice төлөвлөгөө","Хоёр тусдаа MCP ашиглах үнэгүй заавар",{"project":{"type":"string"}},["project"])
    ]
    if writable:
        tools.append(tool("rainy_voice_create_tts","Монгол дуу үүсгэх","Кредит зарцуулна. Quote хийж хэрэглэгчээс тусдаа зөвшөөрөл ав. Нэг ажлын retry-д ижил idempotencyKey ашигла.",
                          {**v,"title":{"type":"string","maxLength":100},"maxCredits":{"type":"integer","minimum":1},
                           "idempotencyKey":{"type":"string","minLength":16,"maxLength":128},"confirmGeneration":{"type":"boolean","const":True}},
                          ["voice_id","text","maxCredits","idempotencyKey","confirmGeneration"],True))
    return tools

async def tool_call(name,args,who,allowed_voice_ids,voice_multiplier):
    uid=who["uid"]
    if name=="rainy_voice_video_handoff":
        return {"project":str(args.get("project",""))[:1000],"videoMcp":"RAINY Video /mcp","voiceMcp":resource(),
            "steps":["RAVS ravs_content_brief + model guide: зохиол, кадр бүрийн prompt, voice-over текст",
                     "RAVS ravs_estimate ба Voice rainy_voice_quote_tts: кредитийг салгаж тооц",
                     "Хэрэглэгчээс тус тусын төлбөртэй хүсэлт бүрт зөвшөөрөл ав",
                     "Зөвшөөрсөн үед ravs_create_generation ба rainy_voice_create_tts-г тус тусад нь эхлүүл",
                     "ravs_generation_status болон rainy_voice_job_status-г шалга",
                     "Бэлэн видео ба аудиог тус тусад нь өг; MCP одоогоор автомат эвлүүлэг хийхгүй"]}
    if name=="rainy_voice_wallet":
        w=billing.wallet(uid)
        return {"balance":w["wallet"]["balance"],"plan":w["subscription"] and w["subscription"]["plan_id"]}
    if name=="rainy_voice_voices":
        with core.db() as c:
            own=[dict(row) for row in c.execute("SELECT id,name FROM voices WHERE user_id=?",(uid,))]
        return {"voices":[{"id":x["id"],"name":x["name"]} for x in ElevenLabsEngine.configured_voices()]+own}
    if name=="rainy_voice_job_status":
        job=str(args.get("job_id",""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",job): raise ValueError("job_id буруу байна")
        with core.db() as c:
            row=c.execute("SELECT * FROM jobs WHERE id=? AND user_id=?",(job,uid)).fetchone()
        if not row: raise ValueError("Таны ажил олдсонгүй")
        output=core.public_job(row)
        if row["status"]=="done":
            output["downloadUrl"]=f"{origin()}/api/jobs/{job}/mp3"
            output["note"]="Татахад Voice бүртгэлээр нэвтэрсэн байх шаардлагатай"
        return output
    if name not in {"rainy_voice_quote_tts","rainy_voice_create_tts"}: raise ValueError("Unknown tool")
    if name=="rainy_voice_create_tts" and "voice:generate" not in who["scope"].split(): raise ValueError("Үүсгэх OAuth эрх байхгүй")
    voice=str(args.get("voice_id",""))
    if voice not in allowed_voice_ids(uid): raise ValueError("Voice ID таны каталоги дахь хоолой биш")
    model=str(args.get("model_id") or "eleven_v4")
    if model not in {"eleven_v4","eleven_v4_turbo"}: raise ValueError("Дэмжигдэхгүй TTS модель")
    text=core.prepare_text(str(args.get("text","")))
    payload={"text":text,"speed":1,"emotion":"neutral","model_id":model}
    n=sum(len(segment) for segment in voice_direction.segments(payload))
    multiplier=await voice_multiplier(voice,uid)
    base=billing.estimate("tts",chars=n,model_id=model)
    credits=max(1,math.ceil(base*multiplier))
    if name=="rainy_voice_quote_tts":
        return {"credits":credits,"characters":n,"model_id":model,"voice_multiplier":multiplier}
    ceiling=args.get("maxCredits")
    key=args.get("idempotencyKey")
    if args.get("confirmGeneration") is not True or type(ceiling) is not int or ceiling<credits or ceiling>1000000:
        raise ValueError(f"Зөвшөөрсөн кредит хангалтгүй. Шаардлагатай {credits}")
    if not isinstance(key,str) or not KEY_RE.fullmatch(key): raise ValueError("idempotencyKey 16–128 тэмдэгт байна")
    title=str(args.get("title") or "RAINY MCP Voice")[:100]
    body_hash=digest(json.dumps([voice,text,model,title],ensure_ascii=False))
    job=core.uid()
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        old=c.execute("SELECT * FROM vmcp_tts_requests WHERE uid=? AND request_key=?",(uid,key)).fetchone()
        if old:
            if old["payload_hash"]!=body_hash: raise ValueError("Ижил idempotencyKey өөр хүсэлтэд ашигласан")
            job=old["job"]
        else:
            c.execute("INSERT INTO vmcp_tts_requests VALUES(?,?,?,?,?)",(uid,key,body_hash,job,time.time()))
    if old:
        with core.db() as c:
            row=c.execute("SELECT status FROM jobs WHERE id=? AND user_id=?",(job,uid)).fetchone()
        return {"id":job,"status":row["status"] if row else "pending_reconciliation","reused":True}
    try:
        ready,reason=ElevenLabsEngine().readiness()
        if not ready: raise ValueError(reason)
        paid=billing.enqueue_tts(uid,job,voice,title,payload,credits,{"characters":n,"voice_multiplier":multiplier,"model_id":model,"base_credits":base})
    except Exception:
        # Preserve the request key if the process crashed after a credit debit.
        raise ValueError(f"Төлөв тодорхойгүй. Шинэ хүсэлт бүү эхлүүл. Ажлын ID: {job}")
    return {"id":job,"status":"queued","credits_used":paid,"reused":False}

def register_routes(app,session,allowed_voice_ids,voice_multiplier):
    @app.on_event("startup")
    async def boot():
        if active(): schema()
    @app.get("/.well-known/oauth-protected-resource/mcp")
    def protected():
        if not active(): raise HTTPException(404)
        return {"resource":resource(),"authorization_servers":[origin()],"scopes_supported":sorted(SCOPES)}
    @app.get("/.well-known/oauth-authorization-server")
    @app.get("/.well-known/oauth-authorization-server/mcp")
    def metadata():
        if not active(): raise HTTPException(404)
        return {"issuer":origin(),"authorization_endpoint":origin()+"/oauth/authorize","token_endpoint":origin()+"/oauth/token",
            "registration_endpoint":origin()+"/oauth/register","response_types_supported":["code"],
            "grant_types_supported":["authorization_code","refresh_token"],"code_challenge_methods_supported":["S256"],
            "token_endpoint_auth_methods_supported":["none"],"scopes_supported":sorted(SCOPES)}
    @app.post("/oauth/register")
    async def register(request:Request):
        if not active(): raise HTTPException(404)
        if int(request.headers.get("content-length","0") or 0)>8192: return error("invalid_client_metadata")
        ip=request.client.host if request.client else "unknown"
        stamp,count=RATE.get(ip,(time.time(),0))
        if time.time()-stamp>3600: stamp,count=time.time(),0
        if count>=30: return error("rate_limited",429)
        RATE[ip]=(stamp,count+1)
        try: data=await request.json()
        except Exception: return error("invalid_client_metadata")
        if not isinstance(data,dict): return error("invalid_client_metadata")
        urls=data.get("redirect_uris")
        if not isinstance(urls,list) or not 1<=len(urls)<=5 or not all(redirects_ok(x) for x in urls) or data.get("token_endpoint_auth_method","none")!="none":
            return error("invalid_redirect_uri")
        cid=secrets.token_urlsafe(24)
        name=str(data.get("client_name") or "AI assistant")[:100]
        with core.db() as c:
            c.execute("INSERT INTO vmcp_clients VALUES(?,?,?,?)",(cid,name,json.dumps(urls),time.time()))
        return no_cache({"client_id":cid,"client_name":name,"redirect_uris":urls,"token_endpoint_auth_method":"none"},201)
    @app.get("/oauth/authorize")
    def consent(request:Request):
        if not active(): raise HTTPException(404)
        q=request.query_params
        cid,redirect=q.get("client_id",""),q.get("redirect_uri","")
        challenge=q.get("code_challenge","")
        if q.get("response_type")!="code" or q.get("code_challenge_method")!="S256" or not PKCE_RE.fullmatch(challenge) or not check_resource(q.get("resource")) or len(q.get("state",""))>1024:
            return error("invalid_request")
        try: scope=grant_scopes(q.get("scope"))
        except ValueError: return error("invalid_scope")
        with core.db() as c: client=c.execute("SELECT * FROM vmcp_clients WHERE id=?",(cid,)).fetchone()
        if not client or redirect not in json.loads(client["redirects"]): return error("invalid_client")
        user=session(request,False)
        if not user:
            # Browser SameSite=Strict excludes the session on a cross-site
            # OAuth redirect. A user-initiated same-origin continuation restores it.
            continue_url=html.escape(origin()+"/oauth/authorize?"+str(request.url.query),quote=True)
            return HTMLResponse(f"<h2>RAINY Voice — OAuth</h2><p>Voice Studio руу нэвтэрсэн бол доорх Continue холбоосоор энэ зөвшөөрлийг үргэлжлүүл.</p><p>Нэвтрээгүй бол <a href='/'>Voice Studio-д нэвтрэх</a>.</p><p><a href='{continue_url}'>OAuth зөвшөөрлийг үргэлжлүүлэх</a></p>",headers={"Cache-Control":"no-store"})
        nonce=secrets.token_urlsafe(32)
        with core.db() as c:
            c.execute("INSERT INTO vmcp_consent VALUES(?,?,?,?,?,?,?,?)",(nonce,cid,user["user_id"],redirect,challenge,scope,q.get("state",""),time.time()+600))
        return HTMLResponse(f"""<!doctype html><html lang='mn'><meta charset='utf-8'><title>RAINY Voice — OAuth</title>
        <body style='font-family:system-ui;max-width:540px;margin:10vh auto;padding:20px'>
        <h1>RAINY Voice Studio</h1><h2>{html.escape(client["name"])}</h2>
        <p>Бүртгэл: {html.escape(user["email"])}</p><p>Эрх: {html.escape(scope)}</p>
        <p>Төлбөртэй дуу үүсгэх бүрт тусдаа зөвшөөрөл шаардлагатай. RAVS Video тусдаа сайт, кредиттэй.</p>
        <form method='POST' action='/oauth/authorize'><input type='hidden' name='nonce' value='{nonce}'>
        <button name='decision' value='allow'>Зөвшөөрөх</button>
        <button name='decision' value='deny'>Татгалзах</button></form></body></html>""",headers={"Cache-Control":"no-store","X-Frame-Options":"DENY"})
    @app.post("/oauth/authorize")
    async def approve(request:Request):
        if not active(): raise HTTPException(404)
        user=session(request,False)
        if not user: return error("login_required",401)
        form=await request.form()
        nonce=str(form.get("nonce",""))
        if not 10<len(nonce)<200: return error("invalid_request")
        with core.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM vmcp_consent WHERE nonce=? AND uid=? AND expiry>?",(nonce,user["user_id"],time.time())).fetchone()
            c.execute("DELETE FROM vmcp_consent WHERE nonce=?",(nonce,))
            if not row: return error("invalid_request")
            if form.get("decision")=="allow":
                code=secrets.token_urlsafe(40)
                c.execute("INSERT INTO vmcp_code VALUES(?,?,?,?,?,?,?)",(digest(code),row["client"],row["uid"],row["redirect"],row["challenge"],row["scope"],time.time()+120))
                params={"code":code}
            else: params={"error":"access_denied"}
        if row["state"]: params["state"]=row["state"]
        return RedirectResponse(row["redirect"]+("&" if "?" in row["redirect"] else "?")+urlencode(params),status_code=303)
    @app.post("/oauth/token")
    async def token(request:Request):
        if not active(): raise HTTPException(404)
        form=await request.form()
        cid=str(form.get("client_id",""))
        if not check_resource(form.get("resource")): return error("invalid_target")
        now=time.time()
        grant=form.get("grant_type")
        if grant=="authorization_code":
            code=str(form.get("code",""));verifier=str(form.get("code_verifier",""))
            if not 20<len(code)<200 or not PKCE_RE.fullmatch(verifier): return error("invalid_grant")
            with core.db() as c:
                c.execute("BEGIN IMMEDIATE")
                row=c.execute("SELECT * FROM vmcp_code WHERE hash=?",(digest(code),)).fetchone()
                if not row or row["expiry"]<now or row["client"]!=cid or row["redirect"]!=form.get("redirect_uri"):
                    return error("invalid_grant")
                proof=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                if not secrets.compare_digest(proof,row["challenge"]): return error("invalid_grant")
                c.execute("DELETE FROM vmcp_code WHERE hash=?",(digest(code),))
                uid,scope=row["uid"],row["scope"]
        elif grant=="refresh_token":
            ref=str(form.get("refresh_token",""))
            with core.db() as c:
                c.execute("BEGIN IMMEDIATE")
                row=c.execute("SELECT * FROM vmcp_tokens WHERE refresh=? AND revoked=0",(digest(ref),)).fetchone()
                if not row or row["refresh_expiry"]<now or row["client"]!=cid: return error("invalid_grant")
                c.execute("UPDATE vmcp_tokens SET revoked=1 WHERE refresh=?",(digest(ref),))
                uid,scope=row["uid"],row["scope"]
        else: return error("unsupported_grant_type")
        access,refresh=secrets.token_urlsafe(40),secrets.token_urlsafe(40)
        with core.db() as c:
            c.execute("INSERT INTO vmcp_tokens VALUES(?,?,?,?,?,?,?,0)",(digest(access),digest(refresh),cid,uid,scope,now+3600,now+30*86400))
        return no_cache({"access_token":access,"token_type":"Bearer","expires_in":3600,"refresh_token":refresh,"scope":scope})
    @app.post("/mcp")
    async def mcp(request:Request):
        if not active(): raise HTTPException(404)
        src=request.headers.get("origin")
        if src and src not in ORIGINS|{origin()}: return error("invalid_origin",403)
        who=principal(request)
        if not who:
            return JSONResponse({"error":"OAuth required"},status_code=401,headers={"WWW-Authenticate":f'Bearer resource_metadata="{origin()}/.well-known/oauth-protected-resource/mcp"'})
        if int(request.headers.get("content-length","0") or 0)>128*1024: return error("too_large",413)
        try: payload=await request.json()
        except Exception: return error("invalid_json")
        if not isinstance(payload,dict) or payload.get("jsonrpc")!="2.0": return error("invalid_request")
        method=payload.get("method");rid=payload.get("id")
        if method=="notifications/initialized": return Response(status_code=202)
        def ok(v): return no_cache({"jsonrpc":"2.0","id":rid,"result":v})
        if method=="initialize":
            return ok({"protocolVersion":"2025-11-25","capabilities":{"tools":{"listChanged":False}},
                       "serverInfo":{"name":"RAINY Voice Studio","version":"1.0.0"},
                       "instructions":"Монгол хэлээр харьц. RAVS Video тусдаа MCP, сайт, кредиттэй. Quote хийж хэрэглэгчийн зөвшөөрөл авсны дараа л paid generation эхлүүл. Дуу done болоогүй байхад бэлэн гэж бүү хэл."})
        if method=="ping": return ok({})
        available=listed("voice:generate" in who["scope"].split())
        if method=="tools/list": return ok({"tools":available})
        if method!="tools/call": return no_cache({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"Method not found"}})
        prm=payload.get("params")
        if not isinstance(prm,dict) or not isinstance(prm.get("arguments",{}),dict): return ok(result({"error":"invalid arguments"},True))
        name=prm.get("name")
        if name not in {t["name"] for t in available}: return ok(result({"error":"Tool not allowed"},True))
        try: return ok(result(await tool_call(name,prm.get("arguments",{}),who,allowed_voice_ids,voice_multiplier)))
        except (ValueError,HTTPException) as exc:
            return ok(result({"error":exc.detail if isinstance(exc,HTTPException) else str(exc)},True))
        except Exception: return ok(result({"error":"Үйлчилгээнд алдаа гарлаа. Давхар төлбөртэй хүсэлт бүү үүсгэ."},True))
    @app.get("/mcp")
    @app.delete("/mcp")
    def mcp_get(request:Request):
        if not active(): raise HTTPException(404)
        if not principal(request): return require_bearer()
        return Response(status_code=405,headers={"Allow":"POST"})
    @app.get("/mcp/access")
    def connected_apps(request:Request):
        if not active(): raise HTTPException(404)
        user=session(request,False)
        if not user: return HTMLResponse("<h2>Voice Studio-д нэвтэрнэ үү.</h2><a href='/'>Нэвтрэх</a>",status_code=401)
        with core.db() as c:
            rows=c.execute("""SELECT t.client,c.name,COUNT(*) AS sessions FROM vmcp_tokens t
                JOIN vmcp_clients c ON c.id=t.client WHERE t.uid=? AND t.revoked=0
                AND t.refresh_expiry>? GROUP BY t.client,c.name""",(user["user_id"],time.time())).fetchall()
        forms="".join(
            "<form method='POST' action='/mcp/access'><input type='hidden' name='csrf' value='"+
            html.escape(user["csrf"],quote=True)+"'><input type='hidden' name='client_id' value='"+
            html.escape(row["client"],quote=True)+"'><b>"+html.escape(row["name"])+
            "</b> ("+str(row["sessions"])+") <button>Холболтыг цуцлах</button></form>"
            for row in rows
        )
        return HTMLResponse("<html lang='mn'><meta charset='utf-8'><h1>RAINY Voice — Зөвшөөрсөн аппууд</h1>"+
            (forms or "<p>Идэвхтэй холболт алга.</p>")+"</html>",headers={"Cache-Control":"no-store","X-Frame-Options":"DENY"})
    @app.post("/mcp/access")
    async def revoke_app(request:Request):
        if not active(): raise HTTPException(404)
        user=session(request,False)
        if not user: return error("login_required",401)
        form=await request.form()
        csrf=str(form.get("csrf",""))
        if not secrets.compare_digest(csrf,str(user["csrf"])): return error("csrf_failed",403)
        cid=str(form.get("client_id",""))
        if len(cid)>200: return error("invalid_client")
        with core.db() as c:
            c.execute("UPDATE vmcp_tokens SET revoked=1 WHERE uid=? AND client=?",
                      (user["user_id"],cid))
        return RedirectResponse("/mcp/access",status_code=303)
    @app.get("/mcp/connect")
    def connect():
        if not active(): raise HTTPException(404)
        return HTMLResponse(f"<h1>RAINY Voice × ChatGPT / Claude</h1><p>Remote MCP: <code>{html.escape(resource())}</code></p><p>OAuth-р зөвшөөрөөд RAVS Video MCP-г бас тусад нь нэмнэ. Кредит тусдаа.</p><a href='/mcp/access'>Холбогдсон аппуудын эрхийг цуцлах</a>")
