import io
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import wave

from fastapi.testclient import TestClient

from app import core, server, worker
from app.engine import ElevenLabsEngine, assemble, friendly_elevenlabs_error
from app.eleven_tools import ElevenTools

def wav_bytes(seconds=.2):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000)
        out.writeframes(b''.join(struct.pack('<h',int(2000*math.sin(2*math.pi*220*i/24000))) for i in range(int(24000*seconds))))
    return buffer.getvalue()

class TextTests(unittest.TestCase):
    def test_glossary_and_validation(self):
        self.assertEqual(core.prepare_text('RAINY сайн байна.',{'RAINY':'Рэйни'}),'Рэйни сайн байна.')
        self.assertEqual(core.prepare_text('RAINY Voice 2026 — OpenAI API 45,000₮.'),'RAINY Voice 2026 — OpenAI API 45,000₮.')
        self.assertEqual(core.prepare_text('hello world'),'hello world')
        for text in ('','Сайн 😀'):
            with self.assertRaises(ValueError):core.prepare_text(text)

    def test_chunks_preserve_words(self):
        text='Сайн байна уу. '*100
        parts=core.chunks(text)
        self.assertTrue(all(len(c)<=240 for c in parts))
        self.assertEqual(' '.join(parts),' '.join(text.split()))

    def test_srt(self):
        cues=core.parse_srt('1\n00:00:01,000 --> 00:00:03,000\nСайн байна уу.\n\n2\n00:00:04,000 --> 00:00:06,000\nБаяртай.')
        self.assertEqual(cues[1]['start'],4)
        with self.assertRaises(ValueError):core.parse_srt('1\n00:00:04,000 --> 00:00:03,000\nСайн')
        with self.assertRaises(ValueError):core.parse_srt('1\n00:61:00,000 --> 00:62:00,000\nСайн')

    def test_passwords(self):
        password=core.hash_password('long-password-123')
        self.assertTrue(core.verify_password('long-password-123',password))
        self.assertFalse(core.verify_password('wrong',password))

class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_data=core.DATA
        cls.temp=tempfile.TemporaryDirectory()
        core.DATA=Path(cls.temp.name)
        core.init()
        os.environ['ALLOW_REGISTRATION']='true'
        server.ORIGIN='http://testserver'
        cls.client=TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        core.DATA=cls.old_data
        cls.temp.cleanup()

    def setUp(self):
        self.legacy_env=patch.dict(os.environ,{'BILLING_ENABLED':'false','DURABLE_TOOLS_ENABLED':'false','REALTIME_PROXY_ENABLED':'false'})
        self.legacy_env.start()
        self.addCleanup(self.legacy_env.stop)
        self.client.cookies.clear()
        email=f'user-{time.time_ns()}@example.com'
        response=self.client.post('/api/register',json={'email':email,'password':'strong-password-123'},headers={'Origin':'http://testserver'})
        self.assertEqual(response.status_code,200,response.text)
        self.csrf=response.json()['user']['csrf']
        self.headers={'Origin':'http://testserver','X-CSRF-Token':self.csrf}

    def test_health_reports_registration_open(self):
        with patch.dict(os.environ, {'ALLOW_REGISTRATION':'yes'}, clear=False):
            response=self.client.get('/api/health')
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['registration_open'])

    def test_registration_accepts_actual_same_origin_and_rejects_cross_site(self):
        with TestClient(server.app, base_url='http://127.0.0.1:8080') as local_client:
            email=f'local-{time.time_ns()}@example.com'
            response=local_client.post(
                '/api/register',
                json={'email':email,'password':'strong-password-123'},
                headers={'Origin':'http://127.0.0.1:8080'}
            )
            self.assertEqual(response.status_code,200,response.text)
        blocked=self.client.post(
            '/api/register',
            json={'email':f'evil-{time.time_ns()}@example.com','password':'strong-password-123'},
            headers={'Origin':'http://evil.test'}
        )
        self.assertEqual(blocked.status_code,403,blocked.text)

    def test_tts_queue_and_history(self):
        voice=ElevenLabsEngine.default_voice_catalog[0]['id']
        with patch('app.server.ElevenLabsEngine.readiness',return_value=(True,'ready')):
            response=self.client.post('/api/jobs',json={'text':'RAINY Voice 2026 сайн байна.','voice_id':voice,'model_id':'eleven_v4_turbo','speed':1},headers=self.headers)
        self.assertEqual(response.status_code,202,response.text)
        job_id=response.json()['id']
        with core.db() as db:
            row=db.execute('SELECT voice_id,payload FROM jobs WHERE id=?',(job_id,)).fetchone()
        self.assertEqual(row['voice_id'],voice)
        payload=json.loads(row['payload'])
        self.assertNotIn('provider_voice_id',payload)
        self.assertEqual(payload['model_id'],'eleven_v4_turbo')
        self.assertEqual(self.client.get('/api/jobs').status_code,200)
        history=self.client.get('/api/history').json()['items']
        self.assertEqual(history[0]['id'],job_id)
        self.assertEqual(history[0]['tool_type'],'tts')

    def test_tts_does_not_require_subscription_preflight(self):
        voice=ElevenLabsEngine.default_voice_catalog[0]['id']
        with patch('app.server.ElevenLabsEngine.readiness',return_value=(True,'ready')), patch.object(server.tools,'subscription',new=AsyncMock(side_effect=AssertionError('subscription should not be called'))):
            response=self.client.post('/api/jobs',json={'text':'Сайн байна уу.','voice_id':voice,'speed':1},headers=self.headers)
        self.assertEqual(response.status_code,202,response.text)

    def test_syncs_shared_voice_library(self):
        with core.db() as db:
            db.execute('DELETE FROM voice_aliases')
        subscription=AsyncMock(return_value={'tier':'starter','status':'active'})
        saved=AsyncMock(return_value=None)
        shared=AsyncMock(side_effect=lambda voice_id:{'voice_id':voice_id,'public_owner_id':'owner-'+voice_id,'preview_url':'https://example.test/p.mp3'})
        added=AsyncMock(side_effect=lambda owner,voice_id,name:{'voice_id':'saved-'+voice_id})
        with patch.object(server.tools,'subscription',new=subscription), patch.object(server.tools,'find_saved_shared_voice',new=saved), patch.object(server.tools,'find_shared_voice',new=shared), patch.object(server.tools,'add_shared_voice',new=added):
            response=self.client.post('/api/voices/sync',json={},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['voices']),12)
        self.assertTrue(all(v['status']=='ready' for v in response.json()['voices']))
        with core.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM voice_aliases').fetchone()[0],12)
        with core.db() as db:
            db.execute('DELETE FROM voice_aliases')

    def test_clone_voice_and_delete(self):
        with patch.object(server.tools,'clone_voice',new=AsyncMock(return_value={'voice_id':'clone-test','requires_verification':False})):
            response=self.client.post(
                '/api/voices/clone',
                data={'name':'My Clone','description':'test','consent':'true','remove_background_noise':'false'},
                files=[('files',('sample.wav',wav_bytes(),'audio/wav'))],
                headers=self.headers
            )
        self.assertEqual(response.status_code,200,response.text)
        voices=self.client.get('/api/voices').json()['voices']
        self.assertTrue(any(v['id']=='clone-test' for v in voices))
        with patch.object(server.tools,'delete_voice',new=AsyncMock(return_value={'status':'ok'})):
            deleted=self.client.delete('/api/voices/clone-test',headers=self.headers)
        self.assertEqual(deleted.status_code,200,deleted.text)

    def test_dialogue_music_and_sound_effects(self):
        ids=[v['id'] for v in ElevenLabsEngine.default_voice_catalog[:2]]
        dialogue_mock=AsyncMock(return_value=b'ID3dialogue')
        with patch.object(server.tools,'dialogue',new=dialogue_mock):
            response=self.client.post('/api/tools/dialogue',json={'title':'Podcast','inputs':[{'voice_id':ids[0],'text':'Сайн байна уу.'},{'voice_id':ids[1],'text':'Сайн, баярлалаа.'}]},headers=self.headers)
        dialogue_mock.assert_awaited_once()
        sent_inputs=dialogue_mock.await_args.args[0]
        self.assertEqual(sent_inputs[0]['voice_id'],ids[0])
        self.assertEqual(sent_inputs[1]['voice_id'],ids[1])
        self.assertEqual(response.status_code,200,response.text)
        music_mock=AsyncMock(return_value=b'ID3music')
        with patch.object(server.tools,'music',new=music_mock):
            response=self.client.post('/api/tools/music',json={'prompt':'Mongolian cinematic ambient','music_length_ms':10000,'model_id':'music_v2_5','force_instrumental':True},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        music_mock.assert_awaited_once_with('Mongolian cinematic ambient',10000,'music_v2_5',True)
        sfx_mock=AsyncMock(return_value=b'ID3sfx')
        with patch.object(server.tools,'sound_effect',new=sfx_mock):
            response=self.client.post('/api/tools/sound-effects',json={'text':'cinematic impact','duration_seconds':5,'loop':True,'prompt_influence':.6},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        sfx_mock.assert_awaited_once_with('cinematic impact',5.0,True,.6)

    def test_stt_voice_changer_and_realtime_token(self):
        transcript={
            'language_code':'mn','language_probability':.99,
            'text':'Сайн байн уу RAINY',
            'edited_transcript':{'kind':'transcript','text':'Сайн байна уу, RAINY.'},
            'words':[{'text':'Сайн','type':'word','start':0,'end':.4},{'text':' ','type':'spacing','start':.4,'end':.4},{'text':'байн','type':'word','start':.4,'end':.8},{'text':' ','type':'spacing','start':.8,'end':.8},{'text':'уу','type':'word','start':.8,'end':1.0},{'text':' ','type':'spacing','start':1.0,'end':1.0},{'text':'RAINY','type':'word','start':1.0,'end':1.4}]
        }
        stt_mock=AsyncMock(return_value=transcript)
        with patch.object(server.tools,'speech_to_text',new=stt_mock):
            response=self.client.post(
                '/api/tools/stt',
                data={'language_code':'mn','keyterms':'RAINY, ElevenLabs','polish':'true','no_verbatim':'true','diarize':'false','num_speakers':'1'},
                files={'file':('voice.wav',wav_bytes(),'audio/wav')},
                headers=self.headers
            )
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['text'],'Сайн байна уу, RAINY.')
        self.assertEqual(response.json()['raw_text'],'Сайн байн уу RAINY')
        self.assertTrue(response.json()['polished'])
        self.assertEqual(response.json()['keyterms_used'],2)
        args=stt_mock.await_args.args
        self.assertEqual(args[1],'mn')
        self.assertEqual(args[2],['RAINY','ElevenLabs'])
        self.assertEqual(args[3:],(True,False,1,True))
        job_id=response.json()['job_id']
        history=self.client.get('/api/history').json()['items']
        stt_item=next(item for item in history if item['id']==job_id)
        names={art['filename'] for art in stt_item['artifacts']}
        self.assertIn('transcript.txt',names)
        self.assertIn('transcript-raw.txt',names)
        self.assertIn('transcript.srt',names)
        srt_artifact=next(art for art in stt_item['artifacts'] if art['filename']=='transcript.srt')
        srt_response=self.client.get(srt_artifact['url'])
        self.assertIn('Сайн байн уу RAINY',srt_response.text)
        voice=ElevenLabsEngine.default_voice_catalog[0]['id']
        changer_mock=AsyncMock(return_value=b'ID3changed')
        with patch.object(server.tools,'voice_changer',new=changer_mock):
            response=self.client.post('/api/tools/voice-changer',data={'voice_id':voice,'remove_background_noise':'false'},files={'file':('voice.wav',wav_bytes(),'audio/wav')},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(changer_mock.await_args.args[1],voice)
        with patch.object(server.tools,'realtime_token',new=AsyncMock(return_value={'token':'sutkn_test'})):
            response=self.client.post('/api/tools/realtime-token',json={},headers=self.headers)
        self.assertEqual(response.json()['token'],'sutkn_test')
        saved=self.client.post('/api/tools/realtime-save',json={'title':'Live Notes','text':'Сайн байна уу. Шууд бичвэр.'},headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text)
        history=self.client.get('/api/history').json()['items']
        realtime=[item for item in history if item['tool_type']=='realtime_stt']
        self.assertTrue(realtime)
        self.assertTrue(realtime[0]['artifacts'])

    def test_stt_rejects_unsafe_or_too_many_keyterms(self):
        response=self.client.post(
            '/api/tools/stt',
            data={'language_code':'mn','keyterms':'bad<term>','polish':'true'},
            files={'file':('voice.wav',wav_bytes(),'audio/wav')},
            headers=self.headers
        )
        self.assertEqual(response.status_code,422,response.text)

    def test_voice_isolator(self):
        isolator=AsyncMock(return_value=(b'ID3clean',{'request_id':'req-1','trace_id':'trace-1'}))
        with patch.object(server.tools,'voice_isolator',new=isolator):
            response=self.client.post(
                '/api/tools/voice-isolator',
                files={'file':('voice.wav',wav_bytes(2),'audio/wav')},
                headers=self.headers
            )
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['provider_usage']['request_id'],'req-1')
        history=self.client.get('/api/history').json()['items']
        self.assertTrue(any(x['tool_type']=='voice_isolator' for x in history))

    def test_professional_voice_clone_flow(self):
        create=AsyncMock(return_value={'voice_id':'pvc-test'})
        samples=AsyncMock(return_value=[{'sample_id':'s1','duration_secs':30}])
        with patch.object(server.billing,'billing_enabled',return_value=False), \
             patch.object(server.tools,'pvc_create',new=create), \
             patch.object(server.tools,'pvc_add_samples',new=samples):
            response=self.client.post(
                '/api/voices/pvc',
                data={'name':'My PVC','description':'Mongolian professional voice','language':'mn','ownership':'true','remove_background_noise':'false'},
                files=[('files',('sample.wav',wav_bytes(2),'audio/wav'))],
                headers=self.headers
            )
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['voice_id'],'pvc-test')
        captcha=AsyncMock(return_value={'captcha':'base64-image'})
        with patch.object(server.tools,'pvc_get_captcha',new=captcha):
            response=self.client.get('/api/voices/pvc/pvc-test/captcha')
        self.assertEqual(response.status_code,200,response.text)
        verify=AsyncMock(return_value={'status':'ok'})
        with patch.object(server.tools,'pvc_verify_captcha',new=verify):
            response=self.client.post(
                '/api/voices/pvc/pvc-test/captcha',
                files={'recording':('verify.wav',wav_bytes(),'audio/wav')},
                headers=self.headers
            )
        self.assertEqual(response.status_code,200,response.text)
        train=AsyncMock(return_value={'status':'ok'})
        with patch.object(server.tools,'pvc_train',new=train):
            response=self.client.post('/api/voices/pvc/pvc-test/train',json={},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        ready={
            'voice_id':'pvc-test','name':'My PVC',
            'voice_verification':{'is_verified':True},
            'fine_tuning':{'state':{'eleven_v4':'fine_tuned'}}
        }
        with patch.object(server.tools,'pvc_status',new=AsyncMock(return_value=ready)):
            response=self.client.get('/api/voices/pvc/pvc-test')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['status'],'ready')
        voices=self.client.get('/api/voices').json()['voices']
        self.assertTrue(any(v['id']=='pvc-test' for v in voices))

    def test_reception_ai_webhook_flow(self):
        config=self.client.get('/api/reception/config')
        self.assertEqual(config.status_code,200,config.text)
        tool=next(x for x in config.json()['tools'] if x['name']=='create_lead')
        path=tool['url'].split('http://testserver')[-1]
        response=self.client.post(path,json={'name':'Bataa','phone':'99112233','interest':'booking'})
        self.assertEqual(response.status_code,200,response.text)
        events=self.client.get('/api/reception/events')
        self.assertEqual(events.status_code,200,events.text)
        self.assertTrue(any(x['tool_name']=='create_lead' for x in events.json()['items']))

    def test_dubbing_create_and_completed_output(self):
        create={'project_id':'proj_test','status':'queued','language_ids':['lang_test']}
        with patch.object(server.tools,'create_dubbing',new=AsyncMock(return_value=create)):
            response=self.client.post('/api/tools/dubbing',data={'reference':'Movie','target_language':'mn','source_language':'en','source_url':'https://example.test/movie.mp4'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        job_id=response.json()['job_id']
        project={'project_id':'proj_test','status':'ready','language_ids':['lang_test']}
        languages={'languages':[{'language_id':'lang_test','target_language':'mn','status':'completed','outputs':{'lossless_audio':'https://example.test/output.flac'}}]}
        with patch.object(server.tools,'get_dubbing_project',new=AsyncMock(return_value=project)), patch.object(server.tools,'list_dubbing_languages',new=AsyncMock(return_value=languages)), patch.object(server.tools,'download_url',new=AsyncMock(return_value=(b'fLaCdata','audio/flac'))):
            status=self.client.get('/api/tools/dubbing/'+job_id)
        self.assertEqual(status.status_code,200,status.text)
        self.assertEqual(status.json()['status'],'done')
        self.assertTrue(status.json()['artifacts'])

    def test_analytics(self):
        response=self.client.get('/api/analytics')
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertIn('wallet',data)
        self.assertIn('subscription',data)
        self.assertIn('credits_spent_30d',data)
        self.assertNotIn('usage',data)

class ElevenToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_scribe_v2_accuracy_multipart(self):
        class DummyUpload:
            filename='voice.wav'
            content_type='audio/wav'
            file=io.BytesIO(b'RIFF')
            async def seek(self,pos):
                self.file.seek(pos)

        tool=ElevenTools('test-key')
        response=MagicMock()
        response.json.return_value={'text':'ok'}
        request_mock=AsyncMock(return_value=response)
        with patch.object(tool,'_request',new=request_mock):
            result=await tool.speech_to_text(
                DummyUpload(),'mn',['RAINY','ElevenLabs'],True,False,1,True
            )
        self.assertEqual(result['text'],'ok')
        kwargs=request_mock.await_args.kwargs
        fields=kwargs['files']
        names=[item[0] for item in fields]
        self.assertEqual(names.count('keyterms'),2)
        values={name:value[1] for name,value in fields if name!='keyterms' and name!='file'}
        self.assertEqual(values['model_id'],'scribe_v2')
        self.assertEqual(values['language_code'],'mn')
        self.assertEqual(values['temperature'],'0')
        self.assertEqual(values['diarize'],'false')
        self.assertEqual(values['no_verbatim'],'true')
        self.assertIn('Do not translate',values['transcript_edit'])

class ProviderErrorTests(unittest.TestCase):
    def test_friendly_elevenlabs_errors(self):
        self.assertIn('API key',friendly_elevenlabs_error(Exception('invalid_api_key')))
        self.assertIn('credit',friendly_elevenlabs_error(Exception('insufficient_credits')))
        self.assertIn('voice',friendly_elevenlabs_error(Exception('voice_access_denied')))

class AudioTests(unittest.TestCase):
    def test_default_mongolian_voice_catalog(self):
        with patch.dict(os.environ, {'ELEVENLABS_VOICES_JSON':''}, clear=False):
            voices=ElevenLabsEngine.configured_voices()
        self.assertEqual(len(voices),12)
        self.assertEqual(voices[0]['id'],'WgH4JH8sD6a2SIrujiKn')
        self.assertEqual(voices[-1]['id'],'RbMF2tQ1nCK38TfvNGLk')

    def test_eleven_v4_sdk_adapter(self):
        pcm=struct.pack('<h',800)*2400
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'eleven.wav'
            catalog=json.dumps([{'id':'voice-123','name':'Test Voice'}])
            with patch.dict(os.environ, {'ELEVENLABS_API_KEY':'test-key','ELEVENLABS_VOICES_JSON':catalog,'ELEVENLABS_LANGUAGE_CODE':'mn'}, clear=False):
                with patch('app.engine.ElevenLabs') as client_cls:
                    convert=client_cls.return_value.text_to_speech.with_raw_response.convert
                    raw=MagicMock()
                    raw.data=[pcm]
                    raw.headers={'character-cost':'14','request-id':'req-tts','x-trace-id':'trace-tts'}
                    convert.return_value.__enter__.return_value=raw
                    engine=ElevenLabsEngine()
                    meta=engine.synthesize('Сайн байна уу.',output,1.0,'voice-123')
                    convert.assert_called_once_with(
                        text='Сайн байна уу.',
                        voice_id='voice-123',
                        model_id='eleven_v4',
                        output_format='pcm_24000',
                        language_code='mn',
                    )
                    self.assertEqual(meta['character_cost'],'14')
                    self.assertEqual(meta['request_id'],'req-tts')
            with wave.open(str(output)) as audio:
                self.assertEqual(audio.getframerate(),24000)

    def test_mux_dubbed_video_command(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.mp4';source.write_bytes(b'video')
            audio=Path(folder)/'dub.flac';audio.write_bytes(b'audio')
            output=Path(folder)/'output.mp4'
            def fake_run(command,**kwargs):
                self.assertIn('-map',command)
                self.assertIn('0:v:0',command)
                self.assertIn('1:a:0',command)
                output.write_bytes(b'muxed')
            with patch('app.server.subprocess.run',side_effect=fake_run):
                server.mux_dubbed_video(source,audio,output)
            self.assertEqual(output.read_bytes(),b'muxed')

    def test_srt_timing_and_overrun(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'in.wav';source.write_bytes(wav_bytes(1));output=Path(folder)/'out.wav'
            warnings=assemble([source],output,[{'start':2,'end':2.5}])
            self.assertEqual(len(warnings),1)
            with self.assertRaises(ValueError):assemble([source,source],output,[{'start':0,'end':.5},{'start':.5,'end':2}])

    def test_worker_export(self):
        old=core.DATA
        with tempfile.TemporaryDirectory() as folder:
            core.DATA=Path(folder);core.init()
            try:
                with core.db() as c:
                    c.execute('INSERT INTO users VALUES(?,?,?,?)',('u','worker@example.com','unused',time.time()))
                    c.execute('INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)',('j','u','voice-worker','Test',json.dumps({'text':'Сайн байна уу.','speed':1}),'running',time.time()))
                    job=c.execute('SELECT * FROM jobs WHERE id=?',('j',)).fetchone()
                def synth(text,output,speed,voice_id,trusted_voice=False,model_id=None):output.write_bytes(wav_bytes());return {'model_id':model_id}
                catalog=json.dumps([{'id':'voice-worker','name':'Worker Voice'}])
                with patch.dict(os.environ, {'ELEVENLABS_VOICES_JSON':catalog}, clear=False), patch.object(worker.engine,'synthesize',side_effect=synth):
                    worker.run_job(job)
                with core.db() as c:self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',('j',)).fetchone()[0],'done')
                self.assertTrue((core.DATA/'outputs/j.mp3').stat().st_size>0)
            finally:core.DATA=old

if __name__=='__main__':
    unittest.main()
