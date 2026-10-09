import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import billing, core, server, wire_payment


class BillingUnitTests(unittest.TestCase):
    def setUp(self):
        self.old_data=core.DATA
        self.temp=tempfile.TemporaryDirectory()
        core.DATA=Path(self.temp.name)
        core.init()
        with core.db() as db:
            db.execute("INSERT INTO users(id,email,password,created) VALUES(?,?,?,?)",("u","u@example.com","x",time.time()))

    def tearDown(self):
        core.DATA=self.old_data
        self.temp.cleanup()

    def test_admin_testing_does_not_grant_customer_credits(self):
        with patch.dict(os.environ,{'BILLING_ENABLED':'true','ADMIN_TEST_MODE':'true','ADMIN_EMAILS':'u@example.com'}):
            self.assertTrue(billing.admin_test_mode('u'))
            self.assertIsNone(billing.debit('u',99999,'music'))
            self.assertEqual(billing.wallet('u')['wallet']['balance'],0)
            with core.db() as db:db.execute("INSERT INTO users VALUES('other','other@example.com','x',1)")
            self.assertFalse(billing.admin_test_mode('other'))
            with self.assertRaises(ValueError):billing.debit('other',1,'music')
        with patch.dict(os.environ,{'ADMIN_TEST_MODE':'false','ADMIN_EMAILS':'u@example.com'}):
            self.assertFalse(billing.admin_test_mode('u'))

    def test_admin_durable_job_keeps_limits_without_credit_requirement(self):
        from app import durable_jobs
        with patch.dict(os.environ,{'BILLING_ENABLED':'true','ADMIN_TEST_MODE':'true','ADMIN_EMAILS':'u@example.com'}):
            for i in range(3):durable_jobs.enqueue('u','music','test',{'method':'music','args':[]},'x.mp3','audio/mpeg',10000)
            with self.assertRaises(ValueError):durable_jobs.enqueue('u','music','test',{'method':'music','args':[]},'x.mp3','audio/mpeg',10000)
            self.assertEqual(billing.wallet('u')['wallet']['balance'],0)
            with core.db() as db:self.assertEqual(db.execute('SELECT SUM(credits) FROM durable_jobs').fetchone()[0],0)

    def test_trial_debit_and_refund(self):
        with patch.dict(os.environ,{"BILLING_ENABLED":"true"},clear=False):
            wallet=billing.ensure_wallet("u")
            self.assertEqual(wallet["balance"],0)
            billing.grant("u",300,"test_grant")
            charge=billing.debit("u",100,"tts","job-1",{"characters":1000})
            self.assertEqual(billing.wallet("u")["wallet"]["balance"],200)
            self.assertTrue(billing.refund("u",charge))
            self.assertEqual(billing.wallet("u")["wallet"]["balance"],300)
            self.assertFalse(billing.refund("u",charge))

    def test_cost_estimates(self):
        self.assertEqual(billing.estimate("tts",chars=1000),80)
        self.assertEqual(billing.estimate("music",seconds=60),150)
        self.assertEqual(billing.estimate("speech_to_text",seconds=3600),220)
        self.assertEqual(billing.estimate("dubbing",seconds=60),2200)
        self.assertEqual(billing.estimate("sound_effects"),120)
        self.assertEqual(billing.estimate("realtime_stt",seconds=3600),390)

    def test_plan_credit_budget_preserves_markup_guard(self):
        with patch.dict(os.environ,{
            "BILLING_USD_MNT_RATE":"3700",
            "BILLING_TARGET_MARKUP":"2.0",
            "BILLING_PAYMENT_FEE_PERCENT":"3",
            "BILLING_OVERHEAD_RESERVE_PERCENT":"10",
            "BILLING_FX_BUFFER_PERCENT":"10",
            "ELEVENLABS_PROVIDER_PLAN":"pro",
            "BILLING_EXPECTED_ACTIVE_USERS":"100",
            "BILLING_FIXED_COST_PER_ACTIVE_USER_USD":"1.25",
        },clear=False):
            settings=billing.pricing_settings()
            self.assertEqual(settings["target_markup"],2.2)
            upstream_per_credit=billing.CREDIT_USD*settings["usd_mnt_rate"]*(1+settings["fx_buffer"])
            fixed=settings["fixed_cost_per_active_user_usd"]*settings["usd_mnt_rate"]*(1+settings["fx_buffer"])
            for plan in billing.plan_catalog():
                if plan["id"]=="trial":
                    continue
                usable=plan["price_mnt"]*(1-settings["payment_fee"])*(1-settings["overhead_reserve"])
                modeled_cost=fixed+plan["monthly_credits"]*upstream_per_credit
                self.assertGreaterEqual(usable,modeled_cost*settings["target_markup"])

            expected={"starter":3500,"creator":4300,"pro":6400,"studio":16000,"agency":40000}
            for plan_id,credits in expected.items():
                self.assertEqual(billing.get_plan(plan_id)["monthly_credits"],credits)

    def test_four_public_tiers_cover_single_user_launch_costs(self):
        with patch.dict(os.environ,{
            'ELEVENLABS_PROVIDER_PLAN':'starter', 'BILLING_EXPECTED_ACTIVE_USERS':'1',
            'BILLING_TARGET_MARKUP':'2.0',
        },clear=True):
            plans=[p for p in billing.public_plan_catalog() if p['id']!='trial']
            self.assertEqual([p['id'] for p in plans],['hobby','pro','studio','agency'])
            self.assertEqual([p['price_mnt'] for p in plans],[95000,155000,275000,575000])
            self.assertEqual([p['monthly_credits'] for p in plans],[1500,6400,16000,40000])
            settings=billing.pricing_settings()
            fixed=6*3700*1.1
            for plan in plans:
                self.assertGreater(plan['monthly_credits'],0)
                cost=fixed+plan['monthly_credits']*0.001*3700*1.1
                self.assertGreaterEqual(plan['price_mnt']*0.97*0.9,cost*2.2)

    def test_default_markup_is_2_2_and_metering_enabled(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(billing.pricing_settings()["target_markup"],2.2)
            self.assertTrue(billing.billing_enabled())
        with patch.dict(os.environ,{"BILLING_TARGET_MARKUP":"1.0"}):
            self.assertEqual(billing.pricing_settings()["target_markup"],2.2)

    def test_provider_plan_scales_with_active_users(self):
        self.assertEqual(billing.recommended_provider_plan(5),"starter")
        self.assertEqual(billing.recommended_provider_plan(20),"creator")
        self.assertEqual(billing.recommended_provider_plan(100),"pro")
        self.assertEqual(billing.recommended_provider_plan(300),"scale")
        self.assertEqual(billing.recommended_provider_plan(1000),"business")

    def test_every_paid_plan_covers_shared_fixed_cost_floor(self):
        minimum=billing.minimum_safe_plan_price_mnt()
        for plan in billing.plan_catalog():
            if plan["id"]=="trial":
                continue
            self.assertTrue(plan["profit_safe"])
            self.assertGreaterEqual(plan["price_mnt"],minimum)


    def test_subscription_payment_is_idempotent(self):
        billing.ensure_wallet("u")
        order=billing.create_order("u","starter","wire")
        first=billing.mark_order_paid(order["id"],"pi_1")
        second=billing.mark_order_paid(order["id"],"pi_1")
        self.assertEqual(first["status"],"paid")
        self.assertEqual(second["status"],"paid")
        data=billing.wallet("u")
        self.assertEqual(data["subscription"]["plan_id"],"starter")
        self.assertEqual(data["wallet"]["balance"],billing.get_plan("starter")["monthly_credits"])
        with core.db() as db:
            resets=db.execute("SELECT COUNT(*) FROM credit_ledger WHERE user_id='u' AND kind='subscription_reset'").fetchone()[0]
        self.assertEqual(resets,1)


class WireSignatureTests(unittest.TestCase):
    def test_signature_and_tolerance(self):
        secret="whsec_test_only"
        body=b'{"type":"endpoint.verification"}'
        now=int(time.time())
        digest=hmac.new(secret.encode(),f"{now}.".encode()+body,hashlib.sha256).hexdigest()
        signature=f"t={now},v1={digest}"
        with patch.dict(os.environ,{"WIRE_MN_WEBHOOK_SECRET":secret},clear=False):
            self.assertTrue(wire_payment.verify_webhook_signature(body,signature,now=now))
            self.assertFalse(wire_payment.verify_webhook_signature(body+b" ",signature,now=now))
            old=now-301
            old_digest=hmac.new(secret.encode(),f"{old}.".encode()+body,hashlib.sha256).hexdigest()
            self.assertFalse(wire_payment.verify_webhook_signature(body,f"t={old},v1={old_digest}",now=now))

    def test_operator_modes(self):
        with patch.dict(os.environ,{"WIRE_MN_API_KEY":"sk_test_mock","WIRE_MN_ALLOWED_OPERATORS":"sandbox"},clear=False):
            self.assertEqual(wire_payment.allowed_operators(),["sandbox"])
        with patch.dict(os.environ,{"WIRE_MN_API_KEY":"sk_live_mock","WIRE_MN_ALLOWED_OPERATORS":"sandbox,qpay"},clear=False):
            self.assertEqual(wire_payment.allowed_operators(),["qpay"])


class BillingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_data=core.DATA
        cls.temp=tempfile.TemporaryDirectory()
        core.DATA=Path(cls.temp.name)
        core.init()
        server.ORIGIN="http://testserver"
        cls.client=TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        core.DATA=cls.old_data
        cls.temp.cleanup()

    def setUp(self):
        self.client.cookies.clear()
        self.email=f"billing-{time.time_ns()}@example.com"
        with patch.dict(os.environ,{"ALLOW_REGISTRATION":"true","BILLING_ENABLED":"true"},clear=False):
            response=self.client.post(
                "/api/register",
                json={"email":self.email,"password":"strong-password-123"},
                headers={"Origin":"http://testserver"},
            )
        self.assertEqual(response.status_code,200,response.text)
        self.csrf=response.json()["user"]["csrf"]
        self.headers={"Origin":"http://testserver","X-CSRF-Token":self.csrf}

    def test_checkout_does_not_silently_change_displayed_price(self):
        with patch.object(server.wire_payment,'configured',return_value=True), patch.object(server.provider_cost,'refresh',new=AsyncMock(return_value=None)):
            response=self.client.post('/api/billing/wire/create',json={'plan_id':'pro','expected_amount_mnt':60000,'expected_credits':7000},headers=self.headers)
        self.assertEqual(response.status_code,409,response.text)

    def test_orders_are_owned_and_resume_the_original_quote(self):
        with core.db() as db:
            uid=db.execute('SELECT id FROM users WHERE email=?',(self.email,)).fetchone()[0]
            db.execute("INSERT INTO users VALUES('other-orders','other-orders@example.com','x',1) ON CONFLICT DO NOTHING")
            for order_id,owner,url in [('mine',uid,'https://pay.wire.mn/original'),('theirs','other-orders','https://pay.wire.mn/private')]:
                oid=order_id+uid
                db.execute("INSERT INTO billing_orders VALUES(?,?,?,?,'pending','wire',NULL,?,NULL)",(oid,owner,'hobby',12345,time.time()))
                db.execute('INSERT INTO billing_order_quotes VALUES(?,?)',(oid,777))
                db.execute("INSERT INTO wire_payments VALUES(?,NULL,NULL,?,'pending',?)",(oid,url,time.time()))
        response=self.client.get('/api/billing/orders')
        self.assertEqual(response.status_code,200)
        orders=response.json()['orders']
        self.assertEqual(len(orders),1)
        self.assertEqual(orders[0]['amount_mnt'],12345)
        self.assertEqual(orders[0]['credits'],777)
        self.assertEqual(orders[0]['pay_url'],'https://pay.wire.mn/original')
        self.assertNotIn('payment_intent_id',orders[0])
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/billing/orders').status_code,401)

    def test_orders_never_resume_unsafe_checkout_urls(self):
        with core.db() as db:
            uid=db.execute('SELECT id FROM users WHERE email=?',(self.email,)).fetchone()[0]
            db.execute("INSERT INTO billing_orders VALUES(?,?,?,?,'pending','wire',NULL,?,NULL)",(uid,uid,'hobby',20000,time.time()))
            db.execute("INSERT INTO wire_payments VALUES(?,NULL,NULL,?,'pending',?)",(uid,'https://pay.wire.mn.attacker.example/pay',time.time()))
        self.assertIsNone(self.client.get('/api/billing/orders').json()['orders'][0]['pay_url'])

    def test_checkout_url_validation(self):
        self.assertTrue(wire_payment.safe_checkout_url('https://pay.wire.mn/test?x=1'))
        for url in ['http://pay.wire.mn/x','https://pay.wire.mn.evil.example/x','https://evil@pay.wire.mn/x','https://pay.wire.mn:8443/x','javascript:alert(1)',None]:
            self.assertFalse(wire_payment.safe_checkout_url(url))

    def test_support_persists_owned_request_and_admin_reply(self):
        created=self.client.post('/api/support',json={'message':'Багцын зөвлөгөө авах хүсэлт байна.'},headers=self.headers)
        self.assertEqual(created.status_code,200,created.text)
        request_id=created.json()['id']
        self.assertEqual(self.client.get('/api/support').json()['requests'][0]['reply'],'')
        self.assertEqual(self.client.get('/api/admin/support').status_code,403)
        self.assertEqual(self.client.post('/api/admin/support/'+request_id,json={'reply':'test'},headers=self.headers).status_code,403)
        with patch.dict(os.environ,{'ADMIN_EMAILS':self.email}):
            self.assertEqual(self.client.get('/api/admin/support').status_code,200)
            response=self.client.post('/api/admin/support/'+request_id,json={'reply':'Танд тохирох багцыг санал болгоё.'},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/support').json()['requests'][0]['status'],'answered')
        self.assertEqual(self.client.post('/api/support',json={'message':'short'},headers=self.headers).status_code,422)
        self.assertEqual(self.client.post('/api/support',json={'message':'No csrf request'},headers={'Origin':'http://testserver'}).status_code,403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/support').status_code,401)

    def test_tts_voice_library_multiplier_is_billed(self):
        from app.engine import ElevenLabsEngine
        with core.db() as db:
            user=db.execute("SELECT id FROM users WHERE email=?",(self.email,)).fetchone()["id"]
            db.execute("DELETE FROM voice_rates")
        billing.grant(user,1000,"test_grant")
        voice=ElevenLabsEngine.default_voice_catalog[0]["id"]
        with patch.dict(os.environ,{"BILLING_ENABLED":"true"},clear=False), \
             patch("app.server.ElevenLabsEngine.readiness",return_value=(True,"ready")), \
             patch.object(server.tools,"find_shared_voice",new=AsyncMock(return_value={"voice_id":voice,"rate":2})):
            response=self.client.post(
                "/api/jobs",
                json={"text":("xxxx "*200).strip(),"voice_id":voice,"speed":1},
                headers=self.headers
            )
        self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(response.json()["credits_used"],160)
        with core.db() as db:
            rate=db.execute("SELECT multiplier FROM voice_rates WHERE source_id=?",(voice,)).fetchone()[0]
        self.assertEqual(rate,2)

    def test_queued_tts_delete_refunds_credits(self):
        from app.engine import ElevenLabsEngine
        with core.db() as db:
            user=db.execute("SELECT id FROM users WHERE email=?",(self.email,)).fetchone()["id"]
        billing.grant(user,1000,"test_grant")
        voice=ElevenLabsEngine.default_voice_catalog[0]["id"]
        with patch.dict(os.environ,{"BILLING_ENABLED":"true"},clear=False), \
             patch("app.server.ElevenLabsEngine.readiness",return_value=(True,"ready")), \
             patch.object(server.tools,"find_shared_voice",new=AsyncMock(return_value={"voice_id":voice,"rate":1})):
            created=self.client.post(
                "/api/jobs",
                json={"text":("xxxx "*200).strip(),"voice_id":voice,"speed":1},
                headers=self.headers
            )
        self.assertEqual(created.status_code,202,created.text)
        after_charge=created.json()["balance"]
        deleted=self.client.delete("/api/jobs/"+created.json()["id"],headers=self.headers)
        self.assertEqual(deleted.status_code,200,deleted.text)
        self.assertEqual(billing.wallet(user)["wallet"]["balance"],after_charge+80)

    def test_wire_checkout_then_status_activates_plan(self):
        intent={"id":"pi_test","status":"requires_payment_method","amount":60000,"currency":"MNT"}
        checkout={"id":"cs_test","url":"https://pay.wire.mn/test"}
        with patch.object(server.wire_payment,"configured",return_value=True), \
             patch.object(server.wire_payment,"create_payment_intent",new=AsyncMock(return_value=intent)), \
             patch.object(server.wire_payment,"create_checkout_session",new=AsyncMock(return_value=checkout)):
            created=self.client.post("/api/billing/wire/create",json={"plan_id":"starter"},headers=self.headers)
        self.assertEqual(created.status_code,200,created.text)
        data=created.json()
        self.assertEqual(data["amount_mnt"],60000)
        self.assertEqual(data["pay_url"],"https://pay.wire.mn/test")

        paid={"id":"pi_test","status":"succeeded","amount":60000,"currency":"MNT"}
        with patch.object(server.wire_payment,"retrieve_payment_intent",new=AsyncMock(return_value=paid)):
            status=self.client.get("/api/billing/wire/status/"+data["order_id"])
        self.assertEqual(status.status_code,200,status.text)
        self.assertEqual(status.json()["status"],"paid")
        self.assertEqual(status.json()["subscription"]["plan_id"],"starter")
        self.assertEqual(status.json()["wallet"]["balance"],billing.get_plan("starter")["monthly_credits"])

    def test_webhook_paid_once_and_rejects_bad_signature(self):
        with core.db() as db:
            user=db.execute("SELECT id FROM users WHERE email=?",(self.email,)).fetchone()["id"]
        billing.ensure_wallet(user)
        order=billing.create_order(user,"creator","wire")
        with core.db() as db:
            db.execute(
                "INSERT INTO wire_payments(order_id,payment_intent_id,checkout_session_id,checkout_url,status,updated) VALUES(?,?,?,?,?,?)",
                (order["id"],"pi_webhook",None,"https://pay.wire.mn/x","pending",time.time())
            )

        body=json.dumps({
            "id":"evt_1","type":"payment_intent.succeeded",
            "data":{"object":{"id":"pi_webhook","status":"succeeded"}}
        },separators=(",",":")).encode()
        secret="whsec_test_only"
        ts=int(time.time())
        digest=hmac.new(secret.encode(),f"{ts}.".encode()+body,hashlib.sha256).hexdigest()
        sig=f"t={ts},v1={digest}"

        bad=self.client.post("/api/billing/wire/webhook",content=body,headers={"WirePayment-Signature":"bad"})
        self.assertEqual(bad.status_code,401,bad.text)

        provider={"id":"pi_webhook","status":"succeeded","amount":69900,"currency":"MNT"}
        with patch.dict(os.environ,{"WIRE_MN_WEBHOOK_SECRET":secret},clear=False), \
             patch.object(server.wire_payment,"retrieve_payment_intent",new=AsyncMock(return_value=provider)):
            first=self.client.post("/api/billing/wire/webhook",content=body,headers={"WirePayment-Signature":sig})
            second=self.client.post("/api/billing/wire/webhook",content=body,headers={"WirePayment-Signature":sig})
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(second.status_code,200,second.text)

        with core.db() as db:
            resets=db.execute("SELECT COUNT(*) FROM credit_ledger WHERE user_id=? AND kind='subscription_reset'",(user,)).fetchone()[0]
            order_status=db.execute("SELECT status FROM billing_orders WHERE id=?",(order["id"],)).fetchone()[0]
        self.assertEqual(order_status,"paid")
        self.assertEqual(resets,1)
        self.assertEqual(billing.wallet(user)["wallet"]["balance"],billing.get_plan("creator")["monthly_credits"])

    def test_payment_amount_mismatch_is_not_activated(self):
        with core.db() as db:
            user=db.execute("SELECT id FROM users WHERE email=?",(self.email,)).fetchone()["id"]
        order=billing.create_order(user,"starter","wire")
        with core.db() as db:
            db.execute(
                "INSERT INTO wire_payments(order_id,payment_intent_id,checkout_session_id,checkout_url,status,updated) VALUES(?,?,?,?,?,?)",
                (order["id"],"pi_bad",None,None,"pending",time.time())
            )
        provider={"id":"pi_bad","status":"succeeded","amount":1,"currency":"MNT"}
        with patch.object(server.wire_payment,"retrieve_payment_intent",new=AsyncMock(return_value=provider)):
            response=self.client.get("/api/billing/wire/status/"+order["id"])
        self.assertEqual(response.status_code,409,response.text)
        with core.db() as db:
            status=db.execute("SELECT status FROM billing_orders WHERE id=?",(order["id"],)).fetchone()[0]
        self.assertEqual(status,"pending")


if __name__=="__main__":
    unittest.main()

