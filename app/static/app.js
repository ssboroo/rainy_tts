'use strict';

const $=id=>document.getElementById(id);
const state={user:null,health:null,voices:[],page:'tts',mode:'text',register:false,rt:null,realtimeText:'',billing:null};
let noticeTimer;
function customerMessage(message){
  const text=String(message||'Үйлдэл амжилтгүй боллоо.');
  return !state.user?.admin&&/ElevenLabs|API|webhook|FFmpeg|provider|api_key|quota|Wire\.mn/i.test(text)?'Үйлчилгээ түр боломжгүй байна. Дараа дахин оролдох эсвэл тусламж авна уу.':text;
}

function notice(message){
  $('notice').textContent=customerMessage(message);
  $('notice').hidden=false;
  clearTimeout(noticeTimer);
  noticeTimer=setTimeout(()=>$('notice').hidden=true,6500);
}

async function rawApi(path,{method='GET',body=null,form=false}={}){
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
    const detail=data.detail||data.error;
    if(!state.user?.admin&&typeof detail==='string'&&/ElevenLabs|API|webhook|FFmpeg|provider|api_key|quota|Wire\.mn/i.test(detail))throw new Error('Үйлчилгээ түр боломжгүй байна. Дараа дахин оролдох эсвэл тусламж авна уу.');
    throw new Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(x=>x.msg||'Оруулсан утгыг шалгана уу.').join(' · '):detail?.message||'Үйлдэл амжилтгүй боллоо.');
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
 tts:['01','Дуу бүтээх / Текстээс дуу'],clone:['02','Хоолой / Хоолой хувилах'],pvc:['03','Хоолой / Мэргэжлийн хувилбар'],dialogue:['04','Дуу бүтээх / Подкаст'],music:['05','Дуу бүтээх / Хөгжим'],sfx:['06','Дуу бүтээх / Эффект'],stt:['07','Аудио / Ярианаас бичвэр'],realtime:['08','Аудио / Шууд бичвэр'],isolator:['09','Аудио / Яриа цэвэрлэх'],changer:['10','Аудио / Хоолой солих'],dubbing:['11','Видео / Орчуулга'],reception:['12','Бизнес / Reception.ai'],voices:['13','Хоолой / Хоолойн сан'],billing:['14','Миний студи / Сарын багц'],analytics:['15','Миний студи / Хэрэглээ'],history:['16','Миний студи / Бүтээлийн түүх']
};

function page(name){
  if(['admin','reception'].includes(name)&&!state.user?.admin){notice('Энэ хэсэгт нэвтрэх эрхгүй байна.');return;}
  state.page=name;
  document.dispatchEvent(new CustomEvent('rainy:page',{detail:{name}}));
  document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==name);
  document.querySelectorAll('.nav').forEach(el=>el.classList.toggle('active',el.dataset.page===name));
  const meta=pageMeta[name]||['•','Миний студи'];
  $('breadcrumb').textContent=meta[1];
  document.querySelector('.route-index').textContent=meta[0];
  if(name==='voices')refreshVoices(true);
  if(name==='reception'){loadReception();loadReceptionEvents();}
  if(name==='settings')loadSettings();
  if(name==='admin')loadAdmin();
  if(name==='billing') loadBilling();
  if(name==='analytics') loadAnalytics();
  if(name==='history') loadHistory();
  if(toolGuides[name])loadToolResults(name);
  window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>page(button.dataset.page));

function renderAccount(){
  if(!state.user)document.querySelectorAll('.tool-output-items').forEach(el=>{const p=document.createElement('p');p.className='field-help';p.textContent='Нэвтэрсний дараа таны үр дүн энд харагдана.';el.replaceChildren(p);});
  if(!state.user?.admin){
    $('admin-content').replaceChildren();
    $('provider-plan').textContent='';$('provider-status-text').textContent='';$('studio-readiness').textContent='';
    if(['admin','reception'].includes(state.page))page('tts');
  }
  document.querySelectorAll('[data-admin-only]').forEach(el=>el.hidden=!state.user?.admin);
  $('account').textContent=state.user?state.user.email:'Нэвтрэх';
  $('logout').hidden=!state.user;
  document.querySelector('[data-page=admin]').hidden=!state.user?.admin;
  $('register').hidden=!!state.user||!state.health?.registration_open;
  $('auth-toggle').hidden=!state.health?.registration_open;
  $('auth-switch').hidden=!state.health?.registration_open;
  $('admin-test-note').hidden=!state.user?.admin_test;
  $('credit-chip').hidden=!state.user;
}

function openAuth(registerMode=false){
  state.register=!!registerMode&&!!state.health?.registration_open;
  $('auth-title').textContent=state.register?'RAINY-д бүртгүүлэх':'RAINY-д нэвтрэх';
  $('auth-submit').querySelector('span').textContent=state.register?'Бүртгүүлэх':'Нэвтрэх';
  $('auth-toggle').textContent=state.register?'Бүртгэлтэй бол нэвтрэх':'Шинэ бүртгэл үүсгэх';
  $('auth-error').textContent='';
  $('auth-description').textContent=state.register?'Имэйл болон шинэ нууц үгээрээ бүртгэл үүсгэнэ үү.':'Бүртгэлтэй имэйл, нууц үгээрээ нэвтэрнэ үү.';
  $('auth-switch-hint').textContent=state.register?'Бүртгэлтэй юу?':'Бүртгэлгүй юу?';
  $('forgot-password').hidden=state.register;
  $('confirm-password-field').hidden=!state.register;
  $('confirm-password').required=state.register;
  $('confirm-password').value='';
  $('password').value='';
  $('password').autocomplete=state.register?'new-password':'current-password';
  if(!$('auth-dialog').open)$('auth-dialog').showModal();
}

$('register').onclick=()=>openAuth(true);
$('account').onclick=()=>state.user?page('settings'):openAuth(false);
$('close-auth').onclick=()=>$('auth-dialog').close();
$('auth-dialog').onclick=e=>{if(e.target===$('auth-dialog')) $('auth-dialog').close();};

$('auth-toggle').onclick=()=>{if(state.health?.registration_open)openAuth(!state.register);};

$('auth-form').onsubmit=async event=>{
  event.preventDefault();
  const button=$('auth-submit');
  if(button.disabled)return;
  if(state.register&&$('password').value!==$('confirm-password').value){$('auth-error').textContent='Нууц үгүүд таарахгүй байна. Давтан оруулсан нууц үгээ шалгана уу.';return;}
  setBusy(button,true,'Түр хүлээнэ үү…');
  $('auth-error').textContent='';
  try{
    const result=await api(state.register?'/register':'/login',{method:'POST',body:{email:$('email').value,password:$('password').value}});
    state.user=result.user;
    $('password').value='';
    $('auth-dialog').close();
    renderAccount();
    await loadSettings();
    await loadProviderStatus();
    await refreshVoices();
    await loadBilling(true);
    if(state.page==='voices')await loadProviderStatus();
    notice('RAINY Studio бэлэн.');
  }catch(e){$('auth-error').textContent=customerMessage(e.message);}
  finally{setBusy(button,false);}
};

$('logout').onclick=async()=>{
  try{
    await api('/logout',{method:'POST',body:{}});
    state.user=null;state.billing=null;renderAccount();$('credit-chip').hidden=true;await refreshVoices();notice('Системээс гарлаа.');
  }catch(e){notice(customerMessage(e.message));}
};
$('credit-chip').onclick=()=>page('billing');
$('topup-button').onclick=()=>page('billing');

function setTheme(theme){
  document.documentElement.dataset.theme=theme;
  localStorage.setItem('rainy-theme-signal',theme);
  $('theme-toggle').textContent=theme==='light'?'☾':'☼';
}
function initTheme(){
  setTheme(localStorage.getItem('rainy-theme-signal')||'dark');
}
$('theme-toggle').onclick=()=>setTheme(document.documentElement.dataset.theme==='light'?'dark':'light');

function voiceDisplayName(voice){
  if(!voice.builtin)return voice.name;
  const names={Sarnai:'Сарнай',Bolor:'Болор',Bataar:'Баатар',Uyanga:'Уянга',Oyuna:'Оюуна',Temuulen:'Тэмүүлэн',Enkhtuya:'Энхтуяа',Munkhbat:'Мөнхбат',Naran:'Наран',Batbayar:'Батбаяр',Erdene:'Эрдэнэ',Ganbold:'Ганболд'};
  const name=(voice.name||'').split(' - ')[0];return names[name]||name;
}
function voiceOptions(select,selected){
  if(!select) return;
  const current=selected||select.value;
  select.replaceChildren();
  state.voices.forEach(voice=>{
    const option=document.createElement('option');
    const multiplier=Number(voice.cost_multiplier||1);
    option.value=voice.id;option.textContent=voiceDisplayName(voice)+(multiplier>1?' · '+multiplier.toFixed(2).replace(/\.00$/,'')+'× кредит':'');
    select.append(option);
  });
  if([...select.options].some(o=>o.value===current)) select.value=current;
}

function renderVoiceSelectors(){
  voiceOptions($('voice'));
  voiceOptions($('changer-voice'));
  voiceOptions($('remix-voice'));
  if($('remix-voice'))[...$('remix-voice').options].forEach(o=>{if(state.voices.find(v=>v.id===o.value)?.builtin)o.remove();});
  document.querySelectorAll('.speaker-voice').forEach(select=>voiceOptions(select,select.dataset.selected));
}

async function refreshVoices(renderLibrary=false){
  try{
    const data=await api('/voices');
    state.voices=data.voices||[];
    renderVoiceSelectors();
    if(renderLibrary||state.page==='voices') renderVoiceLibrary();
  }catch(e){notice(customerMessage(e.message));}
}

function voiceAvatar(voice){
  const name=(voice.name||'').split(' - ')[0];
  const names=['Sarnai','Bolor','Bataar','Uyanga','Oyuna','Temuulen','Enkhtuya','Munkhbat','Naran','Batbayar','Erdene','Ganbold'];
  let index=names.indexOf(name);if(index<0)index=[...(voice.id||'voice')].reduce((n,c)=>n+c.charCodeAt(0),0)%12;
  const longHair=['Sarnai','Bolor','Uyanga','Oyuna','Enkhtuya','Naran'].includes(name);
  const colors=['#dce9dd','#e9e0f2','#dbe4f0','#f5e3db','#e4e1ef','#dcebe8','#f3e8cf','#dde8ec','#e8dfd8','#e2e6f4','#f0e0d9','#dfe8d3'];
  const shirts=['#537766','#806692','#536b8c','#ad746b','#706789','#497c79','#978154','#536c79','#936d66','#58648c','#94644c','#617853'];
  const hair=['#24202b','#3b2526','#20252e','#352a26'][index%4];
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="24" fill="${colors[index]}"/><circle cx="80" cy="18" r="25" fill="white" opacity=".35"/>${longHair?`<path d="M25 80V43c0-38 50-38 50 0v37Z" fill="${hair}"/>`:''}<path d="M13 100c0-34 74-34 74 0" fill="${shirts[index]}"/><path d="M42 62h16v16q-8 12-16 0" fill="#dba885"/><ellipse cx="50" cy="45" rx="23" ry="28" fill="#e8bd99"/><path d="M27 44V33q0-22 23-22t23 22v8q-17-3-23-16-8 15-23 19" fill="${hair}"/><path d="M35 43h9m12 0h9" stroke="${hair}" stroke-width="2.5" stroke-linecap="round"/><circle cx="40" cy="49" r="2" fill="#292934"/><circle cx="60" cy="49" r="2" fill="#292934"/><path d="M49 50l-2 8h5" stroke="#bd8e75" stroke-width="1.7" fill="none"/><path d="M43 64q7 5 14 0" stroke="#a46764" stroke-width="2" fill="none" stroke-linecap="round"/>${index%3===0?'<path d="M33 78l17 13 17-13" stroke="#f6f5ec" stroke-width="3" fill="none"/>':''}</svg>`;
  return 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);
}
function selectVoice(voice){
  page('tts');$('voice').value=voice.id;updateEstimate();
  notice(voiceDisplayName(voice)+' хоолой сонгогдлоо. Бичвэрээ оруулаад “Дуу үүсгэх” дарна уу.');
  $(state.mode==='srt'?'srt-text':'text').focus();
}
function renderVoiceLibrary(){
  const root=$('voice-grid');[...root.children].forEach(card=>card.releasePreview?.());root.replaceChildren();
  const filter=$('voice-filter')?.value||'native';const query=($('voice-search')?.value||'').trim().toLowerCase();
  const visible=state.voices.filter(v=>(filter==='all'||filter==='native'&&v.builtin&&v.native_mn!==false||filter==='default'&&v.source==='default'||filter==='mine'&&!v.builtin)&&voiceDisplayName(v).toLowerCase().includes(query));
  if($('voice-count'))$('voice-count').textContent=visible.length+' хоолой · Дээжийг сонсож, өөрийн бичвэрт тохирохыг сонгоно уу.';
  visible.forEach(voice=>{
    const card=document.createElement('article');card.className='voice-library-card';
    const top=document.createElement('div');top.className='voice-card-head';
    const avatar=document.createElement('img');avatar.className='voice-avatar';avatar.src=voiceAvatar(voice);avatar.alt=voiceDisplayName(voice)+' хоолойн аватар';avatar.width=64;avatar.height=64;
    const text=document.createElement('div');text.innerHTML='<strong></strong><small></small>';
    text.querySelector('strong').textContent=voiceDisplayName(voice);
    text.querySelector('small').textContent=!voice.builtin?'Миний хоолой':voice.native_mn===false?'Үндсэн хоолой · дуудлагыг шалгана':'Монгол хэлээр сурсан';
    top.append(avatar,text);card.append(top);
    const details=document.createElement('p');details.className='field-help';details.textContent=voice.requires_paid?'Төлбөртэй үйлчилгээний багцаар ашиглана.':'Ашиглах боломж нь үйлчилгээний эрхээс хамаарна.';card.append(details);
    const actions=document.createElement('div');actions.className='voice-actions';
    const use=document.createElement('button');use.type='button';use.className='secondary voice-use';use.textContent='Энэ хоолойг ашиглах';use.onclick=()=>selectVoice(voice);
    const listen=document.createElement('button');listen.type='button';listen.className='secondary voice-listen';listen.textContent='Дээж сонсох';
    const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.hidden=true;
    const feedback=document.createElement('p');feedback.className='field-help';feedback.setAttribute('role','status');feedback.hidden=true;
    let previewUrl;
    listen.onclick=async()=>{
      if(listen.disabled)return;listen.disabled=true;listen.textContent='Дээж ачаалж байна…';feedback.hidden=true;
      try{
        if(!previewUrl){
          const response=await fetch('/api/voices/'+encodeURIComponent(voice.id)+'/preview');
          if(!response.ok||!(response.headers.get('content-type')||'').startsWith('audio/'))throw new Error('Дээж одоогоор сонсох боломжгүй байна. Хоолойг сонгож өөрийн бичвэрээр ашиглаж болно.');
          const blob=await response.blob();if(!blob.size)throw new Error('Дээж хоосон байна. Дараа дахин оролдоно уу.');
          if(!card.isConnected)return;
          previewUrl=URL.createObjectURL(blob);audio.src=previewUrl;
        }
        audio.hidden=false;await audio.play();
      }catch(e){feedback.textContent=customerMessage(e.message);feedback.hidden=false;}
      finally{listen.disabled=false;listen.textContent='Дээж сонсох';}
    };
    audio.onerror=()=>{feedback.textContent='Дээжийг тоглуулах боломжгүй байна. Дараа дахин оролдоно уу.';feedback.hidden=false;audio.hidden=true;};
    actions.append(use,listen);card.append(actions,audio,feedback);
    card.releasePreview=()=>{audio.pause();if(previewUrl)URL.revokeObjectURL(previewUrl);};
    if(!voice.builtin&&state.user){
      const remove=document.createElement('button');remove.className='danger-link';remove.textContent='Хоолой устгах';
      remove.onclick=async()=>{if(!confirm('Энэ хоолойн хувилбарыг устгах уу?'))return;try{await api('/voices/'+encodeURIComponent(voice.id),{method:'DELETE',body:{}});await refreshVoices(true);}catch(e){notice(customerMessage(e.message));}};
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
$('example').onclick=()=>{$('text').value='Сайн байна уу. RAINY студид тавтай морил. Та өөрийн бичвэрийг байгалийн дуу хоолойтой бүтээл болгоорой.';updateCounter();};
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
    const body={title:$('tts-title').value,voice_id:$('voice').value,model_id:$('tts-model').value,emotion:$('tts-emotion').value,speed:Number($('speed').value),glossary:parseGlossary()};
    body[state.mode==='srt'?'srt':'text']=$(state.mode==='srt'?'srt-text':'text').value;
    await api('/jobs',{method:'POST',body});
    notice('TTS дараалалд орлоо. Бүтээлийн түүх хэсгээс явцыг харна уу.');
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('clone-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const formEl=event.currentTarget,button=formEl.querySelector('button[type=submit]');setBusy(button,true,'Хувилбар үүсгэж байна…');
  try{
    const form=new FormData(event.currentTarget);
    if(!event.currentTarget.querySelector('[name=consent]').checked) throw new Error('Хоолой эзэмшигчийн зөвшөөрөл шаардлагатай.');
    form.set('consent','true');
    form.set('remove_background_noise',event.currentTarget.querySelector('[name=remove_background_noise]').checked?'true':'false');
    const result=await api('/voices/clone',{method:'POST',body:form,form:true});
    notice('Хоолойн хувилбар бэлэн: '+result.voice_id);formEl.reset();await refreshVoices();
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('pvc-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const formEl=event.currentTarget,button=formEl.querySelector('button[type=submit]');
  setBusy(button,true,'Хоолойн дээж байршуулж байна…');
  try{
    if(!formEl.querySelector('[name=ownership]').checked)throw new Error('Энэ боломж нь зөвхөн өөрийн хоолойд зориулагдана.');
    const form=new FormData(formEl);
    form.set('language','mn');
    form.set('ownership','true');
    form.set('remove_background_noise',formEl.querySelector('[name=remove_background_noise]').checked?'true':'false');
    const result=await api('/voices/pvc',{method:'POST',body:form,form:true});
    $('pvc-voice-id').value=result.voice_id;
    $('pvc-result').hidden=false;
    $('pvc-result').textContent='Хоолойн ноорог үүслээ. Доорх заавраар өөрийн хоолойг баталгаажуулна уу.';
    $('pvc-verify-form').hidden=false;
    notice('Professional Хоолой Хувилбар ноорог үүслээ. Баталгаажуулалт хийнэ үү.');
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('pvc-captcha-get').onclick=async()=>{
  if(!ensureUser())return;
  const id=$('pvc-voice-id').value.trim();if(!id)return notice('Эхлээд хоолойн ноорог үүсгэнэ үү.');
  try{
    const data=await api('/voices/pvc/'+encodeURIComponent(id)+'/captcha');
    const box=$('pvc-captcha');box.hidden=false;box.replaceChildren();
    const raw=data.captcha||data.image||data.data||'';
    if(typeof raw==='string'&&(raw.startsWith('data:image/')||(raw.length>100&&/^[A-Za-z0-9+/=\s]+$/.test(raw)))){
      const img=document.createElement('img');img.className='captcha-image';
      img.alt='Хоолойн эзэмшигчийг баталгаажуулах зураг';
      img.src=raw.startsWith('data:')?raw:'data:image/png;base64,'+raw;
      box.append(img);
    }else{
      box.textContent=typeof raw==='string'&&raw?raw:state.user?.admin?JSON.stringify(data,null,2):'Баталгаажуулах мэдээлэл ирсэнгүй. Дахин оролдоно уу.';
    }
    notice('Баталгаажуулах өгүүлбэрийг өөрийн хоолойгоор уншиж, бичлэгээ оруулна уу.');
  }catch(e){notice(customerMessage(e.message));}
};

$('pvc-verify').onclick=async()=>{
  if(!ensureUser())return;
  const id=$('pvc-voice-id').value.trim(),file=$('pvc-recording').files[0];
  if(!id||!file)return notice('Хоолойн ноорог үүсгээд баталгаажуулах бичлэгээ оруулна уу.');
  const form=new FormData();form.append('recording',file);
  try{
    await api('/voices/pvc/'+encodeURIComponent(id)+'/captcha',{method:'POST',body:form,form:true});
    notice('Ownership баталгаажуулалт амжилттай. Сургалт эхлүүлж болно.');
  }catch(e){notice(customerMessage(e.message));}
};

$('pvc-train').onclick=async()=>{
  if(!ensureUser())return;
  const id=$('pvc-voice-id').value.trim();if(!id)return notice('Эхлээд хоолойн ноорог үүсгэнэ үү.');
  const button=$('pvc-train');setBusy(button,true,'Сургалт эхлүүлж байна…');
  try{
    const result=await api('/voices/pvc/'+encodeURIComponent(id)+'/train',{method:'POST',body:{}});
    $('pvc-result').hidden=false;$('pvc-result').textContent='Төлөв: '+statusLabel(result.status||'training');
    notice('Хоолой боловсруулах ажил эхэллээ. Дараа нь Төлөв шалгана уу.');
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('pvc-status').onclick=async()=>{
  if(!ensureUser())return;
  const id=$('pvc-voice-id').value.trim();if(!id)return notice('Эхлээд хоолойн ноорог үүсгэнэ үү.');
  try{
    const result=await api('/voices/pvc/'+encodeURIComponent(id));
    $('pvc-result').hidden=false;$('pvc-result').textContent='Төлөв: '+statusLabel(result.status);
    if(result.status==='ready'){notice('Хоолой бэлэн. Хоолойн санд нэмэгдлээ.');await refreshVoices();}
  }catch(e){notice(customerMessage(e.message));}
};

function addSpeakerRow(text=''){
  const row=document.createElement('div');row.className='speaker-row';
  const select=document.createElement('select');select.className='speaker-voice field-input';select.setAttribute('aria-label','Яригчийн хоолой');voiceOptions(select);
  const textarea=document.createElement('textarea');textarea.placeholder='Яригчийн бичвэр…';textarea.setAttribute('aria-label','Яригчийн бичвэр');textarea.value=text;
  const emotion=document.createElement('select');emotion.className='speaker-emotion field-input';emotion.setAttribute('aria-label','Яригчийн сэтгэл хөдлөл');
  for(const option of $('tts-emotion').options)emotion.append(option.cloneNode(true));
  const directions=document.createElement('div');directions.className='speaker-directions';directions.append(select,emotion);
  const remove=document.createElement('button');remove.type='button';remove.className='speaker-remove';remove.textContent='×';remove.setAttribute('aria-label','Яригчийг хасах');remove.onclick=()=>row.remove();
  row.append(directions,textarea,remove);$('dialogue-rows').append(row);
}
$('add-speaker').onclick=()=>addSpeakerRow();
$('dialogue-generate').onclick=async()=>{
  if(!ensureUser())return;
  const rows=[...document.querySelectorAll('.speaker-row')];
  const inputs=rows.map(row=>({voice_id:row.querySelector('.speaker-voice').value,emotion:row.querySelector('.speaker-emotion').value,text:row.querySelector('textarea').value.trim()})).filter(x=>x.text);
  const button=$('dialogue-generate');setBusy(button,true,'Подкаст үүсгэж байна…');
  try{
    await api('/tools/dialogue',{method:'POST',body:{title:$('dialogue-title').value,language_code:'mn',inputs}});
    notice('Подкаст / Харилцан яриа бэлэн. Бүтээлийн түүхэд хадгалагдлаа.');loadHistory();
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('music-duration').oninput=()=>$('music-duration-label').textContent=$('music-duration').value+' секунд';
$('sfx-duration').oninput=()=>$('sfx-duration-label').textContent=Number($('sfx-duration').value)===0?'Автомат':$('sfx-duration').value+' секунд';
$('sfx-influence').oninput=()=>$('sfx-influence-label').textContent=Number($('sfx-influence').value).toFixed(2);
$('music-generate').onclick=async()=>{
  if(!ensureUser())return;
  const button=$('music-generate');setBusy(button,true,'Хөгжим үүсгэж байна…');
  try{
    await api('/tools/music',{method:'POST',body:{title:'RAINY Хөгжим',prompt:$('music-prompt').value,music_length_ms:Number($('music-duration').value)*1000,model_id:$('music-model').value,force_instrumental:$('music-instrumental').checked}});
    notice('Хөгжим бэлэн. Бүтээлийн түүх хэсэгт орлоо.');loadHistory();
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('sfx-generate').onclick=async()=>{
  if(!ensureUser())return;
  const button=$('sfx-generate');setBusy(button,true,'Эффект үүсгэж байна…');
  try{
    const duration=Number($('sfx-duration').value);
    await api('/tools/sound-effects',{method:'POST',body:{title:'Дууны эффект',text:$('sfx-prompt').value,duration_seconds:duration||null,loop:$('sfx-loop').checked,prompt_influence:Number($('sfx-influence').value)}});
    notice('Дууны эффект бэлэн.');loadHistory();
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('stt-diarize').onchange=()=>{
  $('stt-speakers').disabled=!$('stt-diarize').checked;
  if(!$('stt-diarize').checked)$('stt-speakers').value='1';
};
$('stt-speakers').disabled=true;

$('stt-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const formEl=event.currentTarget;
  const button=formEl.querySelector('button[type=submit]');setBusy(button,true,'Яриаг бичвэр болгож байна…');
  try{
    const form=new FormData(formEl);
    form.set('polish',formEl.querySelector('[name=polish]').checked?'true':'false');
    form.set('no_verbatim',formEl.querySelector('[name=no_verbatim]').checked?'true':'false');
    form.set('diarize',formEl.querySelector('[name=diarize]').checked?'true':'false');
    form.set('num_speakers',formEl.querySelector('[name=num_speakers]').value||'1');
    const result=await api('/tools/stt',{method:'POST',body:form,form:true});
    $('stt-result').hidden=false;
    const meta=[
      result.polished?'Монгол зөв бичгийн засвар ✓':'Эх бичвэр',
      result.language_code?('Хэл: '+result.language_code):null,
      result.language_probability!=null?('Итгэлцэл '+Math.round(Number(result.language_probability)*100)+'%'):null,
      result.keyterms_used?('нэр томьёоs '+result.keyterms_used):null,
      result.credits_used?('кредит '+result.credits_used):null
    ].filter(Boolean).join(' · ');
    $('stt-result').textContent=(meta?meta+'\n\n':'')+(result.text||'Бичвэр хоосон байна.')+
      (result.edit_error?'\n\nЗөв бичгийн засварын анхааруулга: '+result.edit_error:'');
    notice(result.polished?'Монгол бичвэр засвартайгаар бэлэн боллоо.':'Бичвэр бэлэн боллоо.');
    loadHistory();loadBilling(true);
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('isolator-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const button=event.currentTarget.querySelector('button[type=submit]');setBusy(button,true,'Хоолой цэвэрлэж байна…');
  try{
    const result=await api('/tools/voice-isolator',{method:'POST',body:new FormData(event.currentTarget),form:true});
    $('isolator-result').hidden=false;
    $('isolator-result').textContent='Яриа цэвэрлэх бэлэн · '+result.credits_used+' кредит · Бүтээлийн түүхээс татаж авна уу.';
    notice('Шуугиан цэвэрлэсэн хоолой бэлэн.');loadHistory();loadBilling(true);
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('changer-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const button=event.currentTarget.querySelector('button[type=submit]');setBusy(button,true,'Хоолой сольж байна…');
  try{
    const form=new FormData(event.currentTarget);
    form.set('remove_background_noise',event.currentTarget.querySelector('[name=remove_background_noise]').checked?'true':'false');
    await api('/tools/voice-changer',{method:'POST',body:form,form:true});
    notice('Хоолой Changer гаралт бэлэн.');loadHistory();
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

$('dubbing-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const button=event.currentTarget.querySelector('button[type=submit]');setBusy(button,true,'Dubbing төсөл үүсгэж байна…');
  try{
    const result=await api('/tools/dubbing',{method:'POST',body:new FormData(event.currentTarget),form:true});
    $('dubbing-status').hidden=false;$('dubbing-status').textContent='Төсөл: '+result.project_id+' · '+(result.status||'queued');
    notice('Dubbing эхэллээ. Энэ процесс хэдэн минут үргэлжилж болно.');
    pollDubbing(result.job_id);
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};

async function pollDubbing(jobId){
  let tries=0;
  const tick=async()=>{
    if(++tries>180)return;
    try{
      const data=await api('/tools/dubbing/'+jobId);
      $('dubbing-status').hidden=false;
      const langs=data.result?.languages||[];
      $('dubbing-status').textContent='Төлөв: '+statusLabel(data.status)+(langs.length?' · '+langs.map(x=>x.target_language+': '+x.status).join(' · '):'');
      if(data.status==='done'){notice('Видео орчуулга бэлэн. Доорх үр дүнгээс татаж авна уу.');loadToolResults('dubbing');return;}
      if(data.status==='failed'){notice('Видео орчуулга амжилтгүй боллоо.');loadToolResults('dubbing');return;}
    }catch(e){notice(customerMessage(e.message));return;}
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
  if(!ensureUser()||$('realtime-start').disabled)return;
  $('realtime-start').disabled=true;
  state.realtimeText='';
  $('realtime-transcript').textContent='Сонсож байна…';
  $('realtime-save').disabled=true;
  let stream;
  try{
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
    const authorization=await api('/tools/realtime-token',{method:'POST',body:{}});
    const token=authorization.token;
    const ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+authorization.websocket_path+'?token='+encodeURIComponent(token));
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
    ws.onerror=()=>notice('Шууд бичвэр холболтын алдаа.');
    ws.onclose=()=>{if(state.rt===rt)stopRealtime(false);};
  }catch(e){stream?.getTracks().forEach(track=>track.stop());notice(e.name==='NotAllowedError'?'Микрофон ашиглах зөвшөөрөл олгоно уу.':customerMessage(e.message));stopRealtime(true);$('realtime-start').disabled=false;}
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
    await api('/tools/realtime-save',{method:'POST',body:{title:'Шууд Бичвэр',text:state.realtimeText}});
    notice('Шууд бичвэр Бүтээлийн түүхэд TXT файлаар хадгалагдлаа.');
    loadHistory();
  }catch(e){notice(customerMessage(e.message));}
  finally{button.disabled=!state.realtimeText;}
};

function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

async function loadProviderStatus(){
  if(!state.user?.admin){
    $('provider-plan').textContent='Нэвтэрнэ үү';
    $('provider-status-text').textContent='ElevenLabs ажлын орчны төлөв харахын тулд нэвтэрнэ үү.';
    $('sync-voices').disabled=true;
    return;
  }
  $('sync-voices').disabled=false;
  try{
    const data=await api('/provider/status');
    if(!state.user?.admin)return;
    $('studio-readiness').textContent=(state.health?.engine_ready?'Холболт тохируулсан':'Холболт шаардлагатай')+' · '+(data.provider_ready?'ElevenLabs төлбөртэй багцын эрх идэвхтэй.':'ElevenLabs төлбөртэй багцын эрх шаардлагатай. Нийтийн хоолой ашиглах боломжгүй.');
    $('provider-plan').textContent=data.provider_ready?'Төлбөртэй үйлчилгээний эрх идэвхтэй':'Төлбөртэй үйлчилгээний эрх шаардлагатай';
    if(!data.voice_library_api_available){
      $('provider-status-text').textContent='Хоолойн сан API одоогоор ашиглахад бэлэн биш байна. Админ үйлчилгээний багц болон холболтыг шалгана.';
    }else{
      $('provider-status-text').textContent=(data.synced_voice_count||0)+' / '+(data.total_voice_count||12)+' Монгол хоолой санд хадгалагдсан · Шууд ашиглах боломжтой.';
    }
  }catch(e){
    $('studio-readiness').textContent='Үйлчилгээний эрхийг шалгаж чадсангүй · '+customerMessage(e.message);
    $('provider-plan').textContent='Үйлчилгээний алдаа';
    $('provider-status-text').textContent=customerMessage(e.message);
  }
}
$('sync-voices').onclick=async()=>{
  if(!ensureUser())return;
  const button=$('sync-voices');button.disabled=true;button.textContent='Сан шинэчилж байна…';
  try{
    const data=await api('/voices/sync',{method:'POST',body:{}});
    const ready=data.voices.filter(v=>v.status==='ready').length;
    const failed=data.voices.find(v=>v.status==='failed');
    notice(failed?(ready+' хоолой бэлэн. '+failed.error):(ready+' хоолой шинэчлэгдлээ.'));
    await refreshVoices(true);
    await loadProviderStatus();
  }catch(e){notice(customerMessage(e.message));}
  finally{button.disabled=false;button.textContent='Хоолой шинэчлэх ↻';}
};

function formatMnt(value){return '₮'+Number(value||0).toLocaleString('en-US');}
function formatCycle(ts){return ts?new Date(Number(ts)*1000).toLocaleDateString('mn-MN'):'—';}

function customerPlanName(id,fallback){return ({trial:'Үнэгүй',hobby:'Сонирхогч',starter:'Эхлэх',creator:'Контент бүтээгч',pro:'Мэргэжлийн',studio:'Студи',agency:'Байгууллага'})[id]||fallback||id;}
function renderPlans(plans,wireConfigured){
  const root=$('plan-grid');root.replaceChildren();
  const paidPlans=plans.filter(p=>p.id!=='trial'&&Number(p.price_mnt)>0);
  $('billing-start-price').textContent=paidPlans.length?'Сарын багц '+formatMnt(Math.min(...paidPlans.map(p=>Number(p.price_mnt))))+'-өөс эхэлнэ.':'Сарын багц одоогоор авах боломжгүй байна.';
  plans.filter(plan=>plan.id!=='trial').forEach(plan=>{
    const card=document.createElement('article');card.className='plan-card';
    const top=document.createElement('div');top.className='plan-card-top';
    const name=document.createElement('strong');name.textContent=customerPlanName(plan.id,plan.name);
    const price=document.createElement('span');price.textContent=formatMnt(plan.price_mnt)+'/сар';
    top.append(name,price);
    const credits=document.createElement('h3');credits.textContent=Number(plan.monthly_credits).toLocaleString('en-US')+' кредит';
    const desc=document.createElement('p');desc.textContent=plan.description||'';
    const button=document.createElement('button');button.className='generate plan-buy';button.type='button';
    button.innerHTML='<span>Кредит цэнэглэх</span><span>↗</span>';
    button.disabled=!wireConfigured;
    if(!wireConfigured){button.querySelector('span').textContent='Тун удахгүй';button.title='Төлбөр авах боломж түр хаалттай';}
    button.onclick=()=>buyPlan(plan.id,button,plan);
    card.append(top,credits,desc,button);root.append(card);
  });
}

function renderLedger(items){
  const root=$('credit-ledger');root.replaceChildren();
  if(!items?.length){root.innerHTML='<div class="empty">Кредитийн хөдөлгөөн хараахан алга.</div>';return;}
  items.forEach(item=>{
    const row=document.createElement('div');row.className='ledger-row';
    const left=document.createElement('div');
    const title=document.createElement('strong');
    title.textContent=toolLabel(item.tool_type||item.kind||'credit');
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
      $('billing-cycle').textContent='Сарын багц авахын тулд нэвтэрнэ үү.';
      renderPlans(catalog.plans,catalog.wire_configured);
      renderLedger([]);
      return;
    }
    const account=await api('/billing/me');
    state.billing={...account,plans:catalog.plans,wire_configured:catalog.wire_configured};
    const wallet=account.wallet||{},sub=account.subscription||{};
    $('billing-plan').textContent=customerPlanName(sub.plan_id||'trial');
    $('billing-balance').textContent=Number(wallet.balance||0).toLocaleString('en-US');
    $('billing-cycle').textContent='Дуусах: '+formatCycle(sub.cycle_end);
    $('credit-chip').textContent=state.user?.admin_test?'Админ туршилт':Number(wallet.balance||0).toLocaleString('en-US')+' кредит · Үлдэгдэл';
    $('credit-chip').hidden=false;
    renderPlans(catalog.plans,catalog.wire_configured);
    renderLedger(account.ledger||[]);
    if(!catalog.wire_configured&&!silent)notice('Төлбөр авах боломж түр хаалттай байна. Дараа дахин оролдоно уу.');
  }catch(e){if(!silent)notice(customerMessage(e.message));}
}

async function buyPlan(planId,button,plan){
  if(!ensureUser())return;
  setBusy(button,true,'Төлбөр бэлтгэж байна…');
  try{
    const data=await api('/billing/wire/create',{method:'POST',body:{plan_id:planId,expected_amount_mnt:plan.price_mnt,expected_credits:plan.monthly_credits}});
    $('payment-status').hidden=false;
    $('payment-status').textContent=formatMnt(data.amount_mnt)+' төлбөр хүлээгдэж байна. QPay төлбөрийн хуудас нээгдлээ.';
    const popup=window.open(data.pay_url,'_blank','noopener,noreferrer');
    if(!popup)window.location.href=data.pay_url;
    pollWirePayment(data.order_id);
  }catch(e){await loadBilling(true);notice(customerMessage(e.message));}finally{setBusy(button,false);}
}

async function pollWirePayment(orderId){
  let tries=0;
  const tick=async()=>{
    if(++tries>120)return;
    try{
      const data=await api('/billing/wire/status/'+encodeURIComponent(orderId));
      $('payment-status').hidden=false;
      if(data.status==='paid'){
        $('payment-status').textContent='Төлбөр баталгаажлаа. Сарын багц болон кредит идэвхжлээ.';
        notice('Төлбөр амжилттай. Кредит нэмэгдлээ.');
        await loadBilling(true);
        return;
      }
      if(data.status==='failed'||data.status==='expired'){
        $('payment-status').textContent='Төлбөр '+statusLabel(data.status)+'. Шинэ төлбөрийн хүсэлт үүсгэнэ үү.';
        return;
      }
      $('payment-status').textContent='QPay төлбөр хүлээгдэж байна…';
    }catch(e){$('payment-status').textContent=customerMessage(e.message);return;}
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
      params.textContent='Оруулах талбар: '+(tool.parameters||[]).map(x=>x.key+' ('+x.type+(x.required?', шаардлагатай':'')+')').join(', ');
      const url=document.createElement('code');url.textContent=tool.url;
      const copy=document.createElement('button');copy.className='secondary';copy.type='button';copy.textContent='Хаяг хуулах';
      copy.onclick=async()=>{await navigator.clipboard.writeText(tool.url);notice(tool.name+' Хаяг хуулах хийлээ.');};
      card.append(name,desc,params,url,copy);root.append(card);
    });
  }catch(e){notice(customerMessage(e.message));}
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
  }catch(e){notice(customerMessage(e.message));}
}
$('reception-load').onclick=loadReception;
$('reception-refresh').onclick=loadReceptionEvents;
$('reception-rotate').onclick=async()=>{
  if(!ensureUser())return;
  if(!confirm('Reception.ai webhook token солих уу? Хуучин URL-ууд шууд хүчингүй болно.'))return;
  try{await api('/reception/rotate-token',{method:'POST',body:{}});await loadReception();notice('Reception.ai холболтын эрх шинэчлэгдлээ.');}
  catch(e){notice(customerMessage(e.message));}
};

async function loadAnalytics(){
  if(!state.user){$('analytics-content').innerHTML='<div class="empty">Хэрэглээний тайлан харахын тулд нэвтэрнэ үү.</div>';return;}
  $('analytics-content').innerHTML='<div class="empty">Уншиж байна…</div>';
  try{
    const data=await api('/analytics');
    const sub=data.subscription||{},wallet=data.wallet||{},local=data.local_30d||{};
    const cards=[
      ['Багц',customerPlanName(sub.plan_id||'trial')],
      ['Кредитийн үлдэгдэл',Number(wallet.balance||0).toLocaleString('en-US')],
      ['30 хоногт ашигласан',Number(data.credits_spent_30d||0).toLocaleString('en-US')],
      ['Багц дуусах',sub.cycle_end?new Date(sub.cycle_end*1000).toLocaleDateString('mn-MN'):'—']
    ];
    $('analytics-content').innerHTML='<div class="metric-grid">'+cards.map(x=>'<article><small>'+escapeHtml(x[0])+'</small><strong>'+escapeHtml(x[1])+'</strong></article>').join('')+'</div>'+
      '<div class="usage-local"><h3>RAINY · Сүүлийн 30 хоног</h3>'+Object.entries(local).map(([k,v])=>'<span><b>'+escapeHtml(toolLabel(k))+'</b>'+v+'</span>').join('')+'</div>';
  }catch(e){$('analytics-content').innerHTML='<div class="empty">'+escapeHtml(customerMessage(e.message))+'</div>';}
}
$('analytics-refresh').onclick=loadAnalytics;

function renderHistoryItem(item){
  const card=document.createElement('article');card.className='job';card.dataset.status=item.status;
  const head=document.createElement('div');head.className='job-head';
  const left=document.createElement('div');const title=document.createElement('h3');title.textContent=item.title||toolLabel(item.tool_type);
  const meta=document.createElement('p');meta.textContent=toolLabel(item.tool_type||'tool')+' · '+new Date(item.created*1000).toLocaleString('mn-MN');
  left.append(title,meta);const badge=document.createElement('span');badge.className='badge';badge.textContent=statusLabel(item.status);head.append(left,badge);card.append(head);
  if(item.source==='tts'&&item.status==='done'){
    const use=document.createElement('button');use.type='button';use.className='secondary';use.textContent='Видеонд оруулах ↗';
    use.onclick=()=>{$('voiceover-job').value=item.id;$('voiceover-selection').textContent='Сонгосон дуу: '+item.title;page('tts');$('video-voiceover-form').scrollIntoView({behavior:'smooth',block:'center'});};card.append(use);
  }
  if(item.result?.text){const p=document.createElement('p');p.className='result-preview';p.textContent=item.result.text.slice(0,400);card.append(p);}
  if(item.status==='failed'&&item.error){const p=document.createElement('p');p.className='danger-text';p.textContent='Алдаа: '+customerMessage(item.error);card.append(p);}
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
  if(!['queued','running'].includes(item.status)){
    const remove=document.createElement('button');remove.type='button';remove.className='danger-link';remove.textContent='Бүтээл устгах';
    remove.onclick=async()=>{if(!confirm('Энэ бүтээл болон файлуудыг устгах уу?'))return;remove.disabled=true;try{await api((item.source==='tts'?'/jobs/':'/tool-jobs/')+encodeURIComponent(item.id),{method:'DELETE',body:{}});await loadHistory();await loadToolResults(state.page);}catch(e){notice(customerMessage(e.message));remove.disabled=false;}};card.append(remove);
  }else{const info=document.createElement('p');info.className='field-help';info.textContent='Ажил үргэлжилж байна. Төлөвийг харахын тулд “Шинэчлэх” товч дарна уу.';card.append(info);}
  return card;
}

async function loadHistory(){
  const root=$('history-list');if(!state.user){root.innerHTML='<div class="empty">History харахын тулд нэвтэрнэ үү.</div>';return;}
  root.innerHTML='<div class="empty">Уншиж байна…</div>';
  try{
    const data=await api('/history');root.replaceChildren();
    if(!data.items.length)root.innerHTML='<div class="empty">Бүтээл хараахан алга.</div>';
    data.items.forEach(item=>root.append(renderHistoryItem(item)));
  }catch(e){root.innerHTML='<div class="empty">'+escapeHtml(customerMessage(e.message))+'</div>';}
}
$('history-refresh').onclick=loadHistory;

async function init(){
  initTheme();
  if(matchMedia('(pointer:fine)').matches)window.addEventListener('pointermove',e=>{document.documentElement.style.setProperty('--mx',e.clientX+'px');document.documentElement.style.setProperty('--my',e.clientY+'px');},{passive:true});
  try{
    const [health,meData]=await Promise.all([api('/health'),api('/me')]);
    state.health=health;state.user=meData.user;renderAccount();
    $('studio-readiness').textContent=health.engine_ready?'Үйлчилгээний холболт тохируулсан · Төлбөртэй багцын эрхийг нэвтэрсний дараа шалгана.':'Үйлчилгээний холболт хараахан бэлэн биш · '+(health.engine_message||'Админд хандана уу.');
    if(state.user)await loadProviderStatus();
  }catch(e){notice(customerMessage(e.message));}
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



const pendingActions=new Map();
const queuedTools=new Set(['/tools/dialogue','/tools/music','/tools/sound-effects','/tools/stt','/tools/voice-isolator','/tools/voice-changer','/tools/voice-design','/tools/voice-remix','/tools/alignment']);
const statusNames={queued:'Дараалалд',running:'Боловсруулж байна',done:'Бэлэн',completed:'Бэлэн',failed:'Амжилтгүй',cancelled:'Цуцалсан',training:'Сургаж байна',ready:'Бэлэн',pending:'Хүлээгдэж байна',paid:'Төлөгдсөн',expired:'Хугацаа дууссан'};
function statusLabel(value){return statusNames[value]||value||'Төлөв тодорхойгүй';}
async function api(path,options={}){
  const mutation=options.method&&options.method!=='GET';
  if(mutation&&pendingActions.has(path))throw new Error('Энэ үйлдэл боловсруулагдаж байна. Түр хүлээнэ үү.');
  if(mutation)pendingActions.set(path,true);
  try{
    const data=await rawApi(path,options);
    if(state.user?.admin_test&&Object.hasOwn(data,'credits_used'))data.credits_used=0;
    let result=data;
    if(queuedTools.has(path)&&data.job_id&&['queued','running'].includes(data.status))result=await waitToolJob(data.job_id);
    const resultPage=toolResultRoutes[path];
    if(mutation&&resultPage){
      await loadToolResults(resultPage);
      if(path==='/jobs'&&data.id)watchTtsResult(data.id);
    }
    return result;
  }finally{if(mutation)pendingActions.delete(path);}
}
async function waitToolJob(id){
  const end=Date.now()+10*60*1000;
  let errors=0;
  while(Date.now()<end){
    let data;
    try{data=await rawApi('/tool-jobs/'+encodeURIComponent(id));errors=0;}
    catch(e){
      if(!state.user||++errors>5)throw new Error(customerMessage(e.message)+' Ажлын явцыг бүтээлийн түүхээс шалгана уу. Дахин үүсгэх нь шинэ төлбөртэй үйлдэл болно.');
      notice('Холболт түр тасарлаа. Ажлын төлөвийг дахин шалгаж байна…');
      await new Promise(resolve=>setTimeout(resolve,5000));continue;
    }
    notice(statusLabel(data.status)+' · Ажлаа хаасан ч бүтээлийн түүхээс үргэлжлүүлэн шалгаж болно.');
    if(['done','completed'].includes(data.status))return {...(data.result||{}),job_id:id,artifacts:data.result?.artifacts||data.artifacts};
    if(['failed','cancelled'].includes(data.status))throw new Error(customerMessage(data.error||'Ажил амжилтгүй боллоо. Бүтээлийн түүхээс дэлгэрэнгүйг шалгана уу.'));
    await new Promise(resolve=>setTimeout(resolve,2500));
  }
  throw new Error('Хүлээлгийн хугацаа дууслаа. Ажил үргэлжилж байж болно. Бүтээлийн түүхээс төлөвийг шалгана уу; дахин илгээх шаардлагагүй.');
}
Object.assign(pageMeta,{
 'voice-design':['17','Хоолой / Хоолой зохиох'],'voice-remix':['18','Хоолой / Хоолой шинэчлэх'],alignment:['19','Хадмал / Хугацаа тааруулах'],settings:['20','Миний студи / Бүртгэл'],admin:['21','Удирдлага / Үйл ажиллагаа'],reset:['22','Бүртгэл / Нууц үг сэргээх']
});
function artifactUrl(value){return typeof value==='object'?(value.url||'/api/artifacts/'+encodeURIComponent(value.id||value.artifact_id)):'/api/artifacts/'+encodeURIComponent(value);}
for(const mode of ['voice-design','voice-remix']){
 $(mode+'-form').onsubmit=async event=>{
  event.preventDefault();if(!ensureUser())return;
  const form=event.currentTarget,button=form.querySelector('[type=submit]');if(button.disabled)return;
  setBusy(button,true,'Дээж үүсгэж байна…');
  try{
   const body=Object.fromEntries(new FormData(form));
   const data=await api('/tools/'+mode,{method:'POST',body});
   const root=$(mode+'-previews');root.replaceChildren();
   if(!data.previews?.length)throw new Error('Үйлчилгээ дууны дээж буцаасангүй. Бүтээлийн түүхийг шалгана уу.');
   data.previews.forEach((preview,index)=>{
    const card=document.createElement('article');card.className='voice-library-card';
    const title=document.createElement('h3');title.textContent='Хувилбар '+(index+1);
    const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src=artifactUrl(preview.artifact_id);
    const name=document.createElement('input');name.maxLength=100;name.required=true;name.placeholder='Хоолойн нэр';name.setAttribute('aria-label','Хувилбар '+(index+1)+'-ын нэр');
    const save=document.createElement('button');save.className='secondary';save.textContent='Хоолойн санд хадгалах';
    save.onclick=async()=>{
     if(!name.value.trim())return notice('Хоолойн нэр оруулна уу.');
     if(save.disabled)return;save.disabled=true;
     try{await api('/tools/'+mode+'/save',{method:'POST',body:{job_id:data.job_id,generated_voice_id:preview.generated_voice_id,name:name.value.trim()}});save.textContent='Санд хадгаллаа';await refreshVoices();notice('Шинэ хоолой таны санд нэмэгдлээ.');}
     catch(e){notice(customerMessage(e.message));save.disabled=false;}
    };
    card.append(title,audio,name,save);root.append(card);
   });loadBilling(true);
  }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
 };
}
$('alignment-form').onsubmit=async event=>{
 event.preventDefault();if(!ensureUser())return;
 const form=event.currentTarget,button=form.querySelector('[type=submit]');if(button.disabled)return;setBusy(button,true,'Хугацаа тааруулж байна…');
 try{
  const data=await api('/tools/alignment',{method:'POST',body:new FormData(form),form:true});
  const root=$('alignment-result');root.hidden=false;root.replaceChildren();
  const heading=document.createElement('p');heading.textContent='Хадмал бэлэн. Татах форматаа сонгоно уу.';root.append(heading);
  const entries=Array.isArray(data.artifacts)?data.artifacts.map(x=>[x.filename||x.kind,x]):Object.entries(data.artifacts||{});
  entries.forEach(([format,artifact])=>{const link=document.createElement('a');link.href=artifactUrl(artifact);link.textContent=format.toUpperCase()+' ↓';link.className='secondary';link.download='';root.append(link);});
  loadHistory();loadBilling(true);
 }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};
async function loadSettings(){
 if(!ensureUser())return;
 try{const data=await api('/account');state.user={...state.user,admin:data.admin,admin_test:data.admin_test};renderAccount();$('settings-info').textContent=data.email;}
 catch(e){$('settings-info').textContent=customerMessage(e.message);}
}
async function accountMutation(formId,path,body,success){
 const button=$(formId).querySelector('[type=submit]');if(button.disabled)return;setBusy(button,true);
 try{await api(path,{method:'POST',body});$(formId).reset();state.user=null;renderAccount();notice(success);page('tts');openAuth(false);}
 catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
}
$('password-form').onsubmit=e=>{e.preventDefault();if(ensureUser())accountMutation('password-form','/account/password',{current_password:$('current-password').value,new_password:$('new-password').value},'Нууц үг шинэчлэгдлээ. Шинэ нууц үгээрээ нэвтэрнэ үү.');};
$('delete-form').onsubmit=e=>{e.preventDefault();if(ensureUser())accountMutation('delete-form','/account/delete',{password:$('delete-password').value,confirmation:$('delete-confirmation').value},'Бүртгэл устгагдлаа.');};
let resetToken=new URLSearchParams(location.search).get('reset_token')||'';
if(resetToken)history.replaceState({},'',location.pathname);
function openReset(){
 $('auth-dialog').close();if(!resetToken)$('reset-email').value=$('email').value; $('reset-status').textContent='';page('reset');$('reset-email-field').hidden=!!resetToken;$('reset-email').required=!resetToken;
 $('reset-password-field').hidden=!resetToken;$('reset-password').required=!!resetToken;
 $('reset-submit-label').textContent=resetToken?'Шинэ нууц үг хадгалах':'Сэргээх холбоос авах';
}
$('forgot-password').onclick=openReset;
$('reset-form').onsubmit=async e=>{
 e.preventDefault();const button=e.currentTarget.querySelector('[type=submit]');if(button.disabled)return;setBusy(button,true);
 try{
  await api(resetToken?'/account/reset/confirm':'/account/reset/request',{method:'POST',body:resetToken?{token:resetToken,new_password:$('reset-password').value}:{email:$('reset-email').value}});
  $('reset-status').textContent=resetToken?'Нууц үг шинэчлэгдлээ. Шинэ нууц үгээрээ нэвтэрнэ үү.':'Бүртгэлтэй имэйл бол сэргээх холбоос илгээгдэнэ. Ирсэн захидал болон спам хавтсаа шалгана уу.';
  if(resetToken){resetToken='';history.replaceState({},'','/');$('reset-password').value='';$('reset-password-field').hidden=true;$('reset-password').required=false;$('reset-email-field').hidden=false;$('reset-email').required=true;$('reset-submit-label').textContent='Сэргээх холбоос авах';}
 }catch(err){$('reset-status').textContent=customerMessage(err.message);}finally{setBusy(button,false);}
};
async function loadAdmin(){
 if(!ensureUser()||!state.user.admin)return;
 const adminEmail=state.user.email;
 await loadProviderStatus();
 const root=$('admin-content');root.replaceChildren();
 try{
  const data=await api('/admin/overview');
  if(!state.user?.admin||state.user.email!==adminEmail)return;
  const labels={provider_cost:'ElevenLabs өртөг ба үлдэгдэл',account:'Данс',tier:'Багц',remaining_credits:'ElevenLabs үлдэгдэл',used_credits:'Зарцуулсан кредит',limit_credits:'Нийт боломжит кредит',monthly_quota:'Сарын кредит',monthly_cost_usd:'Сарын өртөг · USD',usd_per_provider_credit:'Нэг ElevenLabs кредитийн тооцоолсон өртөг · USD',cost_basis:'Өртгийн эх сурвалж',fresh:'Мэдээлэл шинэ эсэх',reconciliation:'Бодит суутгалтай тулгалт',samples:'Тулгасан хүсэлт',measured_provider_credits:'Хэмжигдсэн ElevenLabs кредит',allocated_cost_usd:'Хуваарилсан өртөг · USD',cost_factor:'Өртгийн хамгаалалтын үржүүлэгч',note:'Тайлбар',users:'Бүртгэл',active_users:'Идэвхтэй бүртгэл',jobs:'Ажил',failed_jobs:'Амжилтгүй ажил',queued_jobs:'Дараалал дахь ажил',storage:'Хадгалалт',provider:'Үйлчилгээ',billing:'Төлбөр',readiness:'Бэлэн байдал',credits:'Кредит',usage:'Хэрэглээ',cost:'Зардал',worker:'Боловсруулагч',database:'Өгөгдлийн сан',status:'Төлөв',errors:'Алдаа',counts:'Тоо хэмжээ',payments:'Төлбөр',recent_failures:'Сүүлийн алдаа',storage_bytes:'Хадгалалтын хэмжээ',ok:'Хэвийн',configured:'Тохируулсан'};
  function show(value,container){
   Object.entries(value||{}).forEach(([key,item])=>{
    const card=document.createElement('article');card.className='admin-card';
    const title=document.createElement('h3');title.textContent=labels[key]||key.replaceAll('_',' ');card.append(title);
    if(item&&typeof item==='object')show(item,card);
    else{const text=document.createElement('p');text.textContent=typeof item==='boolean'?(item?'Тийм':'Үгүй'):statusLabel(item);card.append(text);}container.append(card);
   });
  }show(data,root);
 }catch(e){root.textContent=customerMessage(e.message);}
}
$('admin-refresh').onclick=loadAdmin;
const costRefresh=document.createElement('button');costRefresh.type='button';costRefresh.className='secondary';costRefresh.textContent='ElevenLabs багц, үлдэгдэл шинэчлэх';
costRefresh.onclick=async()=>{costRefresh.disabled=true;try{await api('/admin/provider-cost/refresh',{method:'POST',body:{}});await loadAdmin();}catch(e){notice(customerMessage(e.message));}finally{costRefresh.disabled=false;}};
$('admin-refresh').after(costRefresh);
const catalogRefresh=document.createElement('button');catalogRefresh.type='button';catalogRefresh.className='secondary';catalogRefresh.textContent='Хоолой ба загварыг API-аас шинэчлэх';
catalogRefresh.onclick=async()=>{catalogRefresh.disabled=true;try{const data=await api('/admin/studio/catalog/refresh',{method:'POST',body:{}});await refreshVoices();notice('Монгол хоолой: '+data.native_voices+' · Үндсэн хоолой: '+data.default_voices+(data.errors?.length?' · Зарим сан шинэчлэгдсэнгүй. Дараа дахин оролдоно уу.':''));}catch(e){notice(customerMessage(e.message));}finally{catalogRefresh.disabled=false;}};
$('admin-refresh').after(catalogRefresh);
// Attach accessible names to existing controls using their nearby visible labels.
document.querySelectorAll('input,textarea,select').forEach((control,index)=>{
 if(!control.id)control.id='field-'+index;
 const label=control.closest('.field')?.querySelector('label')||control.previousElementSibling;
 if(label?.tagName==='LABEL'&&!label.contains(control))label.htmlFor=control.id;
 if(!control.labels?.length&&!control.getAttribute('aria-label'))control.setAttribute('aria-label',control.placeholder||control.name||'Оруулах утга');
});
$('close-auth').setAttribute('aria-label','Нэвтрэх цонх хаах');
$('text-tab').setAttribute('aria-pressed','true');$('srt-tab').setAttribute('aria-pressed','false');
const originalSetTtsMode=setTtsMode;
setTtsMode=mode=>{originalSetTtsMode(mode);$('text-tab').setAttribute('aria-pressed',String(mode==='text'));$('srt-tab').setAttribute('aria-pressed',String(mode==='srt'));};
const sampleTexts={business:'Сайн байна уу. Манай дэлгүүрийн намрын шинэ цуглуулга худалдаанд гарлаа. Та өөрт тохирох загвараа сонгон, хот дотор үнэгүй хүргэлтээр аваарай.',reels:'Өнөөдрийн нэг жижиг алхам маргаашийн том өөрчлөлтийг бүтээнэ. Түр зогсоод, амьсгаа аваад, өөртөө итгэлтэйгээр эхлээрэй.',course:'Энэ хичээлээр бид төсвөө хэрхэн төлөвлөхийг сурна. Эхлээд тогтмол орлого, дараа нь зайлшгүй зардлаа жагсаая.',interview:'Сайн байна уу. Өнөөдрийн ярилцлагаар Монголын жижиг бизнесүүдийн өсөлт, шинэ боломжийн тухай ярилцана.'};
const samples=document.createElement('div');samples.className='sample-actions';
Object.entries({business:'Бизнес',reels:'Богино видео',course:'Хичээл',interview:'Ярилцлага'}).forEach(([key,label])=>{const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=label;button.onclick=()=>{$('text').value=sampleTexts[key];updateCounter();updateEstimate();};samples.append(button);});
$('text').after(samples);
const estimate=document.createElement('p');estimate.id='tts-estimate';estimate.className='field-help';estimate.setAttribute('aria-live','polite');$('generate').before(estimate);
function updateEstimate(){
 const text=state.mode==='srt'?$('srt-text').value:$('text').value;
 const multiplier=Number(state.voices.find(v=>v.id===$('voice').value)?.cost_multiplier||1);
 const rate=$('tts-model').value==='eleven_v4_turbo'?40:80;
 estimate.textContent='Ойролцоогоор '+Math.ceil(text.length/1000*rate*multiplier)+' кредит · Дуудлагын толь, сэтгэл хөдлөлийн tag орсон нарийн тооцоог шалгана уу.';
}
for(const id of ['text','srt-text','tts-model','voice','tts-emotion','glossary'])$(id).addEventListener('input',updateEstimate);
$('tts-emotion').addEventListener('change',()=>{if($('tts-emotion').value!=='neutral')$('tts-model').value='eleven_v4';updateEstimate();});
$('tts-model').addEventListener('change',()=>{if($('tts-model').value==='eleven_v4_turbo')$('tts-emotion').value='neutral';updateEstimate();});
$('tts-quote').onclick=async()=>{
 if(!ensureUser())return;const button=$('tts-quote');setBusy(button,true,'Тооцож байна…');
 try{const body={voice_id:$('voice').value,model_id:$('tts-model').value,emotion:$('tts-emotion').value,speed:Number($('speed').value),glossary:parseGlossary()};body[state.mode==='srt'?'srt':'text']=$(state.mode==='srt'?'srt-text':'text').value;
 const quote=await api('/jobs/quote',{method:'POST',body});estimate.textContent=quote.credits+' кредит · '+quote.characters+' тэмдэгт · '+quote.segments+' хэсэг · Сонгосон хоолойн үржүүлэгч '+quote.voice_multiplier+'×';
 }catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};
$('video-voiceover-form').onsubmit=async event=>{
 event.preventDefault();if(!ensureUser())return;const form=event.currentTarget,button=form.querySelector('[type=submit]');setBusy(button,true,'Видео байршуулж байна…');
 try{if(!$('voiceover-job').value)throw new Error('Бүтээлийн түүхээс бэлэн дуу сонгоно уу.');await api('/tools/video-voiceover',{method:'POST',body:new FormData(form),form:true});notice('Видео дараалалд орлоо. Дуутай MP4 бүтээлийн түүхэд хадгалагдана.');page('history');}
 catch(e){notice(customerMessage(e.message));}finally{setBusy(button,false);}
};
$('music-duration').addEventListener('input',()=>{$('music-duration-label').textContent=$('music-duration').value+' секунд · ойролцоогоор '+Math.ceil(Number($('music-duration').value)/60*150)+' кредит';});
$('admin').append($('studio-readiness'),document.querySelector('.provider-status-card'));

const toolResultRoutes={'/jobs':'tts','/tools/dialogue':'dialogue','/tools/music':'music','/tools/sound-effects':'sfx','/tools/stt':'stt','/tools/realtime-save':'realtime','/tools/voice-isolator':'isolator','/tools/voice-changer':'changer','/tools/dubbing':'dubbing','/tools/voice-design':'voice-design','/tools/voice-remix':'voice-remix','/tools/alignment':'alignment'};
const toolGuides={
 tts:['Бичвэр эсвэл SRT хадмалаа оруулна.','Хоолой, унших хурдыг сонгоод “Дуу үүсгэх” дарна.','Бэлэн дуугаа сонсож, MP3 эсвэл WAV файлаар татна.'],
 clone:['Өөрийн эсвэл зөвшөөрөлтэй хүний цэвэр ярианы дээж оруулна.','Хоолойн нэр өгч, зөвшөөрлийг баталгаажуулна.','Үүссэн хоолойг хоолойн сангаас сонгон ашиглана.'],
 pvc:['Өөрийн хоолойн чанартай дээжийг байршуулна.','Зааврын дагуу хоолойн эзэмшигчийг баталгаажуулна.','Сургалт дууссаны дараа хоолойн сангаас ашиглана.'],
 dialogue:['Яригч бүрийн бичвэрийг тусдаа оруулна.','Яригч бүрд тохирох хоолой сонгоно.','Подкастаа үүсгээд сонсож, татаж авна.'],
 music:['Хүссэн хөгжмийн хэв маяг, уур амьсгалыг тайлбарлана.','Үргэлжлэх хугацаа болон хоолойтой эсэхийг сонгоно.','Үүссэн хөгжмөө сонсож, файлаар татна.'],
 sfx:['Хүссэн дуугаа тодорхой тайлбарлана.','Хугацаа болон давталтыг тохируулна.','Эффектээ үүсгээд сонсож, татаж авна.'],
 stt:['Яриатай аудио эсвэл видео файл оруулна.','Яригч ялгах болон бичвэр засах тохиргоог сонгоно.','Бэлэн бичвэр, хадмалыг үр дүнгээс татна.'],
 realtime:['Микрофон ашиглах зөвшөөрөл олгоно.','Бичвэр эхлүүлэх товчийг дараад ярьж эхэлнэ.','Дуусгах товчийг дарж бичвэрээ хадгална.'],
 isolator:['Шуугиантай аудио файлаа оруулна.','Яриа цэвэрлэх товчийг дарна.','Цэвэрлэсэн аудиогоо сонсож, татаж авна.'],
 changer:['Өөрийн ярианы аудио файлыг оруулна.','Солих хоолойг сонгон үүсгэнэ.','Шинэ хоолойтой аудиогоо сонсож, татна.'],
 dubbing:['Видео файл эсвэл дэмжигдсэн холбоос оруулна.','Эх хэл болон орчуулах хэлийг сонгоно.','Орчуулга дуусмагц MP3 аудио, бэлэн бол видеогоо татна.'],
 'voice-design':['Хоолойн өнгө, нас, хэмнэлийг тайлбарлана.','Сонсох жишээ бичвэрээ оруулж дээж үүсгэнэ.','Дээжүүдийг сонсоод хүссэн хоолойгоо нэрлэж хадгална.'],
 'voice-remix':['Өөрийн хадгалсан хоолойг сонгоно.','Яаж өөрчлөхөө тайлбарлаж дээж үүсгэнэ.','Таалагдсан хувилбарыг шинэ нэрээр хадгална.'],
 alignment:['Аудио болон түүнд уншсан бичвэрийг оруулна.','Хугацаа тааруулах товчийг дарна.','Бэлэн хадмалыг SRT эсвэл VTT файлаар татна.']
};
const toolKinds={tts:'tts',dialogue:'dialogue',music:'music',sfx:'sound_effects',stt:'speech_to_text',realtime:'realtime_stt',isolator:'voice_isolator',changer:'voice_changer',dubbing:'dubbing','voice-design':'voice_design','voice-remix':'voice_remix',alignment:['alignment','forced_alignment']};
const toolResultRequests=new Map();
const studioAdvice={tts:'Чанартай сонголт нь өгүүлэмж, ном, сурталчилгаанд тохирно. Хурдан сонголтыг богино бичвэр болон шуурхай ажилд хэрэглэнэ.',dialogue:'Яригч бүрд өөр Монгол хоолой сонгоно. Нэг хэсэгт нэг яригчийн өгүүлбэр оруулбал хэмнэлээ удирдахад хялбар.',stt:'Монгол яриаг таних тохиргоо ашиглана. Цэвэр бичлэг, ойр микрофон танилтын чанарыг сайжруулна.',realtime:'Монгол яриаг шууд бичвэр болгоно. Чимээгүй орчинд тод ярьж, дууссаны дараа нэр болон тоог шалгана.',dubbing:'Монгол руу орчуулахад яригчийн өнгө ба цагийг хадгалах загвар ашиглана. Нэр томьёо, орчуулгын утгыг эцэст нь шалгана.',changer:'Монгол дуудлагын дэмжлэг хязгаарлагдмал. Эхлээд богино дээжээр шалгаарай; Монгол бичвэрээс дуу үүсгэх нь илүү тохиромжтой.',music:'Хөгжмийн төрөл, хэмнэл, хөгжмийн зэмсэг, уур амьсгалыг тодорхой бичнэ. Монгол үгтэй дууны дуудлагыг сонсож шалгана.',sfx:'Дууны эх үүсвэр, орчин, зай болон хөдөлгөөнийг тайлбарлаарай.',clone:'Монгол хэлээр тод, шуугиангүй ярьсан олон өгүүлбэртэй дээж ашиглаарай.',pvc:'Өөрийн Монгол хоолойн тогтвортой өнгө, өндөр чанартай урт бичлэг ашиглана.',isolator:'Яриаг тодруулах хэрэгсэл. Хэт шуугиантай эх бичлэгийн алдагдсан үгийг нөхөн үүсгэхгүй.',alignment:'Монгол аудиотой яг таарсан бичвэр хэрэглэнэ. Эхлээд аудиогоо бичвэр болгоод засаж болно.','voice-design':'Монгол дуудлагыг жишээ бичвэрээр шалгана. Хоолойг хадгалахаасаа өмнө бүх дээжийг сонсоорой.','voice-remix':'Өөрийн хоолойн шинэ өнгө үүсгэнэ. Монгол дуудлага болон эх хоолойтой төстэй байдлыг дээжээр шалгана.'};
const studioPresets={story:{names:['Sarnai','Uyanga'],terms:/narrat|story|audiobook/i,speed:'0.95',label:'Тайван өгүүлэмж'},ad:{names:['Bolor','Temuulen'],terms:/advert|social|entertain/i,speed:'1.05',label:'Эрчтэй сурталчилгаа'},lesson:{names:['Bataar','Enkhtuya'],terms:/educat|narrat/i,speed:'1',label:'Тод тайлбар'},news:{names:['Munkhbat','Ganbold'],terms:/news|inform|narrat/i,speed:'1',label:'Тогтуун танилцуулга'}};
function recommendedVoice(preset,voices){
 const native=voices.filter(v=>v.builtin&&v.native_mn!==false);
 return native.find(v=>preset.names.some(n=>(v.name||'').split(' - ')[0]===n))||native.find(v=>preset.terms.test(v.use_case||''))||native[0];
}
function applyStudioPreset(){
 const preset=studioPresets[$('studio-preset').value];if(!preset)return;
 const voice=recommendedVoice(preset,state.voices);if(!voice){notice('Монгол хоолойн сан ачаалсны дараа дахин сонгоно уу.');return;}
 $('voice').value=voice.id;$('tts-model').value='eleven_v4';$('speed').value=preset.speed;$('speed-value').textContent=Number(preset.speed).toFixed(2)+'×';
 $('preset-help').textContent=preset.label+' · '+voiceDisplayName(voice)+'. Дээжийг хоолойн сангаас сонсоод хүсвэл өөрчилнө үү.';updateEstimate();
}
function buildToolWorkspaces(){
 $('studio-preset')?.addEventListener('change',applyStudioPreset);
 $('voice-search')?.addEventListener('input',()=>renderVoiceLibrary());$('voice-filter')?.addEventListener('change',()=>renderVoiceLibrary());
 Object.entries(toolGuides).forEach(([name,steps])=>{
  const section=$(name);if(!section)return;
  const workspace=document.createElement('div');workspace.className='tool-workspace';
  const inputs=document.createElement('div');inputs.className='tool-workspace-inputs';
  [...section.children].filter(el=>!el.classList.contains('tool-hero')).forEach(el=>inputs.append(el));
  const side=document.createElement('aside');side.className='tool-workspace-side';side.setAttribute('aria-label','Заавар ба үр дүн');
  const guide=document.createElement('section');guide.className='tool-guide';
  const title=document.createElement('h2');title.textContent='Хэрхэн ашиглах вэ?';guide.append(title);
  const list=document.createElement('ol');steps.forEach(step=>{const li=document.createElement('li');li.textContent=step;list.append(li);});guide.append(list);const advice=document.createElement('p');advice.className='field-help';advice.textContent=studioAdvice[name]||'';guide.append(advice);side.append(guide);
  if(toolKinds[name]){
   const output=document.createElement('section');output.className='tool-output';
   const header=document.createElement('div');header.className='tool-output-head';
   const h=document.createElement('h2');h.textContent='Сүүлийн үр дүн';
   const refresh=document.createElement('button');refresh.type='button';refresh.className='secondary';refresh.textContent='Шинэчлэх';refresh.onclick=()=>loadToolResults(name);header.append(h,refresh);
   const items=document.createElement('div');items.id=name+'-output-items';items.className='tool-output-items';items.setAttribute('aria-live','polite');
   const empty=document.createElement('p');empty.className='field-help';empty.textContent='Таны бүтээл бэлэн болмогц энд харагдана. Бүх бүтээлээ “Бүтээлийн түүх” хэсгээс үзнэ.';items.append(empty);
   output.append(header,items);side.append(output);
  }
  workspace.append(inputs,side);section.append(workspace);
 });
}
async function loadToolResults(name){
 const root=$(name+'-output-items');if(!root)return;
 if(!state.user){root.replaceChildren();const p=document.createElement('p');p.className='field-help';p.textContent='Нэвтэрсний дараа таны үр дүн энд харагдана.';root.append(p);return;}
 const owner=state.user.email,version=(toolResultRequests.get(name)||0)+1;toolResultRequests.set(name,version);
 try{
  const data=await rawApi('/history');
  if(state.user?.email!==owner||toolResultRequests.get(name)!==version)return;
  const items=data.items.filter(item=>[].concat(toolKinds[name]).includes(item.tool_type)).slice(0,3);
  root.replaceChildren();
  if(!items.length){const p=document.createElement('p');p.className='field-help';p.textContent='Энэ хэрэгслээр бүтээл үүсгэвэл үр дүн нь энд харагдана.';root.append(p);}
  items.forEach(item=>root.append(renderHistoryItem(item)));
 }catch(e){if(state.user?.email!==owner||toolResultRequests.get(name)!==version)return;const p=document.createElement('p');p.className='field-help';p.textContent=customerMessage(e.message);root.replaceChildren(p);}
}
async function watchTtsResult(id){
 const owner=state.user?.email;
 for(let tries=0;tries<180&&state.user?.email===owner;tries++){
  await new Promise(resolve=>setTimeout(resolve,5000));
  if(state.user?.email!==owner)return;
  try{const job=await rawApi('/jobs/'+encodeURIComponent(id));if(['done','failed','cancelled'].includes(job.status)){await loadToolResults('tts');return;}}
  catch(e){return;}
 }
}
buildToolWorkspaces();

init().then(()=>{loadToolResults(state.page);updateEstimate();if(resetToken||location.pathname==='/reset')openReset();if(state.user)loadSettings();});

function toolLabel(value){return ({tts:'Текстээс дуу',dialogue:'Подкаст',music:'Хөгжим',sound_effects:'Дууны эффект',stt:'Ярианаас бичвэр',speech_to_text:'Ярианаас бичвэр',realtime_stt:'Шууд бичвэр',voice_isolator:'Яриа цэвэрлэх',voice_changer:'Хоолой солих',dubbing:'Видео орчуулга',video_voiceover:'Видеонд дуу оруулах',voice_design:'Хоолой зохиох',voice_remix:'Хоолой шинэчлэх',alignment:'Хадмал тааруулах',forced_alignment:'Хадмал тааруулах',credit:'Кредит',grant:'Кредит нэмэх',charge:'Кредит зарцуулах',refund:'Кредит буцаах',tool:'Бүтээл'})[value]||value?.replaceAll('_',' ')||'Бүтээл';}
