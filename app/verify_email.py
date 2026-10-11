"""Account email verification: scoped one-time tokens and branded transactional SMTP."""
import asyncio
import hashlib
import logging
import os
import re
import secrets
import smtplib
import time
from email.message import EmailMessage
from html import escape
from urllib.parse import quote
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from . import core, accounts

TTL = 86400
GENERIC = {"ok": True, "message": "Бүртгэл баталгаажуулах шаардлагатай имэйл бол захидал илгээгдэнэ."}

def enabled():
    return os.getenv("EMAIL_VERIFICATION_REQUIRED", "false").strip().lower() in ("true", "1", "yes")

def configured():
    return accounts.email_configured() and os.getenv("SMTP_PASSWORD", "") != ""

def ensure_schema():
    with core.db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS account_email_verifications (
          user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL UNIQUE,
          expires REAL NOT NULL,
          verified REAL
        );
        CREATE INDEX IF NOT EXISTS verification_expiry ON account_email_verifications(expires);
        """)

def new_token(c, user_id):
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    c.execute(
        "INSERT INTO account_email_verifications(user_id,token_hash,expires,verified) "
        "VALUES(?,?,?,NULL) ON CONFLICT(user_id) DO UPDATE SET token_hash=excluded.token_hash, "
        "expires=excluded.expires WHERE account_email_verifications.verified IS NULL",
        (user_id, hashed, time.time() + TTL)
    )
    return raw

def is_unverified(c, user_id):
    row = c.execute("SELECT verified FROM account_email_verifications WHERE user_id=?", (user_id,)).fetchone()
    return row is not None and row["verified"] is None

def send_verification(email, raw):
    origin = os.getenv("PUBLIC_EMAIL_ORIGIN", os.getenv("PUBLIC_ORIGIN", "https://voice.rainy.studio")).rstrip("/")
    if not origin.startswith("https://") or not origin.endswith(("voice.rainy.studio", "rainytts-production.up.railway.app")):
        raise ValueError("Untrusted verification origin")
    link = origin + "/?verify_token=" + quote(raw, safe="")
    message = EmailMessage()
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = email
    message["Subject"] = "Имэйл хаягаа баталгаажуулна уу · RAINY Voice Studio"
    message.set_content(f"RAINY Voice Studio\n\nИмэйл хаягаа баталгаажуулна уу.\nХолбоос (24 цаг хүчинтэй):\n{link}\n\nХэрэв та бүртгэл үүсгээгүй бол энэ захидлыг үл тооно уу.")
    url = escape(link, quote=True)
    message.add_alternative(
        '<html lang="mn"><body style="margin:0;background:#08100d;padding:40px 16px;font-family:Arial,sans-serif;color:#f6fff9">'
        '<table role="presentation" align="center" width="100%" style="max-width:560px;border-radius:20px;background:#16231e;border:1px solid #315345">'
        '<tr><td style="padding:40px 32px"><p style="font-size:15px;letter-spacing:2px;color:#98efbd">RAINY VOICE STUDIO</p>'
        '<h1 style="font-size:30px;color:#fff">Имэйлээ баталгаажуулна уу</h1>'
        '<p style="line-height:1.7;color:#d2e1d7">Таны бүтээлч дуу хоолойн студи бэлэн болох гэж байна.</p>'
        '<p><a href="' + url + '" style="background:#8affc1;color:#102015;text-decoration:none;padding:17px 24px;border-radius:10px;display:inline-block;font-weight:700">Имэйлээ баталгаажуулах →</a></p>'
        '<p style="font-size:12px;word-break:break-all;color:#b8cfc0">' + url + '</p>'
        '<p style="font-size:13px;color:#c0d0c5">Холбоос 24 цаг хүчинтэй. Энэ хүсэлтийг гаргаагүй бол үл тооно уу.</p></td></tr>'
        '</table></body></html>', subtype="html"
    )
    tls = os.getenv("SMTP_TLS", "true").lower()
    transport = smtplib.SMTP_SSL if tls == "ssl" else smtplib.SMTP
    with transport(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "465" if tls == "ssl" else "587")), timeout=15) as smtp:
        if tls in ("true", "1", "yes", "starttls"):
            smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)

def register_routes(app, mutation_guard, throttle):
    app.router.add_event_handler("startup", ensure_schema)

    @app.post("/api/account/verify-email")
    async def verify(request: Request):
        mutation_guard(request)
        throttle("verify-email:" + request.client.host, 12, 3600)
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "Хүсэлт буруу.")
        raw = data.get("token", "") if isinstance(data, dict) else ""
        if not isinstance(raw, str) or len(raw) > 180 or len(raw) < 32:
            raise HTTPException(400, "Баталгаажуулах холбоос буруу.")
        hashed = hashlib.sha256(raw.encode()).hexdigest()
        with core.db() as c:
            row = c.execute("SELECT user_id FROM account_email_verifications WHERE token_hash=? AND verified IS NULL AND expires>?",(hashed,time.time())).fetchone()
            if not row:
                raise HTTPException(400, "Баталгаажуулах холбоос хүчингүй эсвэл хугацаа дууссан.")
            c.execute("UPDATE account_email_verifications SET verified=? WHERE user_id=? AND token_hash=? AND verified IS NULL", (time.time(),row["user_id"],hashed))
        return {"ok": True, "message": "Имэйл баталгаажлаа. Одоо нэвтэрнэ үү."}

    @app.post("/api/account/resend-verification")
    async def resend(request: Request):
        mutation_guard(request)
        throttle("resend-email:" + request.client.host, 5, 3600)
        if not configured():
            raise HTTPException(503, "Имэйл үйлчилгээ түр боломжгүй.")
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "Имэйл буруу.")
        email = str(data.get("email", "")).strip().lower()[:254] if isinstance(data,dict) else ""
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise HTTPException(400, "Имэйл буруу.")
        with core.db() as c:
            row = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            token = new_token(c,row["id"]) if row and is_unverified(c,row["id"]) else None
        if token:
            try:
                await asyncio.to_thread(send_verification, email, token)
            except Exception:
                logging.warning("Verification email SMTP delivery failed")
        return JSONResponse(GENERIC)
