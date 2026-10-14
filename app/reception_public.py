"""Opt-in public self-service booking with existing atomic tenant calendar.

This does not initiate phone calls or incur AI minutes. Only business contact,
services and free slots are public; customer/appointment lists stay admin-only.
"""
import re
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from . import core, reception_booking, reception_knowledge

def ensure_schema():
    with core.db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS reception_public_links (
          user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          token TEXT UNIQUE NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 0,
          created REAL NOT NULL
        )""")

def link_status(user_id,origin):
    ensure_schema()
    with core.db() as db:
        row=db.execute("SELECT token,enabled FROM reception_public_links WHERE user_id=?",(user_id,)).fetchone()
    return {"enabled":bool(row["enabled"]) if row else False,
            "token":row["token"] if row and row["enabled"] else None,
            "url":origin+"/appointment?key="+row["token"] if row and row["enabled"] else None}

def set_link(user_id,payload,origin):
    if not isinstance(payload,dict) or type(payload.get("enabled")) is not bool:
        raise HTTPException(422,"enabled нь true/false утгатай байх ёстой.")
    ensure_schema()
    with core.db() as db:
        row=db.execute("SELECT token FROM reception_public_links WHERE user_id=?",(user_id,)).fetchone()
        if not row:
            db.execute("INSERT INTO reception_public_links(user_id,token,enabled,created) VALUES(?,?,?,?)",
                       (user_id,secrets.token_urlsafe(27),int(payload["enabled"]),time.time()))
        else:
            db.execute("UPDATE reception_public_links SET enabled=? WHERE user_id=?",
                       (int(payload["enabled"]),user_id))
    return link_status(user_id,origin)

def owner_for_link(token):
    if not isinstance(token,str) or not re.fullmatch(r"[A-Za-z0-9_-]{30,70}",token):
        raise HTTPException(404,"Захиалгын холбоос олдсонгүй.")
    ensure_schema()
    with core.db() as db:
        row=db.execute("SELECT user_id FROM reception_public_links WHERE token=? AND enabled=1",(token,)).fetchone()
    if not row:raise HTTPException(404,"Захиалгын холбоос олдсонгүй.")
    return row["user_id"]

def register_routes(app,admin_user,mutation_guard,json_body,throttle,static_dir,origin_provider):
    @app.get("/appointment")
    def reception_public_page():
        return FileResponse(static_dir/"appointment.html",media_type="text/html")

    @app.get("/api/reception/public-link")
    def reception_link_get(request:Request):
        return link_status(admin_user(request)["user_id"],origin_provider())

    @app.post("/api/reception/public-link")
    async def reception_link_set(request:Request):
        user=admin_user(request);mutation_guard(request,user)
        throttle("reception-public-link:"+user["user_id"],10,3600)
        return set_link(user["user_id"],await json_body(request),origin_provider())

    @app.get("/api/public/reception/{token}")
    def reception_public_details(token:str):
        owner=owner_for_link(token)
        business=reception_knowledge.read_business(owner)
        return {"business":business,"services":reception_booking.list_services(owner),"timezone":"Asia/Ulaanbaatar"}

    @app.get("/api/public/reception/{token}/availability")
    def reception_public_slots(token:str,service_id:str,date:str):
        owner=owner_for_link(token)
        return reception_booking.availability(owner,service_id,date)

    @app.post("/api/public/reception/{token}/book")
    async def reception_public_book(token:str,request:Request):
        owner=owner_for_link(token)
        # A public link is intended for guests; protect from bulk junk bookings.
        mutation_guard(request)
        addr=request.client.host if request.client else "unknown"
        throttle("reception-public-user:"+owner,50,3600)
        throttle("reception-public-ip:"+owner+":"+addr,12,3600)
        payload=await json_body(request)
        if payload.get("confirmed") is not True:
            raise HTTPException(422,"Үйлчлүүлэгчийн зөвшөөрөл, нэр, утсыг баталгаажуулна уу.")
        return reception_booking.book(owner,payload)
