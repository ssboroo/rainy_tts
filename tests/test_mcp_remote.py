"""Remote MCP OAuth and TTS tools: provider-free security regression tests."""
import base64
import hashlib
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import core, mcp_remote


class RemoteMcpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_data = core.DATA
        core.DATA = Path(self.directory.name)
        self.env = patch.dict(os.environ, {
            "VOICE_MCP_ENABLED": "true",
            "PUBLIC_ORIGIN": "https://voice.example.com",
            "BILLING_ENABLED": "true",
            "BILLING_TRIAL_CREDITS": "0",
        })
        self.env.start()
        core.init()
        with core.db() as db:
            db.execute("INSERT INTO users(id,email,password,created) VALUES(?,?,?,?)",
                       ("voice-test-user", "test@example.com", core.hash_password("Long_Test_Password!"), 1))
        self.app = FastAPI()
        mcp_remote.register_routes(self.app, self.session, lambda uid: {"voice-test"}, self.multiplier)
        self.http = TestClient(self.app)
        self.http.__enter__()
        self.http.cookies.set("session", "test-session")

    def tearDown(self):
        self.http.__exit__(None,None,None)
        self.env.stop()
        core.DATA = self.original_data
        self.directory.cleanup()

    @staticmethod
    def session(request, required=False):
        if request.cookies.get("session") != "test-session": return None
        return {"user_id": "voice-test-user", "email": "test@example.com"}

    @staticmethod
    async def multiplier(voice, user): return 1

    def authorize(self):
        client=self.http.post("/oauth/register",json={
            "client_name": "Test Client",
            "redirect_uris": ["https://client.example/callback"],
        })
        self.assertEqual(client.status_code,201,client.text)
        cid=client.json()["client_id"]
        verifier="v"*48
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        query={"client_id":cid, "redirect_uri":"https://client.example/callback",
               "response_type":"code","scope":"voice:read voice:generate offline_access",
               "code_challenge":challenge,"code_challenge_method":"S256",
               "state":"retained-state","resource":"https://voice.example.com/mcp"}
        page=self.http.get("/oauth/authorize",params=query)
        self.assertEqual(page.status_code,200,page.text)
        nonce=re.search(r"name='nonce' value='([^']+)'",page.text).group(1)
        callback=self.http.post("/oauth/authorize",data={
            "nonce":nonce,"decision":"allow"
        },follow_redirects=False)
        self.assertEqual(callback.status_code,303,callback.text)
        params=parse_qs(urlsplit(callback.headers["location"]).query)
        self.assertEqual(params["state"],["retained-state"])
        auth_code=params["code"][0]
        token=self.http.post("/oauth/token",data={
            "grant_type":"authorization_code","client_id":cid,
            "redirect_uri":"https://client.example/callback",
            "code":auth_code,"code_verifier":verifier,
            "resource":"https://voice.example.com/mcp",
        })
        self.assertEqual(token.status_code,200,token.text)
        self.assertEqual(self.http.post("/oauth/token",data={
            "grant_type":"authorization_code","client_id":cid,
            "redirect_uri":"https://client.example/callback",
            "code":auth_code,"code_verifier":verifier,
        }).status_code,400)
        return cid,token.json()

    def rpc(self, token, method, params=None, identifier=1):
        return self.http.post("/mcp",headers={"Authorization":"Bearer "+token},
                              json={"jsonrpc":"2.0","id":identifier,"method":method,"params":params or {}})

    def test_discovery_and_redirect_guards(self):
        self.assertEqual(self.http.get("/.well-known/oauth-protected-resource/mcp").status_code,200)
        self.assertFalse(mcp_remote.redirects_ok("http://evil.example/callback"))
        self.assertFalse(mcp_remote.redirects_ok("https://example.org/#fragment"))
        self.assertTrue(mcp_remote.redirects_ok("https://chatgpt.com/callback"))
        self.assertEqual(self.http.post("/mcp",json={"jsonrpc":"2.0","id":1,"method":"tools/list"}).status_code,401)

    def test_pkce_refresh_and_idempotent_tts(self):
        cid,tokens=self.authorize()
        access=tokens["access_token"]
        self.assertEqual(self.rpc(access,"initialize").status_code,200)
        listed=self.rpc(access,"tools/list").json()["result"]["tools"]
        self.assertIn("rainy_voice_create_tts",{t["name"] for t in listed})
        quote=self.rpc(access,"tools/call",{"name":"rainy_voice_quote_tts","arguments":{
            "voice_id":"voice-test","text":"Сайн байна уу"}})
        self.assertEqual(quote.status_code,200)
        amount=__import__("json").loads(quote.json()["result"]["content"][0]["text"])["credits"]
        arguments={"voice_id":"voice-test","text":"Сайн байна уу","maxCredits":amount,
                   "idempotencyKey":"test-idempotency-2026","confirmGeneration":True}
        class DummyEngine:
            def readiness(self): return (True,"ready")
            @staticmethod
            def configured_voices(): return [{"id":"voice-test","name":"Test"}]
        def charge(user_id,job_id,voice_id,title,payload,credits,metadata):
            with core.db() as db:
                db.execute("INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)",
                           (job_id,user_id,voice_id,title,"{}", "queued",1))
            return credits
        with patch.object(mcp_remote,"ElevenLabsEngine",DummyEngine), patch.object(mcp_remote.billing,"enqueue_tts",charge):
            first=self.rpc(access,"tools/call",{"name":"rainy_voice_create_tts","arguments":arguments})
            self.assertIn('"queued"',first.json()["result"]["content"][0]["text"])
            again=self.rpc(access,"tools/call",{"name":"rainy_voice_create_tts","arguments":arguments})
            self.assertIn('"reused": true',again.json()["result"]["content"][0]["text"])
            with core.db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],1)
        changed={**arguments,"text":"Өөр текст"}
        bad=self.rpc(access,"tools/call",{"name":"rainy_voice_create_tts","arguments":changed})
        self.assertTrue(bad.json()["result"]["isError"])
        refresh=self.http.post("/oauth/token",data={"grant_type":"refresh_token",
                        "client_id":cid,"refresh_token":tokens["refresh_token"]})
        self.assertEqual(refresh.status_code,200,refresh.text)
        self.assertEqual(self.http.post("/oauth/token",data={"grant_type":"refresh_token",
                        "client_id":cid,"refresh_token":tokens["refresh_token"]}).status_code,400)
        self.assertEqual(self.rpc(access,"tools/list").status_code,401)


if __name__=="__main__":
    unittest.main()
