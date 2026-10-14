"""REAL permission and connector contract: fail before implementation."""
import os,time,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
from fastapi.testclient import TestClient
from app import core,server

class AgentsAndConnectors(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.old=core.DATA;cls.tmp=tempfile.TemporaryDirectory();core.DATA=Path(cls.tmp.name);core.init();cls.client=TestClient(server.app)
 @classmethod
 def tearDownClass(cls):
  cls.client.close();core.DATA=cls.old;cls.tmp.cleanup()
 def setUp(self):
  self.client.cookies.clear()
  with server.RATE_LOCK:server.RATE.clear()
  self.admin_mail="admin-"+str(time.time_ns())+"@example.org"
  self.member_mail="staff-"+str(time.time_ns())+"@example.org"
  self.env=patch.dict(os.environ,{"ALLOW_REGISTRATION":"true","ADMIN_EMAILS":"","ELEVENLABS_AGENT_ID":"","ELEVENLABS_API_KEY":"test-key","LIVE_AGENT_ADMIN_PREVIEW_ENABLED":"true","BILLING_ENABLED":"false","RECEPTION_CRM_SIGNING_KEY":"this-is-test-crm-secret-not-production-123456"})
  self.env.start();self.addCleanup(self.env.stop)
  server.ORIGIN="http://testserver"
  self.admin_headers=self.register(self.admin_mail)
  self.member_headers=self.register(self.member_mail)
  self.admin=patch.dict(os.environ,{"ADMIN_EMAILS":self.admin_mail})
  self.admin.start();self.addCleanup(self.admin.stop)
 def tearDown(self):
  with server.RATE_LOCK:server.RATE.clear()
 def register(self,email):
  response=self.client.post("/api/register",json={"email":email,"password":"good-password-123"},headers={"Origin":"http://testserver"})
  self.assertEqual(response.status_code,200,response.text)
  return {"Origin":"http://testserver","X-CSRF-Token":response.json()["user"]["csrf"]}
 def login(self,email):
  resp=self.client.post("/api/login",json={"email":email,"password":"good-password-123"},headers={"Origin":"http://testserver"})
  self.assertEqual(resp.status_code,200,resp.text)
  return {"Origin":"http://testserver","X-CSRF-Token":resp.json()["user"]["csrf"]}
 def add(self,agent_id,name):
  from app import reception_launch
  with patch.object(reception_launch,"check_provider_agent",new_callable=AsyncMock) as external:
   external.return_value={"id":agent_id,"name":name,"language":"mn","phone_count":0}
   return self.client.post("/api/reception/launch/agent",json={"agent_id":agent_id},headers=self.admin_headers)
 def test_ordinary_user_only_names_and_opaque_keys_not_provider_ids(self):
  self.login(self.admin_mail)
  a=self.add("agent_mongolA_1234","Монгол ресепшн")
  b=self.add("agent_mongolB_1234","Үйлчилгээний AI")
  self.assertEqual(a.status_code,200,a.text);self.assertEqual(b.status_code,200,b.text)
  catalogue=self.client.get("/api/reception/agents").json()["items"]
  self.assertEqual(len(catalogue),2)
  key_a,key_b=catalogue[0]["key"],catalogue[1]["key"]
  for key in (key_a,key_b):self.assertNotIn("agent_",key)
  for key in (key_a,key_b):
   r=self.client.post("/api/reception/agents/grant",json={"key":key,"email":self.member_mail},headers=self.admin_headers)
   self.assertEqual(r.status_code,200,r.text)
  self.login(self.member_mail)
  visible=self.client.get("/api/reception/agents")
  self.assertEqual(visible.status_code,200,visible.text)
  self.assertEqual({v["name"] for v in visible.json()["items"]},{"Монгол ресепшн","Үйлчилгээний AI"})
  self.assertNotIn("agent_mongol",visible.text)
  self.assertNotIn("agent_id",visible.text)
  select=self.client.post("/api/reception/agents/select",json={"key":key_b},headers=self.member_headers)
  self.assertEqual(select.status_code,200,select.text)
  self.assertEqual(select.json()["name"],"Үйлчилгээний AI")
  self.assertNotIn("agent_",select.text)
  status=self.client.get("/api/production/agent-status")
  self.assertEqual(status.status_code,200,status.text)
  self.assertEqual(status.json()["name"],"Үйлчилгээний AI")
  self.assertNotIn("agent_id",status.text)
  self.assertEqual(self.client.get("/api/reception/launch").status_code,403)
  self.assertEqual(self.client.post("/api/reception/launch/agent",json={"agent_id":"agent_zzzzzzzz123"},headers=self.member_headers).status_code,403)
  with patch("app.voice_agent_preview.httpx.AsyncClient") as mocked:
   client=mocked.return_value.__aenter__.return_value
   client.get=AsyncMock(return_value=type("R",(),{"status_code":200,"json":lambda self:{"signed_url":"wss://api.elevenlabs.io/v1/convai/conversation?token=fake"}})())
   signed=self.client.post("/api/production/agent-session",json={},headers=self.member_headers)
   self.assertEqual(signed.status_code,200,signed.text)
   self.assertEqual(client.get.await_args.kwargs["params"]["agent_id"],"agent_mongolB_1234")
 def test_never_allow_selecting_or_using_ungranted_agent(self):
  self.login(self.admin_mail)
  self.add("agent_allowedabc123","Ажилтан")
  key=self.client.get("/api/reception/agents").json()["items"][0]["key"]
  self.login(self.member_mail)
  self.assertEqual(self.client.post("/api/reception/agents/select",json={"key":key},headers=self.member_headers).status_code,403)
  self.assertFalse(self.client.get("/api/production/agent-status").json()["enabled"])
  self.assertEqual(self.client.post("/api/production/agent-session",json={},headers=self.member_headers).status_code,403)
 def test_phone_sync_uses_real_provider_assignment_and_verified_state(self):
  self.login(self.admin_mail)
  self.add("agent_sipacc0000123","Холбогдсон AI")
  from app import reception_connectors
  async def fake(method,path,body=None):
   if method=="GET":return [{"phone_number_id":"phnum_4321","phone_number":"+97677112233","provider":"sip_trunk","assigned_agent":{"agent_id":"agent_sipacc0000123"}}]
   raise AssertionError("unexpected provider request")
  with patch.object(reception_connectors,"eleven_request",side_effect=fake):
   r=self.client.post("/api/reception/telephony/sync",json={},headers=self.admin_headers)
  self.assertEqual(r.status_code,200,r.text)
  self.assertTrue(r.json()["verified"])
  self.assertEqual(r.json()["phone_number"],"+97677112233")
  self.assertNotIn("agent_sipacc",r.text)
  self.assertEqual(self.client.get("/api/reception/telephony/status").status_code,200)
 def test_twilio_import_does_not_log_or_return_secret_and_patches_assignment(self):
  self.login(self.admin_mail)
  self.add("agent_twilioabc1234","Салон")
  from app import reception_connectors
  calls=[]
  async def fake(method,path,body=None):
   calls.append((method,path,body))
   if method=="POST":return {"phone_number_id":"phnum_test123"}
   if method=="PATCH":return {"phone_number_id":"phnum_test123","assigned_agent":{"agent_id":"agent_twilioabc1234"}}
   if method=="GET":return {"phone_number_id":"phnum_test123","phone_number":"+14155550100","provider":"twilio","assigned_agent":{"agent_id":"agent_twilioabc1234"}}
  with patch.object(reception_connectors,"eleven_request",side_effect=fake):
   response=self.client.post("/api/reception/telephony/twilio",json={"phone_number":"+14155550100","sid":"AC"+"a"*32,"token":"sensitive_twilio_token","label":"Main"},headers=self.admin_headers)
  self.assertEqual(response.status_code,200,response.text)
  self.assertTrue(response.json()["verified"])
  self.assertNotIn("sensitive_twilio_token",response.text)
  self.assertEqual(calls[0][2]["provider"],"twilio")
  self.assertEqual(calls[1][0],"PATCH")
 def test_crm_real_signed_queue_and_failure_retry(self):
  self.login(self.admin_mail)
  from app import reception_connectors
  with patch.object(reception_connectors,"verify_crm_endpoint",new_callable=AsyncMock) as check:
   check.return_value=True
   configured=self.client.post("/api/reception/crm",json={"url":"https://crm.example.org/hooks/appointments","enabled":True},headers=self.admin_headers)
  self.assertEqual(configured.status_code,200,configured.text)
  self.assertNotIn("RECEPTION_CRM_SIGNING_KEY",configured.text)
  from app import reception_booking
  from datetime import datetime,timedelta
  from zoneinfo import ZoneInfo
  day=datetime.now(ZoneInfo("Asia/Ulaanbaatar")).date()+timedelta(days=3)
  while day.weekday()==6:day+=timedelta(days=1)
  service=self.client.get("/api/reception/services").json()["items"][0]["id"]
  booked=self.client.post("/api/reception/appointments",json={"service_id":service,"date":day.isoformat(),"time":"15:00","caller_name":"Бат","phone":"99112233","request_id":"crm-event-retry-001"},headers=self.admin_headers)
  self.assertEqual(booked.status_code,200,booked.text)
  events=self.client.get("/api/reception/crm/events")
  self.assertEqual(events.status_code,200,events.text)
  self.assertEqual(events.json()["items"][0]["status"],"pending")
  sent=[]
  async def deliver(url,payload,signature,key):
   sent.append((url,payload,signature,key));return True
  with patch.object(reception_connectors,"send_crm_event",side_effect=deliver):
   pushed=self.client.post("/api/reception/crm/flush",json={},headers=self.admin_headers)
  self.assertEqual(pushed.status_code,200,pushed.text)
  self.assertEqual(pushed.json()["delivered"],1)
  self.assertTrue(sent[0][2].startswith("sha256="))
  self.assertEqual(sent[0][1]["type"],"appointment.booked")
  self.assertEqual(self.client.get("/api/reception/crm/events").json()["items"][0]["status"],"sent")
 def test_crm_ssrf_and_user_isolation(self):
  self.login(self.admin_mail)
  bad=["http://example.com/x","https://127.0.0.1/test","https://localhost/hook","https://user:pw@example.com/hook","https://169.254.169.254/hook"]
  for url in bad:
   response=self.client.post("/api/reception/crm",json={"url":url,"enabled":True},headers=self.admin_headers)
   self.assertEqual(response.status_code,422,(url,response.text))
  self.login(self.member_mail)
  self.assertEqual(self.client.get("/api/reception/crm").status_code,403)
  self.assertEqual(self.client.get("/api/reception/telephony/status").status_code,403)
