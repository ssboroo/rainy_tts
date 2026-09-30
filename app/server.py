"""Same-origin HTTP API. Production TLS and connection limits are handled by Caddy."""
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from . import core
from .engine import ElevenLabsEngine, OronEngine, convert_reference

STATIC = Path(__file__).parent / 'static'
ORIGIN = os.getenv('PUBLIC_ORIGIN', 'http://localhost:8080').rstrip('/')
SECURE = ORIGIN.startswith('https://')
LIMIT = 12 * 1024 * 1024
RATE = {}
RATE_LOCK = threading.Lock()

class HTTPError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message

class Handler(BaseHTTPRequestHandler):
    server_version = 'RainyVoice'
    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, format, *args):
        # Never log uploaded text, cookies, passwords, or query strings.
        logging.info('%s %s', self.command, self.path.split('?')[0])

    def send(self, status=200, data=None, cookie=None):
        encoded = json.dumps(data or {}, ensure_ascii=False).encode()
        self.send_response(status)
        self.headers_common('application/json; charset=utf-8')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers(); self.wfile.write(encoded)

    def headers_common(self, mime):
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def body(self):
        try:
            length = int(self.headers.get('Content-Length','0'))
        except ValueError:
            raise HTTPError(400,'Хүсэлт буруу байна.')
        if not 0 < length <= LIMIT:
            raise HTTPError(413,'Файл эсвэл хүсэлт хэт том байна.')
        if not self.headers.get('Content-Type','').startswith('application/json'):
            raise HTTPError(415,'JSON хүсэлт шаардлагатай.')
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400,'Хүсэлт буруу байна.')

    def session(self, required=True):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie',''))
            raw = cookies['session'].value if 'session' in cookies else ''
        except Exception:
            raw = ''
        token = hashlib.sha256(raw.encode()).hexdigest()
        with core.db() as c:
            row = c.execute('SELECT sessions.*,users.email FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>?',(token,time.time())).fetchone()
        if not row and required:
            raise HTTPError(401,'Эхлээд нэвтэрнэ үү.')
        return row

    def mutation_guard(self, session=None):
        if self.headers.get('Origin') != ORIGIN:
            raise HTTPError(403,'Хүсэлтийн эх сурвалж зөвшөөрөгдөөгүй.')
        if session and not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']):
            raise HTTPError(403,'Хуудсаа шинэчлээд дахин оролдоно уу.')

    def throttle(self, key, limit=12, seconds=900):
        now = time.time()
        with RATE_LOCK:
            # TTL cleanup prevents unbounded memory growth.
            for stale in [k for k,v in RATE.items() if now-v[0]>seconds]:
                del RATE[stale]
            start, count = RATE.get(key,(now,0))
            if count >= limit:
                raise HTTPError(429,'Түр хүлээгээд дахин оролдоно уу.')
            RATE[key] = (start,count+1)

    def file(self, path, mime, download=False):
        if not path.is_file():
            raise HTTPError(404,'Файл олдсонгүй.')
        self.send_response(200); self.headers_common(mime)
        self.send_header('Content-Length',str(path.stat().st_size))
        if download:
            self.send_header('Content-Disposition',f'attachment; filename="rainy-voice{path.suffix}"')
        self.end_headers()
        with path.open('rb') as stream:
            while chunk := stream.read(65536):
                self.wfile.write(chunk)

    def do_GET(self):
        self.dispatch('GET')
    def do_POST(self):
        self.dispatch('POST')
    def do_DELETE(self):
        self.dispatch('DELETE')

    def dispatch(self, method):
        try:
            self.route(method, urlparse(self.path).path)
        except HTTPError as exc:
            self.send(exc.status,{'error':exc.message})
        except ValueError as exc:
            self.send(422,{'error':str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception('Request failed')
            self.send(500,{'error':'Серверийн алдаа гарлаа. Дахин оролдоно уу.'})

    def route(self, method, path):
        if method == 'GET' and path in ('/','/app.js','/style.css','/favicon.svg'):
            name = 'index.html' if path == '/' else path[1:]
            mime = {'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml'}[name.split('.')[-1]]
            return self.file(STATIC / name,mime)
        if method == 'GET' and path == '/api/health':
            oron_ready, oron_reason = OronEngine().readiness()
            eleven_ready, eleven_reason = ElevenLabsEngine().readiness()
            ready = oron_ready or eleven_ready
            if oron_ready and eleven_ready:
                reason = 'Oron + Eleven v4 бэлэн'
            elif eleven_ready:
                reason = eleven_reason
            elif oron_ready:
                reason = oron_reason
            else:
                reason = f'Oron: {oron_reason} Eleven v4: {eleven_reason}'
            return self.send(data={'ok':True,'engine_ready':ready,'engine_message':reason,'providers':{'oron':{'ready':oron_ready,'message':oron_reason},'eleven_v4':{'ready':eleven_ready,'message':eleven_reason}},'capabilities':{'voice_cloning':os.getenv('ENABLE_EXPERIMENTAL_CLONING')=='true','emotion':False,'voice_design':False},'registration_open':os.getenv('ALLOW_REGISTRATION','false')=='true'})
        if method == 'GET' and path == '/api/me':
            session = self.session(False)
            return self.send(data={'user':{'email':session['email'],'csrf':session['csrf']} if session else None})
        if method == 'POST' and path in ('/api/register','/api/login'):
            self.mutation_guard()
            self.throttle('auth:'+self.client_address[0],30)
            data = self.body()
            email = str(data.get('email','')).strip().lower()
            password = str(data.get('password',''))
            if not re.fullmatch(r'[^\s@]{1,64}@[^\s@]{1,180}\.[^\s@]{2,30}',email) or not 12 <= len(password) <= 128:
                raise HTTPError(422,'Зөв имэйл, 12–128 тэмдэгттэй нууц үг оруулна уу.')
            self.throttle('email:'+email,12)
            with core.db() as c:
                if path == '/api/register':
                    if os.getenv('ALLOW_REGISTRATION','false') != 'true':
                        raise HTTPError(403,'Одоогоор туршилтын бүртгэл хаалттай байна.')
                    try:
                        c.execute('INSERT INTO users VALUES(?,?,?,?)',(core.uid(),email,core.hash_password(password),time.time()))
                    except sqlite3.IntegrityError:
                        raise HTTPError(409,'Энэ имэйлээр бүртгэл үүсгэх боломжгүй байна.')
                user = c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
                if not user or not core.verify_password(password,user['password']):
                    raise HTTPError(401,'Имэйл эсвэл нууц үг буруу байна.')
                raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
                c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(raw.encode()).hexdigest(),user['id'],csrf,time.time()+86400*7))
            cookie = f'session={raw}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800' + ('; Secure' if SECURE else '')
            return self.send(data={'user':{'email':email,'csrf':csrf}},cookie=cookie)
        session = self.session()
        user = session['user_id']
        if method != 'GET':
            self.mutation_guard(session)
        if path == '/api/logout' and method == 'POST':
            with core.db() as c:
                c.execute('DELETE FROM sessions WHERE token=?',(session['token'],))
            return self.send(cookie='session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'+('; Secure' if SECURE else ''))
        if path == '/api/voices' and method == 'GET':
            with core.db() as c:
                rows = [dict(r) for r in c.execute('SELECT id,name,transcript,created FROM voices WHERE user_id=? ORDER BY created DESC',(user,))]
            builtins = [{'id':'builtin-female','name':'Эмэгтэй · Oron','builtin':True},{'id':'builtin-male','name':'Эрэгтэй · Oron','builtin':True}]
            if ElevenLabsEngine().readiness()[0]:
                label = os.getenv('ELEVENLABS_VOICE_LABEL','Монгол · Eleven v4').strip()[:80] or 'Монгол · Eleven v4'
                builtins.insert(0, {'id':ElevenLabsEngine.builtin_id,'name':label,'builtin':True})
            return self.send(data={'voices':builtins+rows})
        if path == '/api/voices' and method == 'POST':
            self.throttle('upload:'+user,20)
            data = self.body()
            if data.get('consent') is not True:
                raise HTTPError(422,'Өөрийн эсвэл ашиглах зөвшөөрөлтэй хоолой байна гэдгийг батална уу.')
            name = str(data.get('name','')).strip()
            transcript = core.prepare_text(str(data.get('transcript','')))
            if not 1 <= len(name) <= 80 or len(transcript)>1500:
                raise HTTPError(422,'Хоолойн нэр эсвэл бичлэгийн текст хэт урт байна.')
            with core.db() as c:
                if c.execute('SELECT COUNT(*) FROM voices WHERE user_id=?',(user,)).fetchone()[0]>=10:
                    raise HTTPError(409,'Хамгийн ихдээ 10 хоолой хадгална.')
            try:
                audio = base64.b64decode(data.get('audio',''),validate=True)
            except Exception:
                raise HTTPError(422,'Аудио буруу байна.')
            if not 100 <= len(audio) <= 8*1024*1024:
                raise HTTPError(413,'Аудио 8 MB-аас бага байна.')
            voice_id = core.uid(); target = core.DATA/'voices'/(voice_id+'.wav')
            try:
                with tempfile.NamedTemporaryFile(dir=core.DATA/'tmp',suffix='.audio') as source:
                    source.write(audio); source.flush()
                    duration = convert_reference(source.name,target)
                with core.db() as c:
                    c.execute('INSERT INTO voices VALUES(?,?,?,?,?)',(voice_id,user,name,transcript,time.time()))
            except (subprocess.SubprocessError, ValueError):
                target.unlink(missing_ok=True)
                raise HTTPError(422,'Аудиог уншиж чадсангүй. 3–12 секундийн сонсогдохуйц цэвэр WAV, MP3 эсвэл WebM бичлэг оруулна уу.')
            return self.send(201,{'id':voice_id,'duration':duration})
        match = re.fullmatch(r'/api/voices/([a-f0-9]{32})(/audio)?',path)
        if match:
            voice_id = match[1]
            with core.db() as c:
                if method == 'DELETE':
                    c.execute('BEGIN IMMEDIATE')
                voice = c.execute('SELECT * FROM voices WHERE id=? AND user_id=?',(voice_id,user)).fetchone()
                if not voice:
                    raise HTTPError(404,'Хоолой олдсонгүй.')
                if method == 'DELETE' and not match[2]:
                    if c.execute("SELECT 1 FROM jobs WHERE voice_id=? AND status IN ('queued','running')",(voice_id,)).fetchone():
                        raise HTTPError(409,'Энэ хоолойгоор дуу үүсгэж байна. Дууссаны дараа устгана уу.')
                    c.execute('DELETE FROM voices WHERE id=?',(voice_id,))
                    (core.DATA/'voices'/(voice_id+'.wav')).unlink(missing_ok=True)
                    return self.send()
            if method == 'GET' and match[2]:
                return self.file(core.DATA/'voices'/(voice_id+'.wav'),'audio/wav')
        if path == '/api/prepare' and method == 'POST':
            data = self.body()
            return self.send(data={'text':core.prepare_text(str(data.get('text','')), data.get('glossary',{}))})
        if path == '/api/jobs' and method == 'GET':
            with core.db() as c:
                rows = [core.public_job(row) for row in c.execute('SELECT * FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT 50',(user,))]
            return self.send(data={'jobs':rows})
        if path == '/api/jobs' and method == 'POST':
            self.throttle('job:'+user,30)
            data = self.body(); voice_id = str(data.get('voice_id',''))
            selected_engine = ElevenLabsEngine() if voice_id == ElevenLabsEngine.builtin_id else OronEngine()
            ready, reason = selected_engine.readiness()
            if not ready:
                raise HTTPError(503,reason)
            title = str(data.get('title','Шинэ бүтээл')).strip()[:100] or 'Шинэ бүтээл'
            speed = float(data.get('speed',1))
            if not .8 <= speed <= 1.2:
                raise HTTPError(422,'Хурд 0.8–1.2 хооронд байна.')
            glossary = data.get('glossary',{})
            if not isinstance(glossary,dict) or len(glossary)>100 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in glossary.items()):
                raise HTTPError(422,'Дуудлагын толь буруу байна.')
            payload = {'speed':speed}
            if data.get('srt'):
                if len(str(data['srt']))>20000:
                    raise HTTPError(422,'SRT хэт урт байна.')
                cues = core.parse_srt(data['srt'])
                for cue in cues:
                    cue['text'] = core.prepare_text(cue['text'],glossary)
                    if len(cue['text'])>240:
                        raise HTTPError(422,'Нэг SRT реплик 240 тэмдэгтээс хэтрэхгүй байна.')
                payload['cues'] = cues
                count = sum(len(cue['text']) for cue in cues)
            else:
                payload['text'] = core.prepare_text(str(data.get('text','')),glossary)
                count = len(payload['text'])
            if count>12000:
                raise HTTPError(422,'Нэг ажил 12000 тэмдэгтээс хэтрэхгүй байна.')
            with core.db() as c:
                c.execute('BEGIN IMMEDIATE')
                if voice_id not in ('builtin-male','builtin-female',ElevenLabsEngine.builtin_id):
                    if os.getenv('ENABLE_EXPERIMENTAL_CLONING') != 'true':
                        raise HTTPError(409,'Хоолой дуурайлтын чанарын туршилт хараахан нээгдээгүй.')
                    if not c.execute('SELECT 1 FROM voices WHERE id=? AND user_id=?',(voice_id,user)).fetchone():
                        raise HTTPError(404,'Хоолой олдсонгүй.')
                active = c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running')",(user,)).fetchone()[0]
                daily = c.execute('SELECT COUNT(*) FROM jobs WHERE user_id=? AND created>?',(user,time.time()-86400)).fetchone()[0]
                if active>=3 or daily>=20:
                    raise HTTPError(429,'Зэрэг 3 ажил, өдөрт 20 ажил үүсгэх туршилтын хязгаартай.')
                job_id = core.uid()
                c.execute('INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)',(job_id,user,voice_id,title,json.dumps(payload,ensure_ascii=False),'queued',time.time()))
            return self.send(202,{'id':job_id})
        match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})(?:/(wav|mp3))?',path)
        if match:
            with core.db() as c:
                if method == 'DELETE':
                    c.execute('BEGIN IMMEDIATE')
                job = c.execute('SELECT * FROM jobs WHERE id=? AND user_id=?',(match[1],user)).fetchone()
                if not job:
                    raise HTTPError(404,'Бүтээл олдсонгүй.')
                if method == 'DELETE' and not match[2]:
                    if job['status']=='running':
                        raise HTTPError(409,'Ажил дууссаны дараа устгана уу.')
                    c.execute('DELETE FROM jobs WHERE id=?',(job['id'],))
                    for extension in ('wav','mp3'):
                        (core.DATA/'outputs'/(job['id']+'.'+extension)).unlink(missing_ok=True)
                    return self.send()
            if method == 'GET':
                if match[2]:
                    if job['status']!='done':
                        raise HTTPError(409,'Дуу хараахан бэлэн болоогүй.')
                    return self.file(core.DATA/'outputs'/(job['id']+'.'+match[2]),'audio/wav' if match[2]=='wav' else 'audio/mpeg',download=match[2]=='mp3')
                return self.send(data=core.public_job(job))
        raise HTTPError(404,'Хуудас олдсонгүй.')

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    core.init()
    server = ThreadingHTTPServer((os.getenv('HOST','127.0.0.1'),int(os.getenv('PORT','8080'))),Handler)
    server.daemon_threads = True
    logging.info('Studio ready on port %s',server.server_port)
    server.serve_forever()
