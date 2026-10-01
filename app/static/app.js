'use strict';

const $=id=>document.getElementById(id);
const state={user:null,health:null,voices:[],page:'tts',mode:'text',register:false,rt:null,realtimeText:'',billing:null};
let noticeTimer;

function notice(message){
  $('notice').textContent=message;
  $('notice').hidden=false;
  clearTimeout(noticeTimer);
  noticeTimer=setTimeout(()=>$('notice').hidden=true,6500);
}

async function api(path,{method='GET',body=null,form=false}={}){
  const headers={};
  if(state.user&&method!=='GET') headers['X-CSRF-Token']=state.user.csrf;
  let payload=body;
  if(body!==null&&!form){
    headers['Content-Type']='application/json';
    payload=JSON.stringify(body);
  }
  const response=await fetch('/api'+path,{method,headers,body:method==='GET'?undefined:payload});
  let data={};
  const type=response.headers.get('content-type')||'';
  if(type.includes('application/json')){
    try{data=await response.json();}catch{}
  }else if(!response.ok){
    data={error:'Серверийн алдаа гарлаа.'};
  }
  if(!response.ok){
    if(response.status===401){state.user=null;renderAccount();}
    throw new Error(data.detail||data.error||'Үйлдэл амжилтгүй боллоо.');
  }
  return data;
}

function ensureUser(){
  if(state.user) return true;
  openAuth(false);
  return false;
}

function setBusy(button,busy,label){
  if(!button) return;
  if(busy){
    button.dataset.label=button.querySelector('span')?.textContent||button.textContent;
    button.disabled=true;
    button.classList.add('is-generating');
    const span=button.querySelector('span');
    if(span) span.textContent=label||'Боловсруулж байна…';
  }else{
    button.disabled=false;
    button.classList.remove('is-generating');
    const span=button.querySelector('span');
    if(span&&button.dataset.label) span.textContent=button.dataset.label;
  }
}

const pageMeta={
  tts:['01','Create / Text to Speech'],clone:['02','Create / Instant Voice Clone'],pvc:['03','Create / Professional Voice Clone'],
  dialogue:['04','Create / Podcast & Dialogue'],music:['05','Create / Music'],sfx:['06','Create / Sound Effects'],
  stt:['07','Audio / Speech to Text'],realtime:['08','Audio / Realtime STT'],isolator:['09','Audio / Voice Isolator'],
  changer:['10','Audio / Voice Changer · Experimental'],dubbing:['11','Video / Dubbing'],reception:['12','Business AI / Reception.ai'],
  voices:['13','Library / Voices'],billing:['14','Account / Subscription'],analytics:['15','Library / Analytics'],history:['16','Library / History']
};

function page(name){
  state.page=name;
  document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==name);
  document.querySelectorAll('.nav').forEach(el=>el.classList.toggle('active',el.dataset.page===name));
  $('breadcrumb').textContent=pageMeta[name][1];
  document.querySelector('.route-index').textContent=pageMeta[name][0];
  if(name==='voices'){refreshVoices(true);loadProviderStatus();}
  if(name==='reception'){loadReception();loadReceptionEvents();}
  if(name==='billing') loadBilling();
  if(name==='analytics') loadAnalytics();
  if(name==='history') loadHistory();
  window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>page(button.dataset.page));

function renderAccount(){
  $('account').textContent=state.user?state.user.email:'Нэвтрэх';
  $('logout').hidden=!state.user;
  $('register').hidden=!!state.user||!state.health?.registration_open;
  $('auth-toggle').hidden=!state.health?.registration_open;
  $('credit-chip').hidden=!state.user;
}

function openAuth(registerMode=false){
  state.register=!!registerMode&&!!state.health?.registration_open;
  $('auth-title').textContent=state.register?'RAINY-д бүртгүүлэх':'RAINY-д нэвтрэх';
  $('auth-submit').querySelector('span').textContent=state.register?'Бүртгүүлэх':'Нэвтрэх';
  $('auth-toggle').textContent=state.register?'Бүртгэлтэй бол нэвтрэх':'Шинэ бүртгэл үүсгэх';
  $('auth-error').textContent='';
  if(!$('auth-dialog').open)$('auth-dialog').showModal();
}

$('register').onclick=()=>openAuth(true);
$('account').onclick=()=>state.user?notice('Нэвтэрсэн: '+state.user.email):openAuth(false);
$('close-auth').onclick=()=>$('auth-dialog').close();
$('auth-dialog').onclick=e=>{if(e.target===$('auth-dialog')) $('auth-dialog').close();};

$('auth-toggle').onclick=()=>{
  if(!state.health?.registration_open)return;
  state.register=!state.register;
  $('auth-title').textContent=state.register?'RAINY-д бүртгүүлэх':'RAINY-д нэвтрэх';
  $('auth-submit').querySelector('span').textContent=state.register?'Бүртгүүлэх':'Нэвтрэх';
  $('auth-toggle').textContent=state.register?'Бүртгэлтэй бол нэвтрэх':'Шинэ бүртгэл үүсгэх';
};

$('auth-form').onsubmit=async event=>{
  event.preventDefault();
  const button=$('auth-submit');
  setBusy(button,true,'Түр хүлээнэ үү…');
  $('auth-error').textContent='';
  try{
    const result=await api(state.register?'/register':'/login',{method:'POST',body:{email:$('email').value,password:$('password').value}});
    state.user=result.user;
    $('password').value='';
    $('auth-dialog').close();
    renderAccount();
    await refreshVoices();
    await loadBilling(true);
    if(state.page==='voices')await loadProviderStatus();
    notice('RAINY Studio бэлэн.');
  }catch(e){$('auth-error').textContent=e.message;}
  finally{setBusy(button,false);}
};

$('logout').onclick=async()=>{
  try{
    await api('/logout',{method:'POST',body:{}});
    state.user=null;state.billing=null;renderAccount();$('credit-chip').hidden=true;await refreshVoices();notice('Системээс гарлаа.');
  }catch(e){notice(e.message);}
};
$('credit-chip').onclick=()=>page('billing');

function setTheme(theme){
  document.documentElement.dataset.theme=theme;
  localStorage.setItem('rainy-theme',theme);
  $('theme-toggle').textContent=theme==='light'?'☾':'☼';
}
function initTheme(){
  setTheme(localStorage.getItem('rainy-theme')||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'));
}
$('theme-toggle').onclick=()=>setTheme(document.documentElement.dataset.theme==='light'?'dark':'light');

function voiceOptions(select,selected){
  if(!select) return;
  const current=selected||select.value;
  select.replaceChildren();
  state.voices.forEach(voice=>{
    const option=document.createElement('option');
    const multiplier=Number(voice.cost_multiplier||1);
    option.value=voice.id;option.textContent=voice.name+(multiplier>1?' · '+multiplier.toFixed(2).replace(/\.00$/,'')+'× credit':'');
    select.append(option);
  });
  if([...select.options].some(o=>o.value===current)) select.value=current;
}

function renderVoiceSelectors(){
  voiceOptions($('voice'));
  voiceOptions($('changer-voice'));
  document.querySelectorAll('.speaker-voice').forEach(select=>voiceOptions(select,select.dataset.selected));
}

async function refreshVoices(renderLibrary=false){
  try{
    const data=await api('/voices');
    state.voices=data.voices||[];
    renderVoiceSelectors();
    if(renderLibrary||state.page==='voices') renderVoiceLibrary();
  }catch(e){notice(e.message);}
}

function renderVoiceLibrary(){
  const root=$('voice-grid');root.replaceChildren();
  state.voices.forEach(voice=>{
    const card=document.createElement('article');card.className='voice-library-card';
    const top=document.createElement('div');top.className='voice-card-head';
    const avatar=document.createElement('span');avatar.className='voice-letter';avatar.textContent=(voice.name||'V').slice(0,1).toUpperCase();
    const text=document.createElement('div');text.innerHTML='<strong></strong><small></small>';
    text.querySelector('strong').textContent=voice.name;
    text.querySelector('small').textContent=voice.builtin?'Mongolian · ElevenLabs Voice Library':'My clone · ElevenLabs';
    top.append(avatar,text);card.append(top);
    if(voice.builtin){
      const sync=document.createElement('span');
      const multiplier=Number(voice.cost_multiplier||1);
      sync.className='voice-sync-state '+(voice.synced?'ready':'pending');
      sync.textContent=(voice.synced?'Synced':'Direct ID')+(multiplier>1?' · '+multiplier.toFixed(2).replace(/\.00$/,'')+'× credit':'');
      card.append(sync);
    }
    const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src='/api/voices/'+encodeURIComponent(voice.id)+'/preview';card.append(audio);
    if(!voice.builtin&&state.user){
      const remove=document.createElement('button');remove.className='danger-link';remove.textContent='Clone устгах';
      remove.onclick=async()=>{if(!confirm('Энэ clone voice-г ElevenLabs болон RAINY-гаас устгах уу?'))return;try{await api('/voices/'+encodeURIComponent(voice.id),{method:'DELETE',body:{}});await refreshVoices(true);}catch(e){notice(e.message);}};
      card.append(remove);
    }
    root.append(card);
  });
}

function parseGlossary(){
  const glossary={};
  for(const line of $('glossary').value.split('\n').filter(x=>x.trim())){
    const i=line.indexOf('=');
    if(i<1||!line.slice(i+1).trim()) throw new Error('Дуудлагын толь: нэр = дуудлага хэлбэр ашиглана.');
    glossary[line.slice(0,i).trim()]=line.slice(i+1).trim();
  }
  return glossary;
}

function updateCounter(){
  $('counter').textContent=$('text').value.length.toLocaleString('en-US')+' / 12,000';
}
$('text').oninput=updateCounter;
$('example').onclick=()=>{$('text').value='Сайн байна уу. Энэ бол RAINY Voice 2026. OpenAI API болон Монгол хэлний дуу оруулалтыг туршиж байна.';updateCounter();};
$('speed').oninput=()=>$('speed-value').textContent=Number($('speed').value).toFixed(2)+'×';
$('text-tab').onclick=()=>setTtsMode('text');
$('srt-tab').onclick=()=>setTtsMode('srt');
function setTtsMode(mode){
  state.mode=mode;$('text').hidden=mode!=='text';$('srt-panel').hidden=mode!=='srt';
  $('text-tab').classList.toggle('selected',mode==='text');$('srt-tab').classList.toggle('selected',mode==='srt');
}
$('srt-file').onchange=async()=>{const file=$('srt-file').files[0];if(file)$('srt-text').value=await file.text();};

$('generate').onclick=async()=>{
  if(!ensureUser()) return;
  const button=$('generate');setBusy(button,true,'Дуу үүсгэж байна…');
  try{
    const body={title:$('tts-title').value,voice_id:$('voice').value,model_id:$('tts-model').value,speed:Number($('speed').value),glossary:parseGlossary()};
    body[state.mode==='srt'?'srt':'text']=$(state.mode==='srt'?'srt-text':'text').value;
    await api('/jobs',{method:'POST',body});
    notice('TTS дараалалд орлоо. History хэсгээс явцыг харна уу.');
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('clone-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const button=event.currentTarget.querySelector('button[type=submit]');setBusy(button,true,'Clone үүсгэж байна…');
  try{
    const form=new FormData(event.currentTarget);
    if(!event.currentTarget.querySelector('[name=consent]').checked) throw new Error('Хоолой эзэмшигчийн зөвшөөрөл шаардлагатай.');
    form.set('consent','true');
    form.set('remove_background_noise',event.currentTarget.querySelector('[name=remove_background_noise]').checked?'true':'false');
    const result=await api('/voices/clone',{method:'POST',body:form,form:true});
    notice('Voice clone бэлэн: '+result.voice_id);event.currentTarget.reset();await refreshVoices();
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('pvc-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const formEl=event.currentTarget,button=formEl.querySelector('button[type=submit]');
  setBusy(button,true,'PVC sample upload…');
  try{
    if(!formEl.querySelector('[name=ownership]').checked)throw new Error('PVC нь зөвхөн өөрийн хоолойд зориулагдана.');
    const form=new FormData(formEl);
    form.set('language','mn');
    form.set('ownership','true');
    form.set('remove_background_noise',formEl.querySelector('[name=remove_background_noise]').checked?'true':'false');
    const result=await api('/voices/pvc',{method:'POST',body:form,form:true});
    $('pvc-voice-id').value=result.voice_id;
    $('pvc-result').hidden=false;
    $('pvc-result').textContent='PVC draft үүслээ · '+result.voice_id+' · ownership verification шаардлагатай.';
    $('pvc-verify-form').hidden=false;
    notice('Professional Voice Clone draft үүслээ. Verification хийнэ үү.');
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('pvc-captcha-get').onclick=async()=>{
  if(!ensureUser())return;
  const id=$('pvc-voice-id').value.trim();if(!id)return notice('PVC Voice ID алга.');
  try{
    const data=await api('/voices/pvc/'+encodeURIComponent(id)+'/captcha');
    const box=$('pvc-captcha');box.hidden=false;box.replaceChildren();
    const raw=data.captcha||data.image||data.data||'';
    if(typeof raw==='string'&&raw.length>100){
      const img=document.createElement('img');img.className='captcha-image';
      img.alt='ElevenLabs PVC verification CAPTCHA';
      img.src=raw.startsWith('data:')?raw:'data:image/png;base64,'+raw;
      box.append(img);
    }else{
      box.textContent=raw||JSON.stringify(data,null,2);
    }
    notice('Verification CAPTCHA бэлэн. Доторх мөрүүдийг өөрийн хоолойгоор уншаад record хийнэ үү.');
  }catch(e){notice(e.message);}
};

$('pvc-verify').onclick=async()=>{
  if(!ensureUser())return;
  const id=$('pvc-voice-id').value.trim(),file=$('pvc-recording').files[0];
  if(!id||!file)return notice('PVC Voice ID болон verification recording шаардлагатай.');
  const form=new FormData();form.append('recording',file);
  try{
    await api('/voices/pvc/'+encodeURIComponent(id)+'/captcha',{method:'POST',body:form,form:true});
    notice('Ownership verification амжилттай. Training эхлүүлж болно.');
  }catch(e){notice(e.message);}
};

$('pvc-train').onclick=async()=>{
  if(!ensureUser())return;
  const id=$('pvc-voice-id').value.trim();if(!id)return notice('PVC Voice ID алга.');
  const button=$('pvc-train');setBusy(button,true,'Training эхлүүлж байна…');
  try{
    const result=await api('/voices/pvc/'+encodeURIComponent(id)+'/train',{method:'POST',body:{}});
    $('pvc-result').hidden=false;$('pvc-result').textContent='Status: '+(result.status||'training');
    notice('PVC training эхэллээ. Дараа нь Status шалгана уу.');
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('pvc-status').onclick=async()=>{
  if(!ensureUser())return;
  const id=$('pvc-voice-id').value.trim();if(!id)return notice('PVC Voice ID алга.');
  try{
    const result=await api('/voices/pvc/'+encodeURIComponent(id));
    $('pvc-result').hidden=false;$('pvc-result').textContent='Status: '+result.status;
    if(result.status==='ready'){notice('PVC бэлэн. Voice Library-д нэмэгдлээ.');await refreshVoices();}
  }catch(e){notice(e.message);}
};

function addSpeakerRow(text=''){
  const row=document.createElement('div');row.className='speaker-row';
  const select=document.createElement('select');select.className='speaker-voice field-input';voiceOptions(select);
  const textarea=document.createElement('textarea');textarea.placeholder='Speaker-ийн текст…';textarea.value=text;
  const remove=document.createElement('button');remove.type='button';remove.className='speaker-remove';remove.textContent='×';remove.onclick=()=>row.remove();
  row.append(select,textarea,remove);$('dialogue-rows').append(row);
}
$('add-speaker').onclick=()=>addSpeakerRow();
$('dialogue-generate').onclick=async()=>{
  if(!ensureUser())return;
  const rows=[...document.querySelectorAll('.speaker-row')];
  const inputs=rows.map(row=>({voice_id:row.querySelector('select').value,text:row.querySelector('textarea').value.trim()})).filter(x=>x.text);
  const button=$('dialogue-generate');setBusy(button,true,'Podcast үүсгэж байна…');
  try{
    await api('/tools/dialogue',{method:'POST',body:{title:$('dialogue-title').value,language_code:'mn',inputs}});
    notice('Podcast / Dialogue бэлэн. History-д хадгалагдлаа.');loadHistory();
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('music-duration').oninput=()=>$('music-duration-label').textContent=$('music-duration').value+' секунд';
$('sfx-duration').oninput=()=>$('sfx-duration-label').textContent=Number($('sfx-duration').value)===0?'Auto':$('sfx-duration').value+' секунд';
$('sfx-influence').oninput=()=>$('sfx-influence-label').textContent=Number($('sfx-influence').value).toFixed(2);
$('music-generate').onclick=async()=>{
  if(!ensureUser())return;
  const button=$('music-generate');setBusy(button,true,'Music үүсгэж байна…');
  try{
    await api('/tools/music',{method:'POST',body:{title:'RAINY Music',prompt:$('music-prompt').value,music_length_ms:Number($('music-duration').value)*1000,model_id:$('music-model').value,force_instrumental:$('music-instrumental').checked}});
    notice('Music бэлэн. History хэсэгт орлоо.');loadHistory();
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('sfx-generate').onclick=async()=>{
  if(!ensureUser())return;
  const button=$('sfx-generate');setBusy(button,true,'Sound үүсгэж байна…');
  try{
    const duration=Number($('sfx-duration').value);
    await api('/tools/sound-effects',{method:'POST',body:{title:'Sound Effect',text:$('sfx-prompt').value,duration_seconds:duration||null,loop:$('sfx-loop').checked,prompt_influence:Number($('sfx-influence').value)}});
    notice('Sound effect бэлэн.');loadHistory();
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('stt-diarize').onchange=()=>{
  $('stt-speakers').disabled=!$('stt-diarize').checked;
  if(!$('stt-diarize').checked)$('stt-speakers').value='1';
};
$('stt-speakers').disabled=true;

$('stt-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const formEl=event.currentTarget;
  const button=formEl.querySelector('button[type=submit]');setBusy(button,true,'Scribe v2 · Монгол accuracy mode…');
  try{
    const form=new FormData(formEl);
    form.set('polish',formEl.querySelector('[name=polish]').checked?'true':'false');
    form.set('no_verbatim',formEl.querySelector('[name=no_verbatim]').checked?'true':'false');
    form.set('diarize',formEl.querySelector('[name=diarize]').checked?'true':'false');
    form.set('num_speakers',formEl.querySelector('[name=num_speakers]').value||'1');
    const result=await api('/tools/stt',{method:'POST',body:form,form:true});
    $('stt-result').hidden=false;
    const meta=[
      result.polished?'Монгол зөв бичгийн polish ✓':'Raw transcript',
      result.language_code?('Хэл: '+result.language_code):null,
      result.language_probability!=null?('confidence '+Math.round(Number(result.language_probability)*100)+'%'):null,
      result.keyterms_used?('keyterms '+result.keyterms_used):null,
      result.credits_used?('credit '+result.credits_used):null
    ].filter(Boolean).join(' · ');
    $('stt-result').textContent=(meta?meta+'\n\n':'')+(result.text||'Transcript хоосон байна.')+
      (result.edit_error?'\n\nPolish warning: '+result.edit_error:'');
    notice(result.polished?'Монгол transcript засвартайгаар бэлэн боллоо.':'Transcript бэлэн боллоо.');
    loadHistory();loadBilling(true);
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('isolator-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const button=event.currentTarget.querySelector('button[type=submit]');setBusy(button,true,'Voice цэвэрлэж байна…');
  try{
    const result=await api('/tools/voice-isolator',{method:'POST',body:new FormData(event.currentTarget),form:true});
    $('isolator-result').hidden=false;
    $('isolator-result').textContent='Voice Isolator бэлэн · '+result.credits_used+' credits · History-оос татаж авна уу.';
    notice('Шуугиан цэвэрлэсэн voice бэлэн.');loadHistory();loadBilling(true);
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('changer-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const button=event.currentTarget.querySelector('button[type=submit]');setBusy(button,true,'Voice сольж байна…');
  try{
    const form=new FormData(event.currentTarget);
    form.set('remove_background_noise',event.currentTarget.querySelector('[name=remove_background_noise]').checked?'true':'false');
    await api('/tools/voice-changer',{method:'POST',body:form,form:true});
    notice('Voice Changer output бэлэн.');loadHistory();
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

$('dubbing-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const button=event.currentTarget.querySelector('button[type=submit]');setBusy(button,true,'Dubbing project үүсгэж байна…');
  try{
    const result=await api('/tools/dubbing',{method:'POST',body:new FormData(event.currentTarget),form:true});
    $('dubbing-status').hidden=false;$('dubbing-status').textContent='Project: '+result.project_id+' · '+(result.status||'queued');
    notice('Dubbing эхэллээ. Энэ процесс хэдэн минут үргэлжилж болно.');
    pollDubbing(result.job_id);
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
};

async function pollDubbing(jobId){
  let tries=0;
  const tick=async()=>{
    if(++tries>180)return;
    try{
      const data=await api('/tools/dubbing/'+jobId);
      $('dubbing-status').hidden=false;
      const langs=data.result?.languages||[];
      $('dubbing-status').textContent='Status: '+data.status+(langs.length?' · '+langs.map(x=>x.target_language+': '+x.status).join(' · '):'');
      if(data.status==='done'){notice('Dubbing бэлэн. History-оос татаж авна уу.');loadHistory();return;}
      if(data.status==='failed'){notice('Dubbing амжилтгүй боллоо.');return;}
    }catch(e){notice(e.message);return;}
    setTimeout(tick,5000);
  };
  tick();
}

function downsample(input,inputRate,outputRate=16000){
  if(inputRate===outputRate)return input;
  const ratio=inputRate/outputRate;
  const length=Math.round(input.length/ratio);
  const result=new Float32Array(length);
  for(let i=0;i<length;i++){
    const start=Math.floor(i*ratio),end=Math.min(Math.floor((i+1)*ratio),input.length);
    let sum=0,count=0;for(let j=start;j<end;j++){sum+=input[j];count++;}
    result[i]=count?sum/count:0;
  }
  return result;
}
function pcmBase64(float32){
  const buffer=new ArrayBuffer(float32.length*2),view=new DataView(buffer);
  float32.forEach((sample,i)=>{sample=Math.max(-1,Math.min(1,sample));view.setInt16(i*2,sample<0?sample*0x8000:sample*0x7fff,true);});
  const bytes=new Uint8Array(buffer);let binary='';for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
  return btoa(binary);
}
async function startRealtime(){
  if(!ensureUser())return;
  state.realtimeText='';
  $('realtime-transcript').textContent='Сонсож байна…';
  $('realtime-save').disabled=true;
  try{
    const token=(await api('/tools/realtime-token',{method:'POST',body:{}})).token;
    const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
    const ws=new WebSocket('wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime&token='+encodeURIComponent(token)+'&audio_format=pcm_16000&language_code=mn&commit_strategy=vad');
    const rt={ws,stream,ctx:null,source:null,processor:null,committed:'',partial:''};state.rt=rt;
    $('realtime-start').disabled=true;$('realtime-stop').disabled=false;$('realtime-status').textContent='Холбогдож байна…';$('realtime-dot').classList.add('live');
    ws.onopen=()=>{
      const AudioCtx=window.AudioContext||window.webkitAudioContext;
      rt.ctx=new AudioCtx();rt.source=rt.ctx.createMediaStreamSource(stream);rt.processor=rt.ctx.createScriptProcessor(4096,1,1);
      rt.processor.onaudioprocess=e=>{
        if(ws.readyState!==WebSocket.OPEN)return;
        const chunk=downsample(e.inputBuffer.getChannelData(0),rt.ctx.sampleRate,16000);
        ws.send(JSON.stringify({message_type:'input_audio_chunk',audio_base_64:pcmBase64(chunk)}));
      };
      rt.source.connect(rt.processor);rt.processor.connect(rt.ctx.destination);$('realtime-status').textContent='Сонсож байна';
    };
    ws.onmessage=event=>{
      try{
        const msg=JSON.parse(event.data);
        if(msg.message_type==='partial_transcript')rt.partial=msg.text||'';
        if(msg.message_type==='committed_transcript'){rt.committed+=(rt.committed?' ':'')+(msg.text||'');rt.partial='';}
        if(msg.message_type==='edited_transcript'&&msg.edited_text){rt.committed=rt.committed.replace(msg.text||'',msg.edited_text);}
        if(msg.error)notice(msg.error);
        state.realtimeText=(rt.committed+(rt.partial?' '+rt.partial:'')).trim();
        $('realtime-transcript').textContent=state.realtimeText||'Сонсож байна…';
        $('realtime-save').disabled=!state.realtimeText;
      }catch{}
    };
    ws.onerror=()=>notice('Realtime STT холболтын алдаа.');
    ws.onclose=()=>{if(state.rt===rt)stopRealtime(false);};
  }catch(e){notice(e.message);stopRealtime(false);}
}
function stopRealtime(closeSocket=true){
  const rt=state.rt;if(!rt)return;
  if(rt.processor){rt.processor.disconnect();rt.processor.onaudioprocess=null;}
  if(rt.source)rt.source.disconnect();
  if(rt.ctx)rt.ctx.close().catch(()=>{});
  if(rt.stream)rt.stream.getTracks().forEach(t=>t.stop());
  if(closeSocket&&rt.ws&&rt.ws.readyState<2)rt.ws.close();
  state.rt=null;$('realtime-start').disabled=false;$('realtime-stop').disabled=true;$('realtime-status').textContent='Бэлэн';$('realtime-dot').classList.remove('live');
}
$('realtime-start').onclick=startRealtime;
$('realtime-stop').onclick=()=>stopRealtime(true);
$('realtime-save').onclick=async()=>{
  if(!ensureUser()||!state.realtimeText)return;
  const button=$('realtime-save');button.disabled=true;
  try{
    await api('/tools/realtime-save',{method:'POST',body:{title:'Realtime Transcript',text:state.realtimeText}});
    notice('Realtime transcript History-д TXT файлаар хадгалагдлаа.');
    loadHistory();
  }catch(e){notice(e.message);}
  finally{button.disabled=!state.realtimeText;}
};

function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

async function loadProviderStatus(){
  if(!state.user){
    $('provider-plan').textContent='Нэвтэрнэ үү';
    $('provider-status-text').textContent='ElevenLabs workspace-ийн төлөв харахын тулд нэвтэрнэ үү.';
    $('sync-voices').disabled=true;
    return;
  }
  $('sync-voices').disabled=false;
  try{
    const data=await api('/provider/status');
    $('provider-plan').textContent=data.provider_ready?'Voice API бэлэн':'Voice API тохиргоо шаардлагатай';
    if(!data.voice_library_api_available){
      $('provider-status-text').textContent='Voice Library API одоогоор ашиглахад бэлэн биш байна. Админ provider subscription/API тохиргоог шалгана.';
    }else{
      $('provider-status-text').textContent=(data.synced_voice_count||0)+' / '+(data.total_voice_count||12)+' Монгол voice workspace-д sync хийгдсэн · Direct ID мөн дэмжигдэнэ.';
    }
  }catch(e){
    $('provider-plan').textContent='Provider error';
    $('provider-status-text').textContent=e.message;
  }
}
$('sync-voices').onclick=async()=>{
  if(!ensureUser())return;
  const button=$('sync-voices');button.disabled=true;button.textContent='Sync хийж байна…';
  try{
    const data=await api('/voices/sync',{method:'POST',body:{}});
    const ready=data.voices.filter(v=>v.status==='ready').length;
    const failed=data.voices.find(v=>v.status==='failed');
    notice(failed?(ready+' voice бэлэн. '+failed.error):(ready+' voice амжилттай sync хийгдлээ.'));
    await refreshVoices(true);
    await loadProviderStatus();
  }catch(e){notice(e.message);}
  finally{button.disabled=false;button.textContent='Optional sync ↻';}
};

function formatMnt(value){return '₮'+Number(value||0).toLocaleString('en-US');}
function formatCycle(ts){return ts?new Date(Number(ts)*1000).toLocaleDateString('mn-MN'):'—';}

function renderPlans(plans,wireConfigured){
  const root=$('plan-grid');root.replaceChildren();
  plans.filter(plan=>plan.id!=='trial').forEach(plan=>{
    const card=document.createElement('article');card.className='plan-card';
    const top=document.createElement('div');top.className='plan-card-top';
    const name=document.createElement('strong');name.textContent=plan.name;
    const price=document.createElement('span');price.textContent=formatMnt(plan.price_mnt)+'/сар';
    top.append(name,price);
    const credits=document.createElement('h3');credits.textContent=Number(plan.monthly_credits).toLocaleString('en-US')+' credits';
    const desc=document.createElement('p');desc.textContent=plan.description||'';
    const button=document.createElement('button');button.className='generate plan-buy';button.type='button';
    button.innerHTML='<span>Wire.mn-ээр авах</span><span>↗</span>';
    button.disabled=!wireConfigured;
    button.onclick=()=>buyPlan(plan.id,button);
    card.append(top,credits,desc,button);root.append(card);
  });
}

function renderLedger(items){
  const root=$('credit-ledger');root.replaceChildren();
  if(!items?.length){root.innerHTML='<div class="empty">Credit хөдөлгөөн хараахан алга.</div>';return;}
  items.forEach(item=>{
    const row=document.createElement('div');row.className='ledger-row';
    const left=document.createElement('div');
    const title=document.createElement('strong');
    title.textContent=(item.tool_type||item.kind||'credit').replaceAll('_',' ');
    const meta=document.createElement('small');meta.textContent=new Date(item.created*1000).toLocaleString('mn-MN');
    left.append(title,meta);
    const delta=document.createElement('b');delta.className=Number(item.delta)>=0?'credit-plus':'credit-minus';
    delta.textContent=(Number(item.delta)>=0?'+':'')+Number(item.delta).toLocaleString('en-US');
    const balance=document.createElement('span');balance.textContent='→ '+Number(item.balance_after).toLocaleString('en-US');
    const right=document.createElement('div');right.className='ledger-amount';right.append(delta,balance);
    row.append(left,right);root.append(row);
  });
}

async function loadBilling(silent=false){
  try{
    const catalog=await api('/billing/plans');
    if(!state.user){
      state.billing={plans:catalog.plans,wire_configured:catalog.wire_configured};
      $('billing-plan').textContent='Нэвтэрнэ үү';
      $('billing-balance').textContent='0';
      $('billing-cycle').textContent='Subscription авахын тулд нэвтэрнэ үү.';
      renderPlans(catalog.plans,catalog.wire_configured);
      renderLedger([]);
      return;
    }
    const account=await api('/billing/me');
    state.billing={...account,plans:catalog.plans,wire_configured:catalog.wire_configured};
    const wallet=account.wallet||{},sub=account.subscription||{};
    $('billing-plan').textContent=(sub.plan_id||'trial').toUpperCase();
    $('billing-balance').textContent=Number(wallet.balance||0).toLocaleString('en-US');
    $('billing-cycle').textContent='Дуусах: '+formatCycle(sub.cycle_end);
    $('credit-chip').textContent=Number(wallet.balance||0).toLocaleString('en-US')+' credits';
    $('credit-chip').hidden=false;
    renderPlans(catalog.plans,catalog.wire_configured);
    renderLedger(account.ledger||[]);
    if(!catalog.wire_configured&&!silent)notice('Wire.mn API key тохируулаагүй байна.');
  }catch(e){if(!silent)notice(e.message);}
}

async function buyPlan(planId,button){
  if(!ensureUser())return;
  setBusy(button,true,'Wire checkout…');
  try{
    const data=await api('/billing/wire/create',{method:'POST',body:{plan_id:planId}});
    $('payment-status').hidden=false;
    $('payment-status').textContent=formatMnt(data.amount_mnt)+' төлбөр хүлээгдэж байна. Wire.mn checkout нээгдлээ.';
    const popup=window.open(data.pay_url,'_blank','noopener,noreferrer');
    if(!popup)window.location.href=data.pay_url;
    pollWirePayment(data.order_id);
  }catch(e){notice(e.message);}finally{setBusy(button,false);}
}

async function pollWirePayment(orderId){
  let tries=0;
  const tick=async()=>{
    if(++tries>120)return;
    try{
      const data=await api('/billing/wire/status/'+encodeURIComponent(orderId));
      $('payment-status').hidden=false;
      if(data.status==='paid'){
        $('payment-status').textContent='Төлбөр баталгаажлаа. Subscription болон credit идэвхжлээ.';
        notice('Төлбөр амжилттай. Credit нэмэгдлээ.');
        await loadBilling(true);
        return;
      }
      if(data.status==='failed'||data.status==='expired'){
        $('payment-status').textContent='Төлбөр '+data.status+'. Дахин checkout үүсгэнэ үү.';
        return;
      }
      $('payment-status').textContent='Wire.mn төлбөр хүлээгдэж байна…';
    }catch(e){$('payment-status').textContent=e.message;return;}
    setTimeout(tick,3000);
  };
  tick();
}

async function loadReception(){
  if(!ensureUser())return;
  try{
    const data=await api('/reception/config');
    const root=$('reception-tools');root.replaceChildren();
    data.tools.forEach(tool=>{
      const card=document.createElement('article');card.className='reception-tool-card';
      const name=document.createElement('strong');name.textContent=tool.name;
      const desc=document.createElement('p');desc.textContent=tool.description;
      const params=document.createElement('p');
      params.className='reception-param-list';
      params.textContent='Body: '+(tool.parameters||[]).map(x=>x.key+' ('+x.type+(x.required?', required':'')+')').join(', ');
      const url=document.createElement('code');url.textContent=tool.url;
      const copy=document.createElement('button');copy.className='secondary';copy.type='button';copy.textContent='URL copy';
      copy.onclick=async()=>{await navigator.clipboard.writeText(tool.url);notice(tool.name+' URL copy хийлээ.');};
      card.append(name,desc,params,url,copy);root.append(card);
    });
  }catch(e){notice(e.message);}
}
async function loadReceptionEvents(){
  if(!state.user)return;
  try{
    const data=await api('/reception/events'),root=$('reception-events');root.replaceChildren();
    if(!data.items.length){root.innerHTML='<div class="empty">Reception.ai activity хараахан алга.</div>';return;}
    data.items.forEach(item=>{
      const row=document.createElement('div');row.className='ledger-row';
      const left=document.createElement('div');const title=document.createElement('strong');title.textContent=item.tool_name;
      const meta=document.createElement('small');meta.textContent=new Date(item.created*1000).toLocaleString('mn-MN');
      const payload=document.createElement('span');payload.textContent=JSON.stringify(item.payload);payload.className='reception-payload';
      left.append(title,meta,payload);row.append(left);root.append(row);
    });
  }catch(e){notice(e.message);}
}
$('reception-load').onclick=loadReception;
$('reception-refresh').onclick=loadReceptionEvents;
$('reception-rotate').onclick=async()=>{
  if(!ensureUser())return;
  if(!confirm('Reception.ai webhook token солих уу? Хуучин URL-ууд шууд хүчингүй болно.'))return;
  try{await api('/reception/rotate-token',{method:'POST',body:{}});await loadReception();notice('Reception.ai token шинэчлэгдлээ.');}
  catch(e){notice(e.message);}
};

async function loadAnalytics(){
  if(!state.user){$('analytics-content').innerHTML='<div class="empty">Analytics харахын тулд нэвтэрнэ үү.</div>';return;}
  $('analytics-content').innerHTML='<div class="empty">Уншиж байна…</div>';
  try{
    const data=await api('/analytics');
    const sub=data.subscription||{},wallet=data.wallet||{},local=data.local_30d||{};
    const cards=[
      ['Plan',(sub.plan_id||'trial').toUpperCase()],
      ['Credit үлдэгдэл',Number(wallet.balance||0).toLocaleString('en-US')],
      ['30 хоногт ашигласан',Number(data.credits_spent_30d||0).toLocaleString('en-US')],
      ['Cycle дуусах',sub.cycle_end?new Date(sub.cycle_end*1000).toLocaleDateString('mn-MN'):'—']
    ];
    $('analytics-content').innerHTML='<div class="metric-grid">'+cards.map(x=>'<article><small>'+escapeHtml(x[0])+'</small><strong>'+escapeHtml(x[1])+'</strong></article>').join('')+'</div>'+
      '<div class="usage-local"><h3>RAINY · Сүүлийн 30 хоног</h3>'+Object.entries(local).map(([k,v])=>'<span><b>'+escapeHtml(k)+'</b>'+v+'</span>').join('')+'</div>';
  }catch(e){$('analytics-content').innerHTML='<div class="empty">'+escapeHtml(e.message)+'</div>';}
}
$('analytics-refresh').onclick=loadAnalytics;

function renderHistoryItem(item){
  const card=document.createElement('article');card.className='job';card.dataset.status=item.status;
  const head=document.createElement('div');head.className='job-head';
  const left=document.createElement('div');const title=document.createElement('h3');title.textContent=item.title||item.tool_type;
  const meta=document.createElement('p');meta.textContent=(item.tool_type||'tool').replaceAll('_',' ')+' · '+new Date(item.created*1000).toLocaleString('mn-MN');
  left.append(title,meta);const badge=document.createElement('span');badge.className='badge';badge.textContent=item.status;head.append(left,badge);card.append(head);
  if(item.result?.text){const p=document.createElement('p');p.className='result-preview';p.textContent=item.result.text.slice(0,400);card.append(p);}
  if(item.status==='failed'&&item.error){const p=document.createElement('p');p.className='danger-text';p.textContent='Алдаа: '+item.error;card.append(p);}
  const artifacts=item.artifacts||[];
  if(artifacts.length){
    const actions=document.createElement('div');actions.className='artifact-actions';
    artifacts.forEach(art=>{
      if((art.mime||'').startsWith('audio/')||/\.(mp3|wav|flac)$/i.test(art.filename||'')){
        const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src=art.url;card.append(audio);
      }
      if((art.mime||'').startsWith('video/')||/\.mp4$/i.test(art.filename||'')){
        const video=document.createElement('video');video.controls=true;video.preload='metadata';video.src=art.url;video.className='history-video';card.append(video);
      }
      const link=document.createElement('a');link.href=art.url;link.textContent=(art.filename||'Файл')+' ↓';link.download=art.filename||'';actions.append(link);
    });
    card.append(actions);
  }
  return card;
}

async function loadHistory(){
  const root=$('history-list');if(!state.user){root.innerHTML='<div class="empty">History харахын тулд нэвтэрнэ үү.</div>';return;}
  root.innerHTML='<div class="empty">Уншиж байна…</div>';
  try{
    const data=await api('/history');root.replaceChildren();
    if(!data.items.length)root.innerHTML='<div class="empty">Бүтээл хараахан алга.</div>';
    data.items.forEach(item=>root.append(renderHistoryItem(item)));
  }catch(e){root.innerHTML='<div class="empty">'+escapeHtml(e.message)+'</div>';}
}
$('history-refresh').onclick=loadHistory;

async function init(){
  initTheme();
  if(matchMedia('(pointer:fine)').matches)window.addEventListener('pointermove',e=>{document.documentElement.style.setProperty('--mx',e.clientX+'px');document.documentElement.style.setProperty('--my',e.clientY+'px');},{passive:true});
  try{
    const [health,meData]=await Promise.all([api('/health'),api('/me')]);
    state.health=health;state.user=meData.user;renderAccount();
  }catch(e){notice(e.message);}
  await refreshVoices();
  await loadBilling(true);
  if(!$('dialogue-rows').children.length){addSpeakerRow('Сайн байна уу. Өнөөдрийн RAINY podcast эхэлж байна.');addSpeakerRow('Сайн байна уу. Ярилцлагад оролцож байгаадаа баяртай байна.');}
  updateCounter();
  const params=new URLSearchParams(location.search);
  if(params.get('payment')==='success'&&params.get('order')){
    page('billing');
    pollWirePayment(params.get('order'));
    history.replaceState({},'',location.pathname);
  }
}
init();

setInterval(()=>{
  if(document.hidden||!state.user)return;
  if(state.page==='history')loadHistory();
},10000);
