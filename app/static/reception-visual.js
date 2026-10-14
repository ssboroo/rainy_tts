'use strict';
/* Compact RAINY Receptionist UI. Real stream state comes ONLY from app.js.
   Visual motion while idle is decorative, not a claim that an agent is online. */
const receptionStudio=(()=>{
  const root=$('reception'),stage=$('rv-stage');
  if(!root||!stage)return null;
  const sections={
    voice:[$('rl-voice')],
    overview:[$('rl-console')],
    booking:[$('rl-public'),$('rl-services'),$('reception-booking-form')?.closest('.tool-form'),
       $('reception-bookings-list')?.closest('.ledger-wrap'),$('reception-time-form')?.closest('.tool-form')],
    knowledge:[$('rl-knowledge')],
    setup:[$('rl-connect'),$('rl-business'),$('rl-webhooks'),$('reception-events')?.closest('.ledger-wrap')],
    pricing:[$('rl-pricing')]
  };
  const nodes=Object.values(sections).flat().filter(Boolean);
  const all=[...new Set(nodes)];
  all.forEach(el=>el.classList.add('reception-tab-panel'));
  let tab='voice',ready=false,active=false,streamStatus='idle';
  const buttons=[...root.querySelectorAll('[data-reception-tab]')];
  function setTab(name){
    if(!sections[name])return;
    if(tab==='voice'&&name!=='voice'&&typeof agentPreview!=='undefined'&&agentPreview)
      stopAgentPreview(); // Never allow paid voice calls to continue unseen in another tab.
    tab=name;
    for(const el of all)el.hidden=!sections[name].includes(el);
    for(const btn of buttons){
      const selected=btn.dataset.receptionTab===name;
      btn.setAttribute('aria-selected',String(selected));
      btn.tabIndex=selected?0:-1;
    }
    if(name==='voice')refreshConnection();
  }
  buttons.forEach((btn,i)=>{
    btn.onclick=()=>setTab(btn.dataset.receptionTab);
    btn.onkeydown=event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();
      const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:
        (i+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
      buttons[next].focus();
      setTab(buttons[next].dataset.receptionTab);
    };
  });
  // Legacy deep links now select their parent tab instead of scrolling to hidden panels.
  const destinations={ 'rl-console':'overview','rl-connect':'setup','rl-webhooks':'setup',
    'rl-business':'setup','rl-pricing':'pricing','rl-knowledge':'knowledge',
    'rl-public':'booking','rl-services':'booking','rl-voice':'voice' };
  root.addEventListener('click',event=>{
    const a=event.target.closest('a[href^="#rl-"]');
    if(!a)return;
    const id=a.getAttribute('href').slice(1),target=destinations[id];
    if(!target)return;
    event.preventDefault();
    setTab(target);
    root.querySelector('#'+id)?.scrollIntoView({behavior:'smooth',block:'start'});
  });
  const viewButtons={orb:$('rv-view-orb'),avatar:$('rv-view-avatar')};
  function setView(view){
    if(!['orb','avatar'].includes(view))return;
    stage.dataset.view=view;
    $('rv-orb').hidden=view!=='orb';
    $('rv-avatar').hidden=view!=='avatar';
    for(const [name,btn] of Object.entries(viewButtons)){
      btn.setAttribute('aria-pressed',String(name===view));
    }
    try{localStorage.setItem('reception-voice-style',view);}catch{}
  }
  let stored='orb';
  try{stored=localStorage.getItem('reception-voice-style')||'orb';}catch{}
  setView(stored);
  Object.entries(viewButtons).forEach(([name,btn])=>btn.onclick=()=>setView(name));
  function setState(next){
    if(!['idle','ready','connecting','listening','speaking','error'].includes(next))return;
    streamStatus=next;
    stage.dataset.state=next;
    const labels={
      idle:['Холболт тохируулаагүй','Агент холбосны дараа ярилцах боломжтой.'],
      ready:['Ярихад бэлэн','Микрофон ашиглахын тулд товчийг дарна уу.'],
      connecting:['Холбогдож байна…','ElevenLabs-ийн эрх, микрофоны холболтыг шалгаж байна.'],
      listening:['Таныг сонсож байна','Монгол хэлээр энгийнээр ярьж үзнэ үү.'],
      speaking:['AI хариулж байна','Дуут хариултыг сонсоно уу.'],
      error:['Холболт амжилтгүй','Доорх алдааг шалгаад дахин оролдоно уу.']
    };
    const label=(next==='idle'&&ready)?labels.ready:labels[next];
    $('rv-state-label').textContent=label[0];
    $('rv-state-sub').textContent=label[1];
    active=['connecting','listening','speaking'].includes(next);
    $('rv-start-btn').hidden=active;
    $('rv-stop-btn').hidden=!active;
    $('rv-start-btn').disabled=!ready;
    $('rv-setup-btn').hidden=active;
  }
  async function refreshConnection(){
    if(!state.user?.admin){
      ready=false;setState('idle');return;
    }
    try{
      const r=await api('/production/agent-status');
      ready=Boolean(r.enabled);
      if(!active&&streamStatus!=='error')setState(ready?'ready':'idle');
      $('rv-setup-btn').textContent=ready?'Агентын тохиргоо ↗':'Агент холбох ↗';
    }catch{
      ready=false;
      if(!active)setState('error');
    }
  }
  $('rv-start-btn').onclick=async()=>{
    await refreshConnection();
    if(!ready){setTab('setup');return;}
    if($('voice-agent-start')?.disabled)return;
    setState('connecting');
    $('voice-agent-start').click(); // existing tested, metered WebSocket runtime
  };
  $('rv-stop-btn').onclick=()=>stopAgentPreview();
  $('rv-setup-btn').onclick=()=>{setTab('setup');$('rl-agent-id')?.focus();};
  document.addEventListener('rainy:agent-state',event=>{
    setState(event.detail?.state||'idle');
  });
  document.addEventListener('rainy:agent-level',event=>{
    const v=Number(event.detail?.level);
    if(Number.isFinite(v))stage.style.setProperty('--rv-level',Math.max(0,Math.min(1,v)).toFixed(2));
  });
  document.addEventListener('rainy:agent-transcript',event=>{
    const role=event.detail?.role;
    if(!['user','agent'].includes(role))return;
    const text=String(event.detail?.text||'').slice(0,500).trim();
    if(!text)return;
    const list=$('rv-transcript');
    const empty=list.querySelector('.rv-muted');if(empty)empty.remove();
    const line=document.createElement('p');line.className='rv-transcript-line';
    const who=document.createElement('b');who.textContent=role==='user'?'Та:':'AI:';
    line.append(who,document.createTextNode(text));list.append(line);
    while(list.children.length>6)list.firstChild.remove();
    list.scrollTop=list.scrollHeight;
  });
  document.addEventListener('rainy:page',event=>{
    if(event.detail?.name==='reception'&&state.user?.admin)refreshConnection();
  });
  document.addEventListener('rainy:agent-refresh',()=>refreshConnection());
  setTab('voice');
  return {setTab,setView,refreshConnection,setState};
})();
