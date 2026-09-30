'use strict';

const $ = id => document.getElementById(id);
const state = {
  user:null,
  health:null,
  voices:[],
  jobs:[],
  mode:'text',
  register:false,
  page:'studio',
  generating:false
};
let noticeTimer;

function notice(message) {
  $('notice').textContent=message;
  $('notice').hidden=false;
  clearTimeout(noticeTimer);
  noticeTimer=setTimeout(()=>$('notice').hidden=true,7000);
}

async function api(path, options={}) {
  const headers={'Content-Type':'application/json',...(options.headers||{})};
  if(state.user) headers['X-CSRF-Token']=state.user.csrf;
  const response=await fetch('/api'+path,{...options,headers});
  let data;
  try { data=await response.json(); }
  catch { throw new Error('Сервертэй холбогдож чадсангүй.'); }
  if(!response.ok) {
    if(response.status===401) {
      state.user=null;
      renderAccount();
    }
    throw new Error(data.error||'Алдаа гарлаа.');
  }
  return data;
}

function element(tag,text,cls) {
  const el=document.createElement(tag);
  if(text!==undefined) el.textContent=text;
  if(cls) el.className=cls;
  return el;
}

function page(name) {
  state.page=name;
  for(const section of document.querySelectorAll('.page')) section.hidden=section.id!==name;
  for(const button of document.querySelectorAll('.nav')) button.classList.toggle('active',button.dataset.page===name);
  const labels={studio:'Studio / Text to speech',history:'Archive / Бүтээлүүд'};
  $('breadcrumb').textContent=labels[name];
  document.querySelector('.route-index').textContent=name==='studio'?'01':'02';
  window.scrollTo({top:0,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}

function auth() {
  $('auth-dialog').showModal();
  $('email').focus();
}

function renderAccount() {
  $('account').textContent=state.user?state.user.email:'Нэвтрэх';
  $('logout').hidden=!state.user;
  $('generate').disabled=!state.health?.engine_ready||state.generating;
}

function renderHealth() {
  const root=document.querySelector('.engine-status');
  const ready=Boolean(state.health?.engine_ready);
  root.classList.toggle('ready',ready);
  $('engine-message').textContent=state.health?.engine_message||'Хөдөлгүүр шалгаж байна…';
}

function renderVoices() {
  const selected=$('voice').value;
  $('voice').replaceChildren();
  for(const voice of state.voices) {
    const option=element('option',voice.name);
    option.value=voice.id;
    $('voice').append(option);
  }
  if([...$('voice').options].some(option=>option.value===selected)) $('voice').value=selected;
}

const labels={queued:'Дараалалд',running:'Үүсгэж байна',done:'Бэлэн',failed:'Алдаа'};

function jobCard(job) {
  const card=element('article',undefined,'job');
  card.dataset.status=job.status;

  const head=element('div',undefined,'job-head');
  const info=element('div');
  const date=new Date(job.created*1000).toLocaleString('mn-MN',{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  info.append(element('h3',job.title),element('p',date));
  head.append(info,element('span',labels[job.status]||job.status,'badge'));
  card.append(head);

  if(job.status==='running'||job.status==='queued') {
    const progress=element('progress');
    progress.max=100;
    progress.value=job.progress||0;
    progress.setAttribute('aria-label','Үүсгэлтийн явц');
    card.append(progress);
  }

  if(job.error) card.append(element('p',job.error,'danger'));

  if(job.status==='done') {
    const audio=element('audio');
    audio.controls=true;
    audio.preload='none';
    audio.src='/api/jobs/'+job.id+'/wav';
    card.append(audio);

    const actions=element('div',undefined,'job-actions');
    for(const format of ['wav','mp3']) {
      const link=element('a',format.toUpperCase()+' ↓');
      link.href='/api/jobs/'+job.id+'/'+format;
      link.download='rainy-voice.'+format;
      actions.append(link);
    }
    card.append(actions);

    try {
      for(const warning of JSON.parse(job.result||'{}').warnings||[]) card.append(element('p',warning));
    } catch {}
  }

  if(job.status!=='running') {
    const remove=element('button','Устгах','danger');
    remove.onclick=async()=>{
      if(!confirm('Энэ бүтээлийг устгах уу?')) return;
      try {
        await api('/jobs/'+job.id,{method:'DELETE'});
        await refresh();
      } catch(e) {
        notice(e.message);
      }
    };
    card.append(remove);
  }
  return card;
}

function renderJobs() {
  for(const [id,limit] of [['recent-jobs',3],['history-jobs',50]]) {
    const root=$(id);
    root.replaceChildren();
    const jobs=state.jobs.slice(0,limit);
    if(!jobs.length) {
      root.append(element('div',state.user?'Таны анхны бүтээл энд харагдана.':'Нэвтэрсний дараа бүтээлүүд энд хадгалагдана.','empty'));
    }
    for(const job of jobs) root.append(jobCard(job));
  }
}

async function refresh() {
  if(!state.user) {
    state.jobs=[];
    state.voices=[{id:'WgH4JH8sD6a2SIrujiKn',name:'RAINY Voice 01',builtin:true}];
  } else {
    const [voices,jobs]=await Promise.all([api('/voices'),api('/jobs')]);
    state.voices=voices.voices;
    state.jobs=jobs.jobs;
  }
  renderVoices();
  renderJobs();
}

function setTheme(theme) {
  document.documentElement.dataset.theme=theme;
  localStorage.setItem('rainy-theme',theme);
  $('theme-toggle').textContent=theme==='light'?'☾':'☼';
  $('theme-toggle').setAttribute('aria-label',theme==='light'?'Харанхуй горим':'Цайвар горим');
}

function initTheme() {
  const saved=localStorage.getItem('rainy-theme');
  const preferred=window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
  setTheme(saved||preferred);
}

function setGenerating(value) {
  state.generating=value;
  const button=$('generate');
  button.classList.toggle('is-generating',value);
  button.querySelector('.generate-label').textContent=value?'Дуу үүсгэж байна…':'Дуу үүсгэх';
  button.querySelector('.generate-arrow').textContent=value?'···':'↗';
  renderAccount();
}

for(const button of document.querySelectorAll('.nav')) button.onclick=()=>page(button.dataset.page);

$('theme-toggle').onclick=()=>{
  const next=document.documentElement.dataset.theme==='light'?'dark':'light';
  setTheme(next);
};

$('account').onclick=()=>{
  if(!state.user) auth();
  else notice('Та '+state.user.email+' хаягаар нэвтэрсэн байна.');
};

$('close-auth').onclick=()=>$('auth-dialog').close();

$('auth-dialog').addEventListener('click',event=>{
  if(event.target===$('auth-dialog')) $('auth-dialog').close();
});

$('logout').onclick=async()=>{
  try {
    await api('/logout',{method:'POST',body:'{}'});
    state.user=null;
    renderAccount();
    await refresh();
    notice('Системээс гарлаа.');
  } catch(e) {
    notice(e.message);
  }
};

$('auth-toggle').onclick=()=>{
  state.register=!state.register;
  $('auth-title').textContent=state.register?'RAINY-д бүртгүүлэх':'RAINY-д нэвтрэх';
  $('auth-submit').querySelector('span:first-child').textContent=state.register?'Бүртгүүлэх':'Нэвтрэх';
  $('auth-toggle').textContent=state.register?'Бүртгэлтэй бол нэвтрэх':'Шинэ бүртгэл үүсгэх';
  $('password').autocomplete=state.register?'new-password':'current-password';
};

$('auth-form').onsubmit=async event=>{
  event.preventDefault();
  $('auth-error').textContent='';
  $('auth-submit').disabled=true;
  try {
    const result=await api(state.register?'/register':'/login',{
      method:'POST',
      body:JSON.stringify({email:$('email').value,password:$('password').value})
    });
    state.user=result.user;
    $('password').value='';
    $('auth-dialog').close();
    renderAccount();
    await refresh();
    notice('RAINY Studio бэлэн.');
  } catch(e) {
    $('auth-error').textContent=e.message;
  } finally {
    $('auth-submit').disabled=false;
  }
};

function updateCounter() {
  const count=$('text').value.length;
  $('counter').textContent=count.toLocaleString('en-US')+' / 12,000';
  $('counter').classList.toggle('near-limit',count>10500);
}
$('text').oninput=updateCounter;

$('example').onclick=()=>{
  $('text').value='Сайн байна уу. Энэ бол RAINY Voice. Монгол үг бүр өөрийн хэмнэл, өөрийн өнгө, өөрийн түүхтэй.';
  updateCounter();
  $('text').focus();
};

$('speed').oninput=()=>{
  $('speed-value').textContent=Number($('speed').value).toFixed(2)+'×';
};

function mode(value) {
  state.mode=value;
  $('text').hidden=value!=='text';
  $('srt-panel').hidden=value!=='srt';
  $('text-tab').classList.toggle('selected',value==='text');
  $('srt-tab').classList.toggle('selected',value==='srt');
  $('example').hidden=value!=='text';
  $('counter').hidden=value!=='text';
}

$('text-tab').onclick=()=>mode('text');
$('srt-tab').onclick=()=>mode('srt');

$('srt-file').onchange=async()=>{
  const file=$('srt-file').files[0];
  if(!file) return;
  if(file.size>40000) {
    notice('SRT файл хэт том байна.');
    return;
  }
  $('srt-text').value=await file.text();
  notice(file.name+' файл уншигдлаа.');
};

$('all-jobs').onclick=()=>page('history');
$('refresh').onclick=()=>refresh().then(()=>notice('Бүтээлүүд шинэчлэгдлээ.')).catch(e=>notice(e.message));

$('generate').onclick=async()=>{
  if(!state.user) {
    auth();
    return;
  }

  const glossary={};
  for(const line of $('glossary').value.split('\n').filter(x=>x.trim())) {
    const i=line.indexOf('=');
    if(i<1||!line.slice(i+1).trim()) {
      notice('Дуудлагын толь: нэр = дуудлага гэсэн хэлбэртэй байна.');
      return;
    }
    glossary[line.slice(0,i).trim()]=line.slice(i+1).trim();
  }

  const data={
    title:$('title').value,
    voice_id:$('voice').value,
    speed:Number($('speed').value),
    glossary
  };
  data[state.mode==='srt'?'srt':'text']=$(state.mode==='srt'?'srt-text':'text').value;

  setGenerating(true);
  try {
    await api('/jobs',{method:'POST',body:JSON.stringify(data)});
    notice('Дуу үүсгэлт эхэллээ. Бүтээл бэлэн болмогц энд харагдана.');
    await refresh();
  } catch(e) {
    notice(e.message);
  } finally {
    setGenerating(false);
  }
};

async function init() {
  initTheme();

  if(window.matchMedia('(pointer:fine)').matches) {
    window.addEventListener('pointermove',event=>{
      document.documentElement.style.setProperty('--mx',event.clientX+'px');
      document.documentElement.style.setProperty('--my',event.clientY+'px');
    },{passive:true});
  }

  try {
    const [health,me]=await Promise.all([api('/health'),api('/me')]);
    state.health=health;
    state.user=me.user;
    $('auth-toggle').hidden=!health.registration_open;
    renderHealth();
    renderAccount();
    await refresh();
  } catch(e) {
    state.health={engine_ready:false,engine_message:'Сервертэй холбогдож чадсангүй.'};
    renderHealth();
    renderAccount();
    notice(e.message);
  }
}

init();

setInterval(async()=>{
  if(document.hidden||!state.user||!state.jobs.some(job=>['queued','running'].includes(job.status))) return;
  try {
    const next=(await api('/jobs')).jobs;
    if(JSON.stringify(next)!==JSON.stringify(state.jobs)) {
      state.jobs=next;
      renderJobs();
    }
  } catch {}
},3500);