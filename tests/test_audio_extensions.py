import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import core, billing
from app.audio_extensions import register_routes, subtitle_exports

class AudioExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.temp.name); core.init()
        with core.db() as db:
            for uid in ('u','other'):
                db.execute('INSERT INTO users(id,email,password,created) VALUES(?,?,?,?)',(uid,uid+'@test.com','hash',0))
            db.execute('INSERT INTO voices VALUES(?,?,?,?,?)',('owned','u','Owned','',0))
        self.provider=MagicMock(); self.provider._request=AsyncMock(return_value=MagicMock())
        self.provider._request.return_value.json.return_value={'previews':[{'generated_voice_id':'preview','audio_base_64':base64.b64encode(b'ID3audio').decode()}]}
        self.charge=MagicMock(return_value='charge'); self.artifacts={}
        def artifact(user,job,kind,name,mime,data):
            aid=core.uid(); self.artifacts[aid]=(user,job,name,data); return aid
        def guard(req,sess):
            if req.headers.get('x-csrf')=='bad': raise HTTPException(403,'CSRF')
        app=FastAPI(); register_routes(app,lambda req:{'user_id':req.headers.get('x-user','u')},guard,lambda *a:None,self.provider,lambda u:{'owned'},self.charge,artifact,artifact)
        self.client=TestClient(app); self.billing=patch.object(billing,'billing_enabled',return_value=False); self.billing.start(); self.durable=patch.dict(os.environ,{'DURABLE_TOOLS_ENABLED':'false'}); self.durable.start()
    def tearDown(self):
        self.client.close(); self.billing.stop(); self.durable.stop(); core.DATA=self.old; self.temp.cleanup()
    def preview(self):
        return self.client.post('/api/tools/voice-design',json={'prompt':'A warm expressive adult voice','text':'Сайн байна уу. '*10})
    def test_design_contract_and_conservative_charge(self):
        response=self.preview(); self.assertEqual(response.status_code,200,response.text)
        result=response.json(); self.assertEqual(result['previews'][0]['generated_voice_id'],'preview')
        self.assertIn(result['previews'][0]['artifact_id'],self.artifacts)
        self.assertEqual(self.provider._request.call_args.args,('POST','/v1/text-to-voice/design'))
        self.assertGreaterEqual(self.charge.call_args.args[1],billing.estimate('voice_clone'))
    def test_preview_save_ownership_and_forgery(self):
        result=self.preview().json(); payload={'job_id':result['job_id'],'generated_voice_id':'preview','name':'Миний хоолой'}
        before=self.provider._request.call_count
        self.assertEqual(self.client.post('/api/tools/voice-design/save',headers={'x-user':'other'},json=payload).status_code,404)
        self.assertEqual(self.client.post('/api/tools/voice-design/save',json={**payload,'generated_voice_id':'alien'}).status_code,422)
        self.assertEqual(self.provider._request.call_count,before)
        self.provider._request.return_value.json.return_value={'voice_id':'saved','name':'Миний хоолой'}
        response=self.client.post('/api/tools/voice-design/save',json=payload); self.assertEqual(response.status_code,200,response.text)
        before=self.provider._request.call_count
        self.assertEqual(self.client.post('/api/tools/voice-design/save',json=payload).json()['voice']['id'],'saved')
        self.assertEqual(self.provider._request.call_count,before)
    def test_alien_remix_rejected_before_provider(self):
        response=self.client.post('/api/tools/voice-remix',json={'voice_id':'alien','prompt':'Warmer voice','text':'a'*100})
        self.assertEqual(response.status_code,404); self.provider._request.assert_not_called()
    def test_input_and_csrf_validation(self):
        self.assertEqual(self.client.post('/api/tools/voice-design',json={'prompt':'short','text':'a'*100}).status_code,422)
        self.assertEqual(self.client.post('/api/tools/voice-design',json={'prompt':'p'*20,'text':'a'*1001}).status_code,422)
        self.assertEqual(self.client.post('/api/tools/voice-design',headers={'x-csrf':'bad'},json={}).status_code,403)
        self.provider._request.assert_not_called()
    def test_failure_refunds_once_and_marks_failed(self):
        self.provider._request.side_effect=RuntimeError('failure')
        with patch.object(billing,'refund') as refund:
            self.assertEqual(self.preview().status_code,502); refund.assert_called_once_with('u','charge','provider_failed')
        with core.db() as db:self.assertEqual(db.execute('SELECT status FROM tool_jobs').fetchone()[0],'failed')
    def test_alignment_invalid_media(self):
        response=self.client.post('/api/tools/alignment',data={'text':'Сайн'},files={'file':('fake.wav',b'not audio','audio/wav')})
        self.assertEqual(response.status_code,422,response.text); self.provider._request.assert_not_called()
    def test_alignment_exports(self):
        with patch('app.audio_extensions.validate_media',return_value=2):
            self.provider._request.return_value.json.return_value={'words':[{'text':'Сайн','start':0,'end':1},{'text':'байна','start':1,'end':2}]}
            response=self.client.post('/api/tools/alignment',data={'text':'Сайн байна'},files={'file':('audio.wav',b'audio','audio/wav')})
        self.assertEqual(response.status_code,200,response.text); self.assertEqual(set(response.json()['artifacts']),{'txt','json','srt','vtt'})
        self.assertEqual(self.provider._request.call_args.args,('POST','/v1/forced-alignment'))
    def test_subtitle_timing(self):
        srt,vtt=subtitle_exports([{'text':'Сайн','start':1.234,'end':2.345}])
        self.assertIn('00:00:01,234 --> 00:00:02,345',srt); self.assertIn('00:00:01.234 --> 00:00:02.345',vtt)

    def test_owned_remix_contract(self):
        response=self.client.post('/api/tools/voice-remix',json={'voice_id':'owned','prompt':'Warmer voice','text':'a'*100})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.provider._request.call_args.args,('POST','/v1/text-to-voice/owned/remix'))
    def test_plan_slots_enforced_before_save(self):
        result=self.preview().json()
        with patch.object(billing,'billing_enabled',return_value=True), patch.object(billing,'wallet',return_value={'subscription':{'status':'active','plan_id':'starter'}}):
            before=self.provider._request.call_count
            response=self.client.post('/api/tools/voice-design/save',json={'job_id':result['job_id'],'generated_voice_id':'preview','name':'New'})
        self.assertEqual(response.status_code,409,response.text); self.assertEqual(self.provider._request.call_count,before)
    def test_ambiguous_timeout_does_not_refund(self):
        import httpx
        self.provider._request.side_effect=httpx.ReadTimeout('ambiguous')
        with patch.object(billing,'refund') as refund:
            self.assertEqual(self.preview().status_code,502); refund.assert_not_called()
    def test_invalid_json_rejected(self):
        response=self.client.post('/api/tools/voice-design',content='{',headers={'content-type':'application/json'})
        self.assertEqual(response.status_code,422)
    def test_alignment_duration_cap(self):
        from app.audio_extensions import validate_media
        import asyncio
        from starlette.datastructures import UploadFile
        import io
        probe=MagicMock(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'audio'}],'format':{'duration':3601}}))
        with patch('app.audio_extensions.subprocess.run',return_value=probe):
            with self.assertRaises(HTTPException): asyncio.run(validate_media(UploadFile(io.BytesIO(b'audio'),filename='test.wav')))
    def test_alignment_upload_cap(self):
        from app.audio_extensions import validate_media
        import asyncio
        from starlette.datastructures import UploadFile
        import io
        with patch('app.audio_extensions.MAX_UPLOAD_BYTES',2):
            with self.assertRaises(HTTPException) as caught: asyncio.run(validate_media(UploadFile(io.BytesIO(b'audio'),filename='test.wav')))
        self.assertEqual(caught.exception.status_code,413)

    def test_short_remix_description_expanded_for_provider_save_contract(self):
        preview=self.client.post('/api/tools/voice-remix',json={'voice_id':'owned','prompt':'Warmer','text':'a'*100}).json()
        self.provider._request.return_value.json.return_value={'voice_id':'saved-remix'}
        response=self.client.post('/api/tools/voice-remix/save',json={'job_id':preview['job_id'],'generated_voice_id':'preview','name':'Warm'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertGreaterEqual(len(self.provider._request.call_args.kwargs['json']['voice_description']),20)

    def test_alignment_queues_without_direct_provider_or_double_charge(self):
        queued=AsyncMock(return_value={'job_id':'queued-job','status':'queued'})
        with patch.dict(os.environ,{'DURABLE_TOOLS_ENABLED':'true'}), patch('app.audio_extensions.validate_media',return_value=2), patch('app.server.enqueue_tool',queued):
            response=self.client.post('/api/tools/alignment',data={'text':'Сайн байна','title':'Тааруулах'},files={'file':('audio.wav',b'audio','audio/wav')})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'queued')
        self.provider._request.assert_not_called(); self.charge.assert_not_called()
        args=queued.call_args.args
        self.assertEqual(args[0],{'user_id':'u'}); self.assertEqual(args[1],'forced_alignment')
        self.assertEqual(args[3]['method'],'forced_alignment'); self.assertEqual(args[3]['args'][:2],['Сайн байна',2])
