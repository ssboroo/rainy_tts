"""Wire.mn hosted payment integration for RAINY subscriptions."""
import hashlib
import hmac
import json
import os
import time

import httpx

API_BASE=(os.getenv("WIRE_MN_API_URL","https://api.wire.mn/v1") or "https://api.wire.mn/v1").rstrip("/")

class WireError(RuntimeError):
    def __init__(self,message,status=502,code=None,request_id=None):
        super().__init__(message)
        self.status=int(status)
        self.code=code
        self.request_id=request_id

def api_key():
    value=(os.getenv("WIRE_MN_API_KEY","") or "").strip()
    if not value or value=="your_wire_mn_api_key":
        raise WireError("WIRE_MN_API_KEY тохируулаагүй байна.",503,"not_configured")
    return value

def configured():
    try:
        api_key()
        return True
    except WireError:
        return False

def allowed_operators():
    key=api_key()
    live=key.startswith("sk_live_")
    ops=[x.strip() for x in (os.getenv("WIRE_MN_ALLOWED_OPERATORS","") or "").split(",") if x.strip()]
    if live:
        live_ops=[x for x in ops if x!="sandbox"]
        return live_ops or None
    if any(x!="sandbox" for x in ops):
        raise WireError("Test key ашиглах үед WIRE_MN_ALLOWED_OPERATORS=sandbox байна.",503,"operator_configuration")
    return ops or ["sandbox"]

def idem(scope,value):
    return f"{scope}-{value}"

def _friendly_error(action,response):
    code=request_id=provider_message=None
    try:
        body=response.json()
        error=body.get("error") or body.get("detail") or {}
        if isinstance(error,dict):
            code=error.get("code")
            request_id=error.get("request_id")
            provider_message=error.get("message")
        elif isinstance(error,str):
            provider_message=error
    except Exception:
        pass
    messages={
        "operator_unknown":"Wire операторын ID буруу байна. Live үед идэвхтэй operator ID ашиглах эсвэл WIRE_MN_ALLOWED_OPERATORS-ийг хоосон үлдээнэ үү.",
        "connector_required":"Wire → Суваг хэсэгт төлбөрийн оператороо холбоно уу.",
        "settlement_account_required":"Wire → Данс хэсэгт орлого хүлээн авах дансаа сонгоно уу.",
        "dan_verification_required":"Wire бүртгэлийн ДАН баталгаажуулалтыг дуусгана уу.",
        "operator_not_allowed":"Wire API key-ийн test/live горим болон operator тохиргоо зөрж байна.",
        "idempotency_in_flight":"Нэхэмжлэл боловсруулагдаж байна. 1–2 секундын дараа дахин оролдоно уу.",
        "payment_intent_unexpected_state":"Нэхэмжлэлийн төлөв өөрчлөгдсөн. Дахин шалгана уу.",
    }
    message=messages.get(code)
    if not message and response.status_code==401:
        message="Wire API key хүчингүй байна."
    if not message and isinstance(provider_message,str) and 0<len(provider_message)<=500:
        message=provider_message
    if not message:
        message=f"{action} үед Wire.mn алдаа гарлаа (HTTP {response.status_code})."
    return WireError(message,response.status_code,code,request_id)

async def _request(method,path,*,headers=None,json_body=None,form=None,timeout=15):
    request_headers={"Authorization":f"Bearer {api_key()}"}
    if headers:
        request_headers.update(headers)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=10),follow_redirects=True) as client:
        response=await client.request(
            method,API_BASE+path,headers=request_headers,
            json=json_body if form is None else None,
            content=form if form is not None else None,
        )
    if response.status_code>=400:
        raise _friendly_error(path,response)
    return response

async def create_payment_intent(order_id,amount_mnt,description=""):
    amount=int(amount_mnt)
    if amount<=0:
        raise ValueError("Төлбөрийн дүн буруу байна.")
    body={"amount":amount,"currency":"MNT","description":description[:500] or None}
    ops=allowed_operators()
    if ops is not None:
        body["allowed_operators"]=ops
    response=await _request(
        "POST","/payment_intents",
        headers={"Content-Type":"application/json","Idempotency-Key":idem("pi",order_id)},
        json_body=body
    )
    return response.json()

async def create_checkout_session(payment_intent_id,order_id,success_url=None):
    payload={"payment_intent":payment_intent_id}
    if success_url:
        payload["success_url"]=success_url
    from urllib.parse import urlencode
    encoded=urlencode(payload)
    headers={
        "Content-Type":"application/x-www-form-urlencoded",
        "Idempotency-Key":idem("cs",payment_intent_id),
    }
    try:
        response=await _request("POST","/checkout/sessions",headers=headers,form=encoded)
        return response.json()
    except WireError as exc:
        # Some Wire deployments have required JSON for this endpoint.
        # Retry only a 400 request-body format rejection.
        if exc.status!=400:
            raise
    response=await _request(
        "POST","/checkout/sessions",
        headers={"Content-Type":"application/json","Idempotency-Key":idem("cs",payment_intent_id)},
        json_body=payload
    )
    return response.json()

async def retrieve_payment_intent(payment_intent_id):
    response=await _request("GET",f"/payment_intents/{payment_intent_id}")
    return response.json()

def map_status(status):
    value=str(status or "").lower()
    if value in {"succeeded","paid"}:
        return "paid"
    if value in {"failed","canceled","cancelled"}:
        return "failed"
    if value=="expired":
        return "expired"
    return "pending"

def verify_webhook_signature(raw_body,signature,now=None):
    secret=(os.getenv("WIRE_MN_WEBHOOK_SECRET","") or "").strip()
    if not secret or secret=="whsec_replace_with_your_endpoint_signing_secret":
        return False
    parts=[part.strip() for part in str(signature or "").split(",") if part.strip()]
    timestamps=[p[2:] for p in parts if p.startswith("t=")]
    if len(timestamps)!=1 or not timestamps[0].isdigit():
        return False
    ts=int(timestamps[0])
    current=time.time() if now is None else float(now)
    if abs(current-ts)>300:
        return False
    payload=f"{ts}.".encode()+raw_body
    expected=hmac.new(secret.encode(),payload,hashlib.sha256).hexdigest()
    for part in parts:
        if not part.startswith("v1="):
            continue
        candidate=part[3:]
        if len(candidate)==64 and hmac.compare_digest(expected.lower(),candidate.lower()):
            return True
    return False

def success_url(order_id):
    origin=(os.getenv("PUBLIC_ORIGIN","") or "").strip().rstrip("/")
    if not origin or not origin.startswith(("http://localhost","http://127.0.0.1","https://")):
        return None
    return f"{origin}/?payment=success&order={order_id}"
