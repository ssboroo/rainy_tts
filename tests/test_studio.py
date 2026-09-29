import base64
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
from app.engine import assemble

def wav_bytes(seconds=4):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000)
        out.writeframes(b''.join(struct.pack('<h',int(2000*math.sin(2*math.pi*220*i/24000))) for i in range(int(24000*seconds))))
    return buffer.getvalue()

class TextTests(unittest.TestCase):
    def test_glossary_and_validation(self):
        self.assertEqual(core.prepare_text('RAINY сайн байна.',{'RAINY':'Рэйни'}),'Рэйни сайн байна.')
        for text in ('','45000₮','hello','Сайн 😀'):
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
    def test_isolation_csrf_upload_and_queue(self):
        alice=self.account('alice');bob=self.account('bob')
        self.assertEqual(self.request('/jobs')[0],401)
        self.assertEqual(self.request('/logout','POST',{},alice,csrf=False)[0],403)
        self.assertEqual(self.request('/logout','POST',{},alice,origin=False)[0],403)
        payload={'name':'Миний хоолой','transcript':'Сайн байна уу.','consent':True,'audio':base64.b64encode(wav_bytes()).decode()}
        status,data,_=self.request('/voices','POST',payload,alice)
        self.assertEqual(status,201,data);voice=data['id']
        self.assertEqual(self.request('/voices/'+voice+'/audio',auth=bob)[0],404)
        self.assertEqual(self.request('/voices/'+voice,'DELETE',{},bob)[0],404)
        self.assertEqual(self.request('/voices/'+voice+'/audio',auth=alice)[0],200)
        self.assertEqual(self.request('/jobs','POST',{'text':'Сайн байна уу.','voice_id':'builtin-female'},alice)[0],503)
        with patch('app.server.OronEngine.readiness',return_value=(True,'ready')):
            self.assertEqual(self.request('/jobs','POST',{'text':'Сайн','voice_id':voice},alice)[0],409)
            status,data,_=self.request('/jobs','POST',{'text':'Сайн байна уу.','voice_id':'builtin-female'},alice)
            self.assertEqual(status,202,data);job_id=data['id']
            self.assertEqual(self.request('/jobs/'+job_id,auth=bob)[0],404)
            self.assertEqual(self.request('/jobs/'+job_id+'/wav',auth=alice)[0],409)
        self.assertEqual(self.request('/jobs/'+job_id,'DELETE',{},alice)[0],200)
        self.assertEqual(self.request('/voices/'+voice,'DELETE',{},alice)[0],200)
        self.assertFalse((core.DATA/'voices'/(voice+'.wav')).exists())
    def test_bad_upload_and_missing_consent(self):
        auth=self.account('upload')
        payload={'name':'test','transcript':'Сайн байна уу.','consent':False,'audio':base64.b64encode(wav_bytes()).decode()}
        self.assertEqual(self.request('/voices','POST',payload,auth)[0],422)
        payload.update(consent=True,audio=base64.b64encode(b'bad audio'*100).decode())
        self.assertEqual(self.request('/voices','POST',payload,auth)[0],422)
    def test_session_logout(self):
        auth=self.account('logout')
        self.assertIsNotNone(self.request('/me',auth=auth)[1]['user'])
        self.assertEqual(self.request('/logout','POST',{},auth)[0],200)
        self.assertIsNone(self.request('/me',auth=auth)[1]['user'])

class AudioTests(unittest.TestCase):
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
                    c.execute('INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)',('j','u','builtin-female','Test',json.dumps({'text':'Сайн байна уу.','speed':1}),'running',time.time()))
                    job=c.execute('SELECT * FROM jobs WHERE id=?',('j',)).fetchone()
                def synth(text,reference,transcript,output,speed):output.write_bytes(wav_bytes(.2))
                with patch.object(worker.engine,'builtin',return_value=(Path('reference.wav'),'Сайн')),patch.object(worker.engine,'synthesize',side_effect=synth):worker.run_job(job)
                with core.db() as c:self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',('j',)).fetchone()[0],'done')
                self.assertTrue((core.DATA/'outputs/j.mp3').stat().st_size>0)
                self.assertFalse((core.DATA/'tmp/j').exists())
            finally:core.DATA=old

if __name__=='__main__':unittest.main()
