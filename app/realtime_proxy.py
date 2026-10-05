"""Server-bounded Scribe sessions; provider credentials never reach the browser."""
import asyncio
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from fastapi import WebSocket, WebSocketDisconnect
import websockets
from . import billing, core

MAX_SECONDS=900
LOCK=threading.Lock()


def ensure_schema():
    with core.db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS realtime_sessions(
            id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,user_id TEXT NOT NULL REFERENCES users(id),
            status TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,charge_id TEXT)''')


def reconcile_unused():
    ensure_schema()
    with core.db() as db:
        rows=db.execute("SELECT * FROM realtime_sessions WHERE status IN ('issued','expired') AND expires<?",(time.time(),)).fetchall()
        db.execute("UPDATE realtime_sessions SET status='expired' WHERE status='issued' AND expires<?",(time.time(),))
    for row in rows: billing.refund(row['user_id'],row['charge_id'],'realtime_unused')


def issue(user_id):
    if not os.getenv('ELEVENLABS_API_KEY','').strip(): raise ValueError('ElevenLabs холболт тохируулаагүй байна.')
    with LOCK:
        reconcile_unused()
        now=time.time()
        with core.db() as db:
            active=db.execute("SELECT 1 FROM realtime_sessions WHERE user_id=? AND status IN ('issued','connected') AND expires>?",(user_id,now)).fetchone()
        if active: raise ValueError('Шууд бичвэрийн нэг идэвхтэй эрх байна. Эхлээд өмнөх эрх дуусахыг хүлээнэ үү.')
        reference='rt-'+core.uid();credits=billing.estimate('realtime_stt',seconds=MAX_SECONDS)
        charge_id=billing.debit(user_id,credits,'realtime_stt',reference,{'window_seconds':MAX_SECONDS})
        token=secrets.token_urlsafe(32)
        try:
            with core.db() as db:
                db.execute('INSERT INTO realtime_sessions VALUES(?,?,?,?,?,?,?)',
                           (reference,hashlib.sha256(token.encode()).hexdigest(),user_id,'issued',now,now+MAX_SECONDS,charge_id))
        except Exception:
            billing.refund(user_id,charge_id,'realtime_issue_failed');raise
    return {'token':token,'websocket_path':'/api/realtime','max_seconds':MAX_SECONDS,
            'credits_used':credits if billing.billing_enabled() else 0,'balance':billing.wallet(user_id)['wallet']['balance']}


def consume(token,user_id):
    ensure_schema()
    with core.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM realtime_sessions WHERE token_hash=? AND user_id=? AND status='issued' AND expires>?",
                       (hashlib.sha256(token.encode()).hexdigest(),user_id,time.time())).fetchone()
        if not row:return None
        db.execute("UPDATE realtime_sessions SET status='connected' WHERE id=?",(row['id'],))
    return dict(row)


def register_routes(app,session,allowed_origins):
    @app.websocket('/api/realtime')
    async def realtime(ws:WebSocket):
        if (ws.headers.get('origin') or '').rstrip('/') not in allowed_origins(ws):
            await ws.close(code=1008);return
        try: user=session(ws)
        except Exception:
            await ws.close(code=1008);return
        token=ws.query_params.get('token','')
        record=consume(token,user['user_id']) if len(token)<=200 else None
        if not record:
            await ws.close(code=1008);return
        await ws.accept()
        forwarded_bytes=0
        tasks=[]
        try:
            upstream='wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime&audio_format=pcm_16000&language_code=mn&commit_strategy=vad'
            async with websockets.connect(upstream,additional_headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY']},open_timeout=20,max_size=256*1024) as provider:
                async def send_audio():
                    nonlocal forwarded_bytes
                    while True:
                        raw=await ws.receive_text()
                        if len(raw)>96000:raise ValueError('Аудио багц хэт том байна.')
                        data=json.loads(raw)
                        if not isinstance(data,dict) or data.get('message_type')!='input_audio_chunk':raise ValueError('Аудио багц буруу байна.')
                        audio=base64.b64decode(data.get('audio_base_64',''),validate=True)
                        if len(audio)>64000 or len(audio)%2:raise ValueError('Аудио өгөгдөл буруу байна.')
                        forwarded_bytes+=len(audio)
                        if forwarded_bytes>MAX_SECONDS*16000*2:raise ValueError('Шууд бичвэрийн 15 минутын эрх дууслаа.')
                        await provider.send(json.dumps({'message_type':'input_audio_chunk','audio_base_64':data.get('audio_base_64',''),
                                                        'commit':bool(data.get('commit',False))}))
                async def receive_text():
                    async for message in provider:
                        await ws.send_text(message if isinstance(message,str) else message.decode())
                tasks=[asyncio.create_task(send_audio()),asyncio.create_task(receive_text())]
                done,_=await asyncio.wait(tasks,timeout=max(0,record['expires']-time.time()),return_when=asyncio.FIRST_COMPLETED)
                for task in done:task.result()
                if not done:await ws.send_json({'message_type':'session_ended','text':'15 минутын эрх дууслаа.'})
        except (WebSocketDisconnect,asyncio.CancelledError):pass
        except Exception:
            try:await ws.send_json({'message_type':'error','error':'Шууд бичвэрийн холболт тасарлаа. Дахин оролдохын өмнө үлдэгдлээ шалгана уу.'})
            except Exception:pass
        finally:
            for task in tasks:task.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
            if not forwarded_bytes:billing.refund(user['user_id'],record['charge_id'],'realtime_no_audio')
            with core.db() as db:db.execute("UPDATE realtime_sessions SET status='completed' WHERE id=?",(record['id'],))
            try:await ws.close()
            except Exception:pass
