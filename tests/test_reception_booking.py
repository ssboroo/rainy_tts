"""End-to-end receptionist calendar contract tests (no ElevenLabs charges)."""
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import core, server

TZ=ZoneInfo("Asia/Ulaanbaatar")

def next_workday():
    day=datetime.now(TZ).date()+timedelta(days=3)
    while day.weekday()==6:day+=timedelta(days=1)
    return day.isoformat()

class ReceptionBookingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_data=core.DATA
        cls.tmp=tempfile.TemporaryDirectory()
        core.DATA=Path(cls.tmp.name)
        core.init()
        cls.client=TestClient(server.app)
    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        core.DATA=cls.old_data
        cls.tmp.cleanup()
    def setUp(self):
        self.client.cookies.clear()
        self.email="reception-"+str(time.time_ns())+"@example.com"
        self.env=patch.dict(os.environ,{"ALLOW_REGISTRATION":"true","BILLING_ENABLED":"false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        server.ORIGIN="http://testserver"
        # Admin emails cannot be registered publicly; elevate ONLY after signup.
        with server.RATE_LOCK:server.RATE.clear()
        signup=self.client.post("/api/register",json={"email":self.email,"password":"strong-password-123"},headers={"Origin":"http://testserver"})
        self.assertEqual(signup.status_code,200,signup.text)
        self.headers={"Origin":"http://testserver","X-CSRF-Token":signup.json()["user"]["csrf"]}
        self.admin=patch.dict(os.environ,{"ADMIN_EMAILS":self.email})
        self.admin.start()
        self.addCleanup(self.admin.stop)
    def tearDown(self):
        # Avoid exhausting the shared registration limiter in existing tests.
        with server.RATE_LOCK:server.RATE.clear()
    def service(self):
        services=self.client.get("/api/reception/services")
        self.assertEqual(services.status_code,200,services.text)
        self.assertTrue(services.json()["items"])
        return services.json()["items"][0]
    def request(self,service_id=None,request_id="caller-unique-0001"):
        return {"service_id":service_id or self.service()["id"],"date":next_workday(),"time":"15:00",
                "caller_name":"Бат","phone":"99112233","request_id":request_id}
    def test_services_and_real_calendar_slots_are_scoped_to_admin(self):
        service=self.service()
        self.assertIn("duration_minutes",service)
        self.assertGreater(service["duration_minutes"],0)
        available=self.client.get("/api/reception/availability",params={"service_id":service["id"],"date":next_workday()})
        self.assertEqual(available.status_code,200,available.text)
        self.assertIn("15:00",available.json()["slots"])
        with patch.dict(os.environ,{"ADMIN_EMAILS":"other@example.com"}):
            denied=self.client.get("/api/reception/services")
        self.assertEqual(denied.status_code,403)
    def test_booking_conflicts_and_idempotent_retries(self):
        payload=self.request()
        first=self.client.post("/api/reception/appointments",json=payload,headers=self.headers)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()["status"],"booked")
        repeat=self.client.post("/api/reception/appointments",json=payload,headers=self.headers)
        self.assertEqual(repeat.status_code,200,repeat.text)
        self.assertEqual(repeat.json()["id"],first.json()["id"])
        reused={**payload,"time":"16:00"}
        conflict_key=self.client.post("/api/reception/appointments",json=reused,headers=self.headers)
        self.assertEqual(conflict_key.status_code,409,conflict_key.text)
        competing=self.client.post("/api/reception/appointments",json={**payload,"request_id":"caller-unique-0002"},headers=self.headers)
        self.assertEqual(competing.status_code,409,competing.text)
        slots=self.client.get("/api/reception/availability",params={"service_id":payload["service_id"],"date":payload["date"]}).json()["slots"]
        self.assertNotIn("15:00",slots)
        self.assertIn("16:00",slots)
        listed=self.client.get("/api/reception/appointments")
        self.assertEqual(listed.status_code,200,listed.text)
        self.assertTrue(any(a["id"]==first.json()["id"] for a in listed.json()["items"]))
    def test_webhook_can_check_slots_and_book_exactly_once_without_session(self):
        payload=self.request()
        config=self.client.get("/api/reception/config").json()
        tools={item["name"]:item["url"] for item in config["tools"]}
        self.assertIn("check_availability",tools)
        self.assertIn("book_appointment",tools)
        from urllib.parse import urlsplit
        path=lambda name:urlsplit(tools[name]).path
        # discard admin session: webhooks must use bearer-in-path token instead
        self.client.cookies.clear()
        availability=self.client.post(path("check_availability"),json={"date":payload["date"],"service_id":payload["service_id"]})
        self.assertEqual(availability.status_code,200,availability.text)
        self.assertIn("15:00",availability.json()["slots"])
        created=self.client.post(path("book_appointment"),json=payload)
        self.assertEqual(created.status_code,200,created.text)
        self.assertEqual(created.json()["status"],"booked")
        same=self.client.post(path("book_appointment"),json=payload)
        self.assertEqual(same.status_code,200,same.text)
        self.assertEqual(same.json()["id"],created.json()["id"])
        invalid=self.client.post(path("book_appointment").replace("book_appointment","book_appointment")+"bad",json=payload)
        self.assertEqual(invalid.status_code,404)
        with core.db() as db:
            user=db.execute("SELECT id FROM users WHERE email=?",(self.email,)).fetchone()["id"]
            count=db.execute("SELECT COUNT(*) FROM reception_appointments WHERE user_id=?",(user,)).fetchone()[0]
        self.assertEqual(count,1)
    def test_invalid_date_after_hours_and_bad_phone_are_rejected(self):
        payload=self.request()
        for override in ({"time":"23:30"},{"date":"2024-01-01"},{"phone":"not a phone"},{"caller_name":""},{"request_id":""}):
            response=self.client.post("/api/reception/appointments",json={**payload,**override},headers=self.headers)
            self.assertEqual(response.status_code,422,response.text)
    def test_cancelled_slot_can_be_rebooked_but_other_user_cannot_read_it(self):
        payload=self.request()
        created=self.client.post("/api/reception/appointments",json=payload,headers=self.headers)
        self.assertEqual(created.status_code,200,created.text)
        appointment_id=created.json()["id"]
        cancel=self.client.post("/api/reception/appointments/"+appointment_id+"/cancel",json={},headers=self.headers)
        self.assertEqual(cancel.status_code,200,cancel.text)
        self.assertEqual(cancel.json()["status"],"cancelled")
        again=self.client.post("/api/reception/appointments",json={**payload,"request_id":"another-unique-id"},headers=self.headers)
        self.assertEqual(again.status_code,200,again.text)
        with patch.dict(os.environ,{"ADMIN_EMAILS":"other@example.com"}):
            denied=self.client.get("/api/reception/appointments")
        self.assertEqual(denied.status_code,403)
