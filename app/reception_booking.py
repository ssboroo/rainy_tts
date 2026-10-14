"""RAINY Receptionist appointments: durable, tenant-scoped, race-safe Mongolian calendar.

Times are supplied as local Asia/Ulaanbaatar YYYY-MM-DD and HH:MM, stored as
UTC epoch seconds. One business-wide resource in MVP: overlapping appointments
across services are rejected transactionally. No phone/AI provider is invoked.
"""
from datetime import date as Date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import re
import sqlite3
import time

from fastapi import HTTPException, Request
from . import core

TZ=ZoneInfo("Asia/Ulaanbaatar")
DURATIONS={30,60,90,120}
OPEN_HOUR=9
CLOSE_HOUR=18
MAX_DAYS=90

def default_services(user_id):
    with core.db() as db:
        db.execute(
            "INSERT OR IGNORE INTO reception_services(id,user_id,name,duration_minutes,price_mnt,active,created) VALUES(?,?,?,?,?,?,?)",
            ("default-"+user_id,user_id,"Анхан шатны зөвлөгөө",30,0,1,time.time())
        )

def list_services(user_id):
    default_services(user_id)
    with core.db() as db:
        rows=db.execute(
            "SELECT id,name,duration_minutes,price_mnt FROM reception_services WHERE user_id=? AND active=1 ORDER BY created,id",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def create_service(user_id,payload):
    if not isinstance(payload,dict):
        raise HTTPException(422,"Үйлчилгээний мэдээлэл буруу байна.")
    name=payload.get("name")
    if not isinstance(name,str) or not 2<=len(name.strip())<=100:
        raise HTTPException(422,"Үйлчилгээний нэр 2–100 тэмдэгттэй байна.")
    duration=payload.get("duration_minutes")
    price=payload.get("price_mnt",0)
    if type(duration) is not int or duration not in DURATIONS or type(price) is not int or not 0<=price<=100000000:
        raise HTTPException(422,"Үргэлжлэх хугацаа 30, 60, 90, 120 минут; үнэ 0–100 сая төгрөг байна.")
    service={"id":core.uid(),"name":name.strip(),"duration_minutes":duration,"price_mnt":price}
    with core.db() as db:
        db.execute(
            "INSERT INTO reception_services(id,user_id,name,duration_minutes,price_mnt,active,created) VALUES(?,?,?,?,?,1,?)",
            (service["id"],user_id,service["name"],duration,price,time.time())
        )
    return service

def local_start(date_text,time_text):
    if not isinstance(date_text,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",date_text):
        raise HTTPException(422,"Өдөр YYYY-MM-DD хэлбэртэй байна.")
    if not isinstance(time_text,str) or not re.fullmatch(r"(?:0\d|1\d|2[0-3]):(?:00|30)",time_text):
        raise HTTPException(422,"Цаг HH:00 эсвэл HH:30 хэлбэртэй байна.")
    try:
        date=Date.fromisoformat(date_text)
        hh,mm=map(int,time_text.split(":"))
        day_diff=(date-datetime.now(TZ).date()).days
        if day_diff<0 or day_diff>MAX_DAYS:
            raise HTTPException(422,"Өнөөдрөөс хойш 90 хоногийн дотор цаг сонгоно уу.")
        return datetime(date.year,date.month,date.day,hh,mm,tzinfo=TZ)
    except ValueError:
        raise HTTPException(422,"Огноо эсвэл цаг буруу байна.")

def business_hours(db,user_id):
    try:
        row=db.execute("SELECT open_hour,close_hour,closed_weekdays FROM reception_business WHERE user_id=?",(user_id,)).fetchone()
    except sqlite3.OperationalError:
        row=None  # Existing tests without the optional receptionist profile schema
    if not row:return {"open_hour":9,"close_hour":18,"closed_weekdays":[6]}
    return {"open_hour":row["open_hour"],"close_hour":row["close_hour"],
            "closed_weekdays":json.loads(row["closed_weekdays"])}

def validate_slot(start,duration,hours=None):
    hours=hours or {"open_hour":OPEN_HOUR,"close_hour":CLOSE_HOUR,"closed_weekdays":[6]}
    if start <= datetime.now(TZ)+timedelta(minutes=1):
        raise HTTPException(422,"Өнгөрсөн эсвэл хэт ойрын цаг захиалах боломжгүй.")
    if start.weekday() in hours["closed_weekdays"]:
        raise HTTPException(422,"Тухайн өдөр байгууллага амарна.")
    opening=start.replace(hour=hours["open_hour"],minute=0)
    closing=start.replace(hour=hours["close_hour"],minute=0)
    if start<opening or start+timedelta(minutes=duration)>closing:
        raise HTTPException(422,"Байгууллагын ажиллах цагийн гадна байна.")

def get_service(db,user_id,service_id):
    if not isinstance(service_id,str) or len(service_id)>120:
        raise HTTPException(422,"Үйлчилгээ сонгоно уу.")
    service=db.execute(
        "SELECT id,name,duration_minutes,price_mnt FROM reception_services WHERE id=? AND user_id=? AND active=1",
        (service_id,user_id)
    ).fetchone()
    if not service:
        raise HTTPException(404,"Үйлчилгээ олдсонгүй.")
    return dict(service)

def availability(user_id,service_id,date_text):
    default_services(user_id)
    with core.db() as db:
        service=get_service(db,user_id,service_id)
        date_start=local_start(date_text,"09:00")
        hours=business_hours(db,user_id)
        slots=[]
        for minutes in range(hours["open_hour"]*60,hours["close_hour"]*60,30):
            start=date_start.replace(hour=minutes//60,minute=minutes%60)
            try:validate_slot(start,service["duration_minutes"],hours)
            except HTTPException:continue
            t=int(start.timestamp());end=t+service["duration_minutes"]*60
            exists=db.execute(
                "SELECT 1 FROM reception_appointments WHERE user_id=? AND status='booked' AND start_utc<? AND end_utc>? LIMIT 1",
                (user_id,end,t)
            ).fetchone()
            if not exists:slots.append(start.strftime("%H:%M"))
    return {"date":date_text,"service_id":service_id,"service_name":service["name"],"timezone":"Asia/Ulaanbaatar","slots":slots}

def book(user_id,payload):
    if not isinstance(payload,dict):
        raise HTTPException(422,"Захиалгын мэдээлэл буруу байна.")
    name=payload.get("caller_name")
    phone=payload.get("phone")
    request_id=payload.get("request_id")
    if not isinstance(name,str) or not 2<=len(name.strip())<=120:
        raise HTTPException(422,"Үйлчлүүлэгчийн нэр 2–120 тэмдэгттэй байна.")
    if not isinstance(phone,str) or not re.fullmatch(r"\+?[0-9][0-9 ()-]{6,19}",phone.strip()):
        raise HTTPException(422,"Утасны дугаар зөв оруулна уу.")
    if not isinstance(request_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}",request_id):
        raise HTTPException(422,"Давхар захиалгаас сэргийлэх request_id (8–100 үсэг/тоо) шаардлагатай.")
    service_id=payload.get("service_id")
    start=local_start(payload.get("date"),payload.get("time"))
    normalized={
        "service_id":service_id,
        "date":start.strftime("%Y-%m-%d"),
        "time":start.strftime("%H:%M"),
        "caller_name":name.strip(),
        "phone":phone.strip()
    }
    digest=hashlib.sha256(json.dumps(normalized,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    default_services(user_id)
    with core.db() as db:
        # BEGIN IMMEDIATE serializes writer transactions before overlap check.
        db.execute("BEGIN IMMEDIATE")
        previous=db.execute(
            "SELECT id,status,service_id,start_utc,end_utc,request_hash FROM reception_appointments WHERE user_id=? AND request_id=?",
            (user_id,request_id)
        ).fetchone()
        if previous:
            if previous["request_hash"]!=digest:
                raise HTTPException(409,"request_id өөр захиалгад аль хэдийн ашиглагдсан.")
            return public_appointment(previous)
        service=get_service(db,user_id,service_id)
        validate_slot(start,service["duration_minutes"],business_hours(db,user_id))
        start_utc=int(start.timestamp());end_utc=start_utc+service["duration_minutes"]*60
        conflicting=db.execute(
            "SELECT 1 FROM reception_appointments WHERE user_id=? AND status='booked' AND start_utc<? AND end_utc>? LIMIT 1",
            (user_id,end_utc,start_utc)
        ).fetchone()
        if conflicting:
            raise HTTPException(409,"Энэ цаг аль хэдийн захиалагдсан. Өөр сул цаг сонгоно уу.")
        appointment_id=core.uid()
        db.execute(
            "INSERT INTO reception_appointments(id,user_id,service_id,start_utc,end_utc,caller_name,phone,status,request_id,request_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (appointment_id,user_id,service_id,start_utc,end_utc,normalized["caller_name"],normalized["phone"],"booked",request_id,digest,time.time())
        )
        return {"id":appointment_id,"status":"booked","service_id":service_id,
                "date":normalized["date"],"time":normalized["time"],"timezone":"Asia/Ulaanbaatar"}

def public_appointment(row):
    start=datetime.fromtimestamp(row["start_utc"],TZ)
    return {"id":row["id"],"status":row["status"],"service_id":row["service_id"],
            "date":start.strftime("%Y-%m-%d"),"time":start.strftime("%H:%M"),"timezone":"Asia/Ulaanbaatar"}

def list_appointments(user_id,limit=100):
    with core.db() as db:
        rows=db.execute(
            "SELECT a.id,a.service_id,s.name AS service_name,a.caller_name,a.phone,a.start_utc,a.end_utc,a.status FROM reception_appointments a JOIN reception_services s ON s.id=a.service_id WHERE a.user_id=? ORDER BY a.start_utc DESC LIMIT ?",
            (user_id,limit)
        ).fetchall()
    return [{"id":r["id"],"service_id":r["service_id"],"service_name":r["service_name"],
             "caller_name":r["caller_name"],"phone":r["phone"],"status":r["status"],
             "date":datetime.fromtimestamp(r["start_utc"],TZ).strftime("%Y-%m-%d"),
             "time":datetime.fromtimestamp(r["start_utc"],TZ).strftime("%H:%M")}
            for r in rows]

def cancel(user_id,appointment_id):
    if not re.fullmatch(r"[0-9a-f]{32}",appointment_id):
        raise HTTPException(404,"Захиалга олдсонгүй.")
    with core.db() as db:
        changed=db.execute(
            "UPDATE reception_appointments SET status='cancelled' WHERE id=? AND user_id=? AND status='booked'",
            (appointment_id,user_id)
        ).rowcount
        if not changed:
            exists=db.execute("SELECT status FROM reception_appointments WHERE id=? AND user_id=?",(appointment_id,user_id)).fetchone()
            if not exists:raise HTTPException(404,"Захиалга олдсонгүй.")
        return {"id":appointment_id,"status":"cancelled"}

def register_routes(app,admin_user,mutation_guard,json_body,throttle):
    @app.get("/api/reception/services")
    def receptionist_services(request:Request):
        user=admin_user(request)
        return {"items":list_services(user["user_id"]),"timezone":"Asia/Ulaanbaatar"}
    @app.post("/api/reception/services")
    async def receptionist_add_service(request:Request):
        user=admin_user(request);mutation_guard(request,user)
        throttle("reception-add-service:"+user["user_id"],20,3600)
        return create_service(user["user_id"],await json_body(request))
    @app.get("/api/reception/availability")
    def receptionist_availability(request:Request,service_id:str,date:str):
        user=admin_user(request)
        return availability(user["user_id"],service_id,date)
    @app.post("/api/reception/appointments")
    async def receptionist_book(request:Request):
        user=admin_user(request);mutation_guard(request,user)
        throttle("reception-book:"+user["user_id"],60,3600)
        return book(user["user_id"],await json_body(request))
    @app.get("/api/reception/appointments")
    def receptionist_appointments(request:Request):
        user=admin_user(request)
        return {"items":list_appointments(user["user_id"])}
    @app.post("/api/reception/appointments/{appointment_id}/cancel")
    async def receptionist_cancel(appointment_id:str,request:Request):
        user=admin_user(request);mutation_guard(request,user)
        return cancel(user["user_id"],appointment_id)
