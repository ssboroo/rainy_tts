import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import wave

import httpx
from fastapi.testclient import TestClient
from app import core, billing, durable_jobs, server, voice_direction, operations
from app.engine import ElevenLabsEngine


class DirectionTests(unittest.TestCase):
    def test_v4_ipa_is_preserved(self):
        self.assertEqual(core.prepare_text('RAINY /ˈreɪni/'), 'RAINY /ˈreɪni/')
    def test_every_segment_is_directed_and_billable(self):
        payload={'model_id':'eleven_v4','emotion':'excited','text':('Сайн байна уу. '*50).strip()}
        texts=voice_direction.segments(payload)
        self.assertGreater(len(texts),1)
        self.assertTrue(all(text.startswith('[excited] ') for text in texts))
        self.assertEqual(sum(map(len,texts)),sum(map(len,core.chunks(payload['text'])))+len(texts)*10)

    def test_srt_times_are_preserved(self):
        cues=[{'start':1,'end':3,'text':'Сайн байна уу.'}]
        self.assertEqual(voice_direction.segments({'model_id':'eleven_v4','emotion':'whisper','cues':cues}),['[whisper] Сайн байна уу.'])
        self.assertEqual(cues[0]['start'],1)

    def test_invalid_direction_or_turbo_fails(self):
        for emotion,model in [('invented','eleven_v4'),('happy','eleven_v4_turbo')]:
            with self.assertRaises(ValueError):
                voice_direction.segments({'emotion':emotion,'model_id':model,'text':'Сайн'})

    def test_timeout_cause_is_not_refundable(self):
        wrapped=RuntimeError('failed');wrapped.__cause__=httpx.ReadTimeout('timeout')
        self.assertTrue(voice_direction.uncertain_failure(wrapped))
        self.assertFalse(voice_direction.uncertain_failure(ValueError('bad input')))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.old_data=core.DATA
        self.temp=tempfile.TemporaryDirectory();core.DATA=Path(self.temp.name);core.init()
        self.env=patch.dict(os.environ,{'ALLOW_REGISTRATION':'true','BILLING_ENABLED':'true','ADMIN_EMAILS':''})
        self.env.start();self.old_origin=server.ORIGIN;server.ORIGIN='http://testserver'
        server.RATE.clear()
        self.client=TestClient(server.app)
        result=self.client.post('/api/register',json={'email':'direction@example.com','password':'strong-password-123'},headers={'Origin':'http://testserver'})
        self.assertEqual(result.status_code,200,result.text)
        with core.db() as db:self.user=db.execute("SELECT id FROM users WHERE email='direction@example.com'").fetchone()[0]
        self.headers={'Origin':'http://testserver','X-CSRF-Token':result.json()['user']['csrf']}
        billing.grant(self.user,1000,'test')
        self.voice=ElevenLabsEngine.default_voice_catalog[0]['id']

    def tearDown(self):
        self.client.close();server.ORIGIN=self.old_origin;self.env.stop();core.DATA=self.old_data;self.temp.cleanup()

    def test_quote_does_not_charge_and_matches_submission(self):
        body={'voice_id':self.voice,'model_id':'eleven_v4','emotion':'happy','text':'RAINY сайн байна. '*20,'glossary':{'RAINY':'Рэйни'}}
        with patch('app.server.ElevenLabsEngine.readiness',return_value=(True,'')),patch('app.server.voice_cost_multiplier',new=AsyncMock(return_value=2)):
            quote=self.client.post('/api/jobs/quote',json=body,headers=self.headers)
            self.assertEqual(quote.status_code,200,quote.text)
            self.assertEqual(billing.wallet(self.user)['wallet']['balance'],1000)
            with core.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
            created=self.client.post('/api/jobs',json=body,headers=self.headers)
        self.assertEqual(created.status_code,202,created.text)
        self.assertEqual(created.json()['credits_used'],quote.json()['credits'])
        self.assertEqual(billing.wallet(self.user)['wallet']['balance'],1000-quote.json()['credits'])

    def test_daily_database_snapshot_is_consistent_and_idempotent(self):
        import sqlite3
        path=operations.daily_database_backup()
        self.assertEqual(operations.daily_database_backup(),path)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT balance FROM credit_wallets WHERE user_id=?',(self.user,)).fetchone()[0],1000)

    def test_single_customer_launch_has_profitable_entry_plan(self):
        with patch.dict(os.environ,{'ELEVENLABS_PROVIDER_PLAN':'starter','BILLING_EXPECTED_ACTIVE_USERS':'1'}):
            self.assertTrue(billing.get_plan('pro')['profit_safe'])
            self.assertNotIn('starter',{p['id'] for p in billing.public_plan_catalog()})
            self.assertTrue(billing.get_plan('pro')['profit_safe'])

    def test_interrupted_daily_snapshot_is_repaired(self):
        path=operations.daily_database_backup()
        path.write_bytes(b'partial database')
        operations.daily_database_backup()
        self.assertTrue(operations.verify_backup(path)['ok'])
        self.assertEqual(len(list(path.parent.glob('*.invalid-*'))),1)

    def test_queue_and_wallet_are_atomic_under_concurrency(self):
        def submit(i):
            try:
                billing.enqueue_tts(self.user,str(i),self.voice,'Test',{'text':'Сайн','speed':1,'model_id':'eleven_v4'},10,{'voice_multiplier':1,'model_id':'eleven_v4'})
                return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(submit,range(40)))
        self.assertEqual(sum(results),3)
        self.assertEqual(billing.wallet(self.user)['wallet']['balance'],970)
        with core.db() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='usage'").fetchone()[0],3)

    def test_foreign_or_unfinished_voiceover_is_rejected(self):
        response=self.client.post('/api/tools/video-voiceover',data={'source_job_id':'foreign'},files={'file':('video.mp4',b'video','video/mp4')},headers=self.headers)
        self.assertEqual(response.status_code,404,response.text)
        self.assertEqual(billing.wallet(self.user)['wallet']['balance'],1000)

    def make_media(self):
        audio=core.DATA/'outputs'/'source.wav'
        with wave.open(str(audio),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(24000);stream.writeframes(b'\0\0'*12000)
        video=core.DATA/'tmp'/'video.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=c=black:s=160x90:r=10','-t','2','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True,capture_output=True)
        with core.db() as db:
            db.execute('INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)',('source',self.user,self.voice,'Source','{}','done',time.time()))
        return audio,video

    def test_real_ffmpeg_voiceover_retains_full_video_and_history(self):
        audio,video=self.make_media()
        response=self.client.post('/api/tools/video-voiceover',data={'source_job_id':'source'},files={'file':('video.mp4',video.read_bytes(),'video/mp4')},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['credits_used'],10)
        job=durable_jobs.claim_next()
        asyncio.run(durable_jobs.execute(job))
        result=self.client.get('/api/tool-jobs/'+job['id']).json()
        self.assertEqual(result['status'],'done',result)
        output=core.tool_artifacts(job['id'],self.user)[0]
        with core.db() as db:path=Path(db.execute('SELECT path FROM artifacts WHERE id=?',(output['id'],)).fetchone()[0])
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(path)],check=True,capture_output=True,text=True)
        data=json.loads(probe.stdout)
        self.assertAlmostEqual(float(data['format']['duration']),2,delta=.2)
        self.assertEqual({s['codec_type'] for s in data['streams']},{'audio','video'})
        self.assertFalse(Path(job['upload_path']).exists())
        history=self.client.get('/api/history').json()['items']
        self.assertTrue(any(item['tool_type']=='video_voiceover' and item['artifacts'] for item in history))

    def test_voiceover_local_failure_refunds_reservation(self):
        audio,video=self.make_media()
        response=self.client.post('/api/tools/video-voiceover',data={'source_job_id':'source'},files={'file':('video.mp4',video.read_bytes(),'video/mp4')},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        audio.unlink()
        asyncio.run(durable_jobs.execute(durable_jobs.claim_next()))
        self.assertEqual(billing.wallet(self.user)['wallet']['balance'],1000)

    def test_dubbing_timeout_preserves_upstream_reservation(self):
        with patch('app.server.upload_duration_seconds',new=AsyncMock(return_value=10)),patch.object(server.tools,'create_dubbing',new=AsyncMock(side_effect=httpx.ReadTimeout('timeout'))):
            result=self.client.post('/api/tools/dubbing',data={'target_language':'mn'},files={'file':('voice.wav',b'RIFF','audio/wav')},headers=self.headers)
        self.assertGreaterEqual(result.status_code,400)
        self.assertEqual(billing.wallet(self.user)['wallet']['balance'],1000-billing.estimate('dubbing',seconds=10))

    def test_keyterms_are_validated_before_upstream(self):
        with patch.object(server.tools,'create_dubbing',new=AsyncMock()) as provider:
            result=self.client.post('/api/tools/dubbing',data={'target_language':'mn','keyterms':'<invalid>'},files={'file':('voice.wav',b'RIFF','audio/wav')},headers=self.headers)
        self.assertEqual(result.status_code,422)
        provider.assert_not_awaited()
