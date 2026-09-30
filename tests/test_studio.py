import io
import math
import struct
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
import wave
from app import core, server, worker
from app.engine import ElevenLabsEngine, assemble

def wav_bytes(seconds=4):
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
        cls.temp=tempfile.TemporaryDirectory();core.DATA=Path(cls.temp.name);core.init()
        os.environ['ALLOW_REGISTRATION']='true'
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.base=f'http://127.0.0.1:{cls.http.server_port}';server.ORIGIN=cls.base
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.temp.cleanup()

    def request(self,path,method='GET',body=None,auth=None,origin=True,csrf=True):
        headers={}
        if body is not None:headers['Content-Type']='application/json'
        if origin:headers['Origin']=self.base
        if auth:
            headers['Cookie']=auth[0]
            if csrf:headers['X-CSRF-Token']=auth[1]
        req=urllib.request.Request(self.base+'/api'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:response=urllib.request.urlopen(req)
        except urllib.error.HTTPError as exc:response=exc
        raw=response.read();data=json.loads(raw) if response.headers.get('Content-Type','').startswith('application/json') else raw
        return response.status,data,response.headers

    def account(self,name):
        status,data,headers=self.request('/register','POST',{'email':name+'@example.com','password':'strong-password-123'})
        self.assertEqual(status,200,data)
        return headers['Set-Cookie'].split(';')[0],data['user']['csrf']

    def test_eleven_only_queue_and_isolation(self):
        alice=self.account('alice');bob=self.account('bob')
        self.assertEqual(self.request('/jobs')[0],401)
        self.assertEqual(self.request('/logout','POST',{},alice,csrf=False)[0],403)
        self.assertEqual(self.request('/logout','POST',{},alice,origin=False)[0],403)
        self.assertEqual(self.request('/voices','POST',{},alice)[0],409)
        self.assertEqual(self.request('/jobs','POST',{'text':'Сайн байна уу.','voice_id':'builtin-female'},alice)[0],422)
        catalog=json.dumps([
            {'id':'voice-a','name':'RAINY A'},
            {'id':'voice-b','name':'RAINY B'}
        ])
        with patch.dict(os.environ, {'ELEVENLABS_VOICES_JSON':catalog}, clear=False), patch('app.server.ElevenLabsEngine.readiness',return_value=(True,'ready')):
            status,voices,_=self.request('/voices',auth=alice)
            self.assertEqual(status,200)
            self.assertEqual([v['id'] for v in voices['voices']],['voice-a','voice-b'])
            self.assertEqual(self.request('/jobs','POST',{'text':'Сайн байна уу.','voice_id':'voice-x'},alice)[0],422)
            status,data,_=self.request('/jobs','POST',{'text':'Сайн байна уу.','voice_id':'voice-b'},alice)
            self.assertEqual(status,202,data);job_id=data['id']
            self.assertEqual(self.request('/jobs/'+job_id,auth=bob)[0],404)
            self.assertEqual(self.request('/jobs/'+job_id+'/wav',auth=alice)[0],409)
        self.assertEqual(self.request('/jobs/'+job_id,'DELETE',{},alice)[0],200)

    def test_session_logout(self):
        auth=self.account('logout')
        self.assertIsNotNone(self.request('/me',auth=auth)[1]['user'])
        self.assertEqual(self.request('/logout','POST',{},auth)[0],200)
        self.assertIsNone(self.request('/me',auth=auth)[1]['user'])

class AudioTests(unittest.TestCase):
    def test_default_mongolian_voice_catalog(self):
        with patch.dict(os.environ, {'ELEVENLABS_VOICES_JSON':''}, clear=False):
            voices = ElevenLabsEngine.configured_voices()
        self.assertEqual(len(voices),12)
        self.assertEqual(voices[0]['id'],'WgH4JH8sD6a2SIrujiKn')
        self.assertEqual(voices[0]['name'],'Sarnai - Proud Mongolian Narrator')
        self.assertEqual(voices[-1]['id'],'RbMF2tQ1nCK38TfvNGLk')
        self.assertEqual(voices[-1]['name'],'Ganbold - Confident Khalkha Ad')

    def test_eleven_v4_pcm_adapter(self):
        pcm = struct.pack('<h',800) * 2400

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'eleven.wav'
            catalog=json.dumps([{'id':'voice-123','name':'Test Voice'}])
            with patch.dict(os.environ, {'ELEVENLABS_API_KEY':'test-key','ELEVENLABS_VOICES_JSON':catalog,'ELEVENLABS_LANGUAGE_CODE':'mn'}, clear=False):
                with patch('app.engine.ElevenLabs') as client_cls:
                    convert = client_cls.return_value.text_to_speech.convert
                    convert.return_value = [pcm]
                    engine = ElevenLabsEngine()
                    self.assertTrue(engine.readiness()[0])
                    engine.synthesize('Сайн байна уу.',output,1.0,'voice-123')
                    client_cls.assert_called_once_with(api_key='test-key')
                    convert.assert_called_once_with(
                        text='Сайн байна уу.',
                        voice_id='voice-123',
                        model_id='eleven_v4',
                        output_format='pcm_24000',
                        language_code='mn',
                    )
            with wave.open(str(output)) as audio:
                self.assertEqual(audio.getframerate(),24000)
                self.assertEqual(audio.getnchannels(),1)
                self.assertGreater(audio.getnframes(),0)

    def test_srt_timing_and_overrun(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'in.wav';source.write_bytes(wav_bytes(1));output=Path(folder)/'out.wav'
            warnings=assemble([source],output,[{'start':2,'end':2.5}])
            self.assertEqual(len(warnings),1)
            with wave.open(str(output)) as audio:self.assertEqual(audio.getnframes()/audio.getframerate(),3)
            with self.assertRaises(ValueError):assemble([source,source],output,[{'start':0,'end':.5},{'start':.5,'end':2}])

    def test_worker_full_export_with_explicit_test_double(self):
        old=core.DATA
        with tempfile.TemporaryDirectory() as folder:
            core.DATA=Path(folder);core.init()
            try:
                with core.db() as c:
                    c.execute('INSERT INTO users VALUES(?,?,?,?)',('u','worker@example.com','unused',time.time()))
                    c.execute('INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)',('j','u','voice-worker','Test',json.dumps({'text':'Сайн байна уу.','speed':1}),'running',time.time()))
                    job=c.execute('SELECT * FROM jobs WHERE id=?',('j',)).fetchone()
                def synth(text,output,speed,voice_id):output.write_bytes(wav_bytes(.2))
                catalog=json.dumps([{'id':'voice-worker','name':'Worker Voice'}])
                with patch.dict(os.environ, {'ELEVENLABS_VOICES_JSON':catalog}, clear=False), patch.object(worker.engine,'synthesize',side_effect=synth):worker.run_job(job)
                with core.db() as c:self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',('j',)).fetchone()[0],'done')
                self.assertTrue((core.DATA/'outputs/j.mp3').stat().st_size>0)
                self.assertFalse((core.DATA/'tmp/j').exists())
            finally:core.DATA=old

if __name__=='__main__':unittest.main()
