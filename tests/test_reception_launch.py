"""Reception launch console: honest provider readiness and price math."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
from fastapi.testclient import TestClient
from app import core,server

class LaunchTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.old=core.DATA
  cls.tmp=tempfile.TemporaryDirectory()
  core.DATA=Path(cls.tmp.name);core.init();cls.client=TestClient(server.app)
 @classmethod
 def tearDownClass(cls):
  cls.client.close();core.DATA=cls.old;cls.tmp.cleanup()
 def setUp(self):
  self.client.cookies.clear()
  with server.RATE_LOCK:server.RATE.clear()
  self.mail="launch-"+str(time.time_ns())+"@example.org"
  self.env=patch.dict(os.environ,{"ALLOW_REGISTRATION":"true","BILLING_ENABLED":"false","ADMIN_EMAILS":"","LIVE_AGENT_ADMIN_PREVIEW_ENABLED":"false","ELEVENLABS_AGENT_ID":""})
  self.env.start();self.addCleanup(self.env.stop)
  server.ORIGIN="http://testserver"
  created=self.client.post("/api/register",json={"email":self.mail,"password":"good-password-123"},headers={"Origin":"http://testserver"})
  self.assertEqual(created.status_code,200,created.text)
  self.headers={"Origin":"http://testserver","X-CSRF-Token":created.json()["user"]["csrf"]}
  self.admin=patch.dict(os.environ,{"ADMIN_EMAILS":self.mail})
  self.admin.start();self.addCleanup(self.admin.stop)
 def tearDown(self):
  with server.RATE_LOCK:server.RATE.clear()
 def test_status_never_claims_telephone_or_voice_ready_from_tts_key(self):
  status=self.client.get("/api/reception/launch")
  self.assertEqual(status.status_code,200,status.text)
  d=status.json()
  self.assertFalse(d["steps"]["business"]["ready"])
  self.assertFalse(d["steps"]["services"]["ready"])
  self.assertFalse(d["steps"]["voice_agent"]["ready"])
  self.assertFalse(d["steps"]["telephony"]["ready"])
  self.assertFalse(d["steps"]["booking_link"]["ready"])
  self.assertTrue(d["mode"] in ("setup","partial","ready"))
  self.assertNotIn("ELEVENLABS_API_KEY",str(d))
  self.assertNotIn("private_key",str(d))
  with patch.dict(os.environ,{"ADMIN_EMAILS":"nobody@example.org"}):
   self.assertEqual(self.client.get("/api/reception/launch").status_code,403)
 def test_price_math_uses_included_minutes_and_real_extras(self):
  payload={"plan":"starter","calls":100,"avg_minutes":3,"llm_usd_per_min":0.015,
           "telephony_usd_per_min":0.02,"hosting_usd_per_month":5,
           "fx_mnt_per_usd":3500,"revenue_mnt_per_month":199000}
  r=self.client.post("/api/reception/launch/estimate",json=payload,headers=self.headers)
  self.assertEqual(r.status_code,200,r.text)
  d=r.json()
  self.assertEqual(d["total_minutes"],300)
  self.assertEqual(d["included_minutes"],75)
  self.assertEqual(d["extra_minutes"],225)
  self.assertAlmostEqual(d["agent_usd"],6+225*0.08,places=4)
  self.assertAlmostEqual(d["llm_usd"],300*0.015,places=4)
  self.assertAlmostEqual(d["telephony_usd"],300*0.02,places=4)
  self.assertAlmostEqual(d["total_usd"],6+225*0.08+4.5+6+5,places=4)
  self.assertEqual(d["total_mnt"],round(d["total_usd"]*3500))
  self.assertEqual(d["profit_mnt"],199000-d["total_mnt"])
  self.assertTrue(d["illustrative"])
 def test_cost_invalid_and_unknown_plan_fail_closed(self):
  p={"plan":"unknown","calls":10,"avg_minutes":2,"llm_usd_per_min":0,
     "telephony_usd_per_min":0,"hosting_usd_per_month":0,"fx_mnt_per_usd":3500,
     "revenue_mnt_per_month":0}
  self.assertEqual(self.client.post("/api/reception/launch/estimate",json=p,headers=self.headers).status_code,422)
  p["plan"]="creator"
  for patch_value in [{"calls":-1},{"calls":99999999},{"fx_mnt_per_usd":0},{"avg_minutes":0},{"llm_usd_per_min":-1}]:
   r=self.client.post("/api/reception/launch/estimate",json={**p,**patch_value},headers=self.headers)
   self.assertIn(r.status_code,(400,422),r.text)
 def test_nonfinite_direct_pricing_is_rejected_before_cost_math(self):
  from fastapi import HTTPException
  from app.reception_launch import estimate
  template={"plan":"starter","calls":2,"avg_minutes":3,
            "llm_usd_per_min":0,"telephony_usd_per_min":0,
            "hosting_usd_per_month":0,"fx_mnt_per_usd":3500,
            "revenue_mnt_per_month":100000}
  for impossible in (float("inf"),float("nan"),-float("inf")):
   with self.assertRaises(HTTPException) as ex:
    estimate({**template,"telephony_usd_per_min":impossible})
   self.assertEqual(ex.exception.status_code,422)
 def test_agent_verify_permission_and_provider_errors_do_not_save(self):
  from app import reception_launch
  with patch.object(reception_launch,"check_provider_agent",new_callable=AsyncMock) as mock:
   mock.return_value={"id":"agent_abcdef12345","name":"Монгол AI","language":"mn","phone_count":0}
   verified=self.client.post("/api/reception/launch/agent",json={"agent_id":"agent_abcdef12345"},headers=self.headers)
  self.assertEqual(verified.status_code,200,verified.text)
  self.assertEqual(verified.json()["agent_name"],"Монгол AI")
  s=self.client.get("/api/reception/launch").json()
  self.assertEqual(s["agent_name"],"Монгол AI")
  self.assertFalse(s["steps"]["voice_agent"]["ready"]) # preview disabled, even if linked
  self.assertFalse(s["steps"]["telephony"]["ready"])  # no carrier phone
  with patch.dict(os.environ,{"ADMIN_EMAILS":"elsewhere@example.org"}):
   denied=self.client.post("/api/reception/launch/agent",json={"agent_id":"agent_abcdef12345"},headers=self.headers)
  self.assertEqual(denied.status_code,403)
 def test_web_asset_and_setup_guide_exist(self):
  for item in ("reception-launch.js","reception-launch.css"):
   result=self.client.get("/"+item)
   self.assertEqual(result.status_code,200,item+" "+result.text[:100])
