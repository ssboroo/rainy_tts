"""Read-only discovery of public Mongolian and provider default voices."""
import json
import math
import os
import re
import time
from . import core


def read():
    try:
        value=json.loads((core.DATA/'provider-catalog.json').read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def write(value):
    core.DATA.mkdir(parents=True,exist_ok=True)
    temporary=core.DATA/(core.uid()+'.catalog.tmp')
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False))
        temporary.replace(core.DATA/'provider-catalog.json')
    finally:temporary.unlink(missing_ok=True)


def normalize_voice(voice,source):
    vid=str(voice.get('voice_id',''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',vid):return None
    labels=voice.get('labels') or {}
    if not isinstance(labels,dict):labels={}
    language=str(voice.get('language') or labels.get('language') or '').lower()
    verified=voice.get('verified_languages') or []
    native=language in {'mn','mon','mongolian'} or any(str(v.get('language','')).lower() in {'mn','mon','mongolian'} for v in verified if isinstance(v,dict))
    if source=='shared' and (not native or not voice.get('public_owner_id')):return None
    if source=='default' and voice.get('category')!='premade':return None
    try:rate=float(voice.get('rate',1) or 1)
    except (ValueError,TypeError):rate=1
    if not math.isfinite(rate) or rate<1:rate=1
    return {'id':vid,'name':str(voice.get('name') or 'Хоолой')[:100],'builtin':True,
            'source':source,'native_mn':native,'language':language,'cost_multiplier':rate,
            'use_case':str(voice.get('use_case') or labels.get('use_case') or '')[:80],
            'gender':str(voice.get('gender') or labels.get('gender') or '')[:30],
            'tone':str(voice.get('descriptive') or labels.get('descriptive') or '')[:80],
            'requires_paid':source=='shared'}


async def refresh(tools):
    old=read();models=None;shared=None;defaults=None;errors=[]
    if not os.getenv('ELEVENLABS_API_KEY'):return old
    try:
        response=await tools._request('GET','/v1/models',timeout=25)
        models=[]
        for model in response.json():
            if not isinstance(model,dict):continue
            mid=str(model.get('model_id',''))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',mid):continue
            languages=model.get('languages') or []
            models.append({'id':mid,'name':str(model.get('name') or mid)[:100],
                           'supports_mn':any(str(x.get('language_id','')).lower() in {'mn','mon','mongolian'} for x in languages if isinstance(x,dict)),
                           'tts':bool(model.get('can_do_text_to_speech'))})
    except Exception:errors.append('models')
    try:
        shared=[]
        for page in range(3):
            response=await tools._request('GET','/v1/shared-voices',params={'language':'mn','page_size':100,'page':page,'sort':'usage_character_count_1y','include_custom_rates':'true'},timeout=25)
            data=response.json()
            shared.extend(v for raw in data.get('voices',[]) if (v:=normalize_voice(raw,'shared')))
            if not data.get('has_more'):break
    except Exception:shared=None;errors.append('mongolian_voices')
    try:
        defaults=[];token=None
        for page in range(3):
            params={'voice_type':'default','page_size':100,'include_total_count':'false'}
            if token:params['next_page_token']=token
            response=await tools._request('GET','/v2/voices',params=params,timeout=25)
            data=response.json();defaults.extend(v for raw in data.get('voices',[]) if (v:=normalize_voice(raw,'default')))
            token=data.get('next_page_token')
            if not data.get('has_more') or not token:break
    except Exception:defaults=None;errors.append('default_voices')
    voices=[];seen=set()
    for items,source in [(shared,'shared'),(defaults,'default')]:
        candidates=items if items is not None else [v for v in old.get('voices',[]) if v.get('source')==source]
        for voice in candidates[:100]:
            if voice['id'] not in seen:seen.add(voice['id']);voices.append(voice)
    if shared is None and defaults is None:voices=old.get('voices',[])
    value={'voices':voices[:200],'models':models if models is not None else old.get('models',[]),
           'updated':time.time() if shared is not None or defaults is not None or models is not None else old.get('updated'),
           'errors':errors}
    write(value)
    return value
