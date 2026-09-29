'use strict';
const $ = id => document.getElementById(id);
const state = {user:null, health:null, voices:[], jobs:[], mode:'text', register:false, page:'studio'};
let noticeTimer;
function notice(message) { $('notice').textContent=message; $('notice').hidden=false; clearTimeout(noticeTimer); noticeTimer=setTimeout(()=>$('notice').hidden=true,9000); }
async function api(path, options={}) {
  const headers={'Content-Type':'application/json',...(options.headers||{})};
  if(state.user) headers['X-CSRF-Token']=state.user.csrf;
  const response=await fetch('/api'+path,{...options,headers});
  let data; try { data=await response.json(); } catch { throw new Error('Сервертэй холбогдож чадсангүй.'); }
  if(!response.ok) { if(response.status===401) {state.user=null;renderAccount();} throw new Error(data.error||'Алдаа гарлаа.'); }
  return data;
}
function element(tag,text,cls) {const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function page(name) {state.page=name;for(const section of document.querySelectorAll('.page'))section.hidden=section.id!==name;for(const button of document.querySelectorAll('.nav'))button.classList.toggle('active',button.dataset.page===name);$('breadcrumb').textContent='Ажлын талбар / '+({studio:'Дуу үүсгэх',voices:'Миний хоолой',history:'Миний бүтээлүүд'}[name]);}
function auth() {$('auth-dialog').showModal();$('email').focus();}
function renderAccount() {$('account').textContent=state.user?state.user.email:'Нэвтрэх';$('logout').hidden=!state.user;$('generate').disabled=!state.health?.engine_ready;}
function renderVoices() {
  const selected=$('voice').value;$('voice').replaceChildren();$('voice-list').replaceChildren();
  for(const voice of state.voices) {
    if(voice.builtin||state.health?.capabilities.voice_cloning){const option=element('option',voice.name);option.value=voice.id;$('voice').append(option);}
    if(voice.builtin) continue;
    const card=element('article',undefined,'card voice-card');card.append(element('h2',voice.name),element('p','Хувийн хоолой','hint'));
    const audio=element('audio');audio.controls=true;audio.preload='none';audio.src='/api/voices/'+voice.id+'/audio';card.append(audio);
    const remove=element('button','Устгах','quiet danger');remove.onclick=async()=>{if(!confirm('Энэ хоолойн бичлэгийг устгах уу?'))return;try{await api('/voices/'+voice.id,{method:'DELETE'});await refresh();}catch(e){notice(e.message);}};card.append(remove);$('voice-list').append(card);
  }
  if([...$('voice').options].some(o=>o.value===selected))$('voice').value=selected;
  if(!$('voice-list').children.length)$('voice-list').append(element('div',state.user?'Хадгалсан хувийн хоолой хараахан байхгүй.':'Хоолойгоо хадгалахын тулд нэвтэрнэ үү.','empty'));
}
const labels={queued:'Дараалалд',running:'Үүсгэж байна',done:'Бэлэн',failed:'Алдаа гарсан'};
function jobCard(job) {
  const card=element('article',undefined,'job'),head=element('div',undefined,'job-head'),info=element('div');
  info.append(element('h3',job.title),element('p',new Date(job.created*1000).toLocaleString('mn-MN')));head.append(info,element('span',labels[job.status]||job.status,'badge'));card.append(head);
  if(job.status==='running'||job.status==='queued'){const progress=element('progress');progress.max=100;progress.value=job.progress;progress.setAttribute('aria-label','Үүсгэлтийн явц');card.append(progress);}
  if(job.error)card.append(element('p',job.error,'danger'));
  if(job.status==='done') {
    const audio=element('audio');audio.controls=true;audio.preload='none';audio.src='/api/jobs/'+job.id+'/wav';card.append(audio);
    for(const format of ['wav','mp3']){const link=element('a',format.toUpperCase()+' татах');link.href='/api/jobs/'+job.id+'/'+format;link.download='rainy-voice.'+format;card.append(link);}
    try{for(const warning of JSON.parse(job.result||'{}').warnings||[])card.append(element('p',warning));}catch{}
  }
  if(job.status!=='running'){const remove=element('button','Устгах','quiet danger');remove.onclick=async()=>{if(!confirm('Энэ бүтээлийг устгах уу?'))return;try{await api('/jobs/'+job.id,{method:'DELETE'});await refresh();}catch(e){notice(e.message);}};card.append(remove);}
  return card;
}
function renderJobs() {for(const [id,limit] of [['recent-jobs',3],['history-jobs',50]]) {const root=$(id);root.replaceChildren();const jobs=state.jobs.slice(0,limit);if(!jobs.length)root.append(element('div',state.user?'Таны анхны бүтээл энд харагдана.':'Нэвтэрч бүтээлүүдээ хадгалаарай.','empty'));for(const job of jobs)root.append(jobCard(job));}}
async function refresh() {if(!state.user){state.jobs=[];state.voices=[{id:'builtin-female',name:'Эмэгтэй · Oron',builtin:true},{id:'builtin-male',name:'Эрэгтэй · Oron',builtin:true}];}else{const [voices,jobs]=await Promise.all([api('/voices'),api('/jobs')]);state.voices=voices.voices;state.jobs=jobs.jobs;}renderVoices();renderJobs();}
for(const button of document.querySelectorAll('.nav'))button.onclick=()=>page(button.dataset.page);
$('account').onclick=()=>{if(!state.user)auth();else notice('Та '+state.user.email+' хаягаар нэвтэрсэн байна.');};$('close-auth').onclick=()=>$('auth-dialog').close();
$('logout').onclick=async()=>{try{await api('/logout',{method:'POST',body:'{}'});state.user=null;renderAccount();await refresh();}catch(e){notice(e.message);}};
$('auth-toggle').onclick=()=>{state.register=!state.register;$('auth-title').textContent=state.register?'Бүртгэл үүсгэх':'Студид нэвтрэх';$('auth-submit').textContent=state.register?'Бүртгүүлэх':'Нэвтрэх';$('auth-toggle').textContent=state.register?'Бүртгэлтэй бол нэвтрэх':'Шинэ бүртгэл үүсгэх';$('password').autocomplete=state.register?'new-password':'current-password';};
$('auth-form').onsubmit=async event=>{event.preventDefault();$('auth-error').textContent='';$('auth-submit').disabled=true;try{const result=await api(state.register?'/register':'/login',{method:'POST',body:JSON.stringify({email:$('email').value,password:$('password').value})});state.user=result.user;$('password').value='';$('auth-dialog').close();renderAccount();await refresh();}catch(e){$('auth-error').textContent=e.message;}finally{$('auth-submit').disabled=false;}};
$('text').oninput=()=>$('counter').textContent=$('text').value.length+' / 12000';
$('example').onclick=()=>{$('text').value='Сайн байна уу. Энэ бол таны түүх эхлэх мөч. Үг бүхэн өөрийн өнгөтэй, хоолой бүхэн өөрийн түүхтэй.';$('text').oninput();};
$('speed').oninput=()=>$('speed-value').textContent=Number($('speed').value).toFixed(2)+'×';
function mode(value){state.mode=value;$('text').hidden=value!=='text';$('srt-panel').hidden=value!=='srt';$('text-tab').classList.toggle('selected',value==='text');$('srt-tab').classList.toggle('selected',value==='srt');$('example').hidden=value!=='text';$('counter').hidden=value!=='text';}
$('text-tab').onclick=()=>mode('text');$('srt-tab').onclick=()=>mode('srt');
$('srt-file').onchange=async()=>{const file=$('srt-file').files[0];if(!file)return;if(file.size>40000){notice('SRT файл хэт том байна.');return;}$('srt-text').value=await file.text();};
$('add-voice-link').onclick=()=>page('voices');$('all-jobs').onclick=()=>page('history');$('refresh').onclick=()=>refresh().catch(e=>notice(e.message));
$('generate').onclick=async()=>{
  if(!state.user){auth();return;}
  const glossary={};for(const line of $('glossary').value.split('\n').filter(x=>x.trim())){const i=line.indexOf('=');if(i<1||!line.slice(i+1).trim()){notice('Дуудлагын толь: нэр = дуудлага гэсэн хэлбэртэй байна.');return;}glossary[line.slice(0,i).trim()]=line.slice(i+1).trim();}
  const data={title:$('title').value,voice_id:$('voice').value,speed:Number($('speed').value),glossary};data[state.mode==='srt'?'srt':'text']=$(state.mode==='srt'?'srt-text':'text').value;
  $('generate').disabled=true;
  try{await api('/jobs',{method:'POST',body:JSON.stringify(data)});notice('Ажил дараалалд орлоо. Хуудас хаасан ч үргэлжилнэ.');await refresh();}catch(e){notice(e.message);}finally{renderAccount();}
};
$('voice-form').onsubmit=async event=>{
  event.preventDefault();if(!state.user){auth();return;}
  const file=$('voice-file').files[0];if(!file||file.size>8*1024*1024){notice('8 MB хүртэл аудио сонгоно уу.');return;}
  const button=event.target.querySelector('button[type=submit]');button.disabled=true;
  try{const audio=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});await api('/voices',{method:'POST',body:JSON.stringify({name:$('voice-name').value,transcript:$('transcript').value,consent:$('consent').checked,audio})});event.target.reset();notice('Хоолойн бичлэг хадгалагдлаа.');await refresh();}catch(e){notice(e.message||'Файл уншиж чадсангүй.');}finally{button.disabled=false;}
};
async function init(){try{const [health,me]=await Promise.all([api('/health'),api('/me')]);state.health=health;state.user=me.user;$('engine-message').textContent=health.engine_message;$('auth-toggle').hidden=!health.registration_open;if(health.capabilities.voice_cloning)$('clone-note').textContent='Хоолой дуурайлт туршилтын горимд нээлттэй. Төстэй байдал, дуудлагыг реплик бүрээр сонсож шалгаарай.';renderAccount();await refresh();}catch(e){$('engine-message').textContent='Сервертэй холбогдож чадсангүй.';notice(e.message);}}
init();
setInterval(async()=>{if(document.hidden||!state.user||!state.jobs.some(j=>['queued','running'].includes(j.status)))return;try{const next=(await api('/jobs')).jobs;if(JSON.stringify(next)!==JSON.stringify(state.jobs)){state.jobs=next;renderJobs();}}catch{}},4000);
