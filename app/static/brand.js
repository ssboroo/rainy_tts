/* Shared vector icon family and accessible mobile navigation. */
'use strict';
(()=>{
 const paths={
  tts:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
  clone:'<path d="M8 3v5m0 4v9m4-15v12m4-15v7m0 4v7M4 9v6m16-8v10"/>',
  pvc:'<path d="m12 2 9 5-9 15L3 7l9-5ZM3 7h18M8 7l4 15 4-15M8 7l4-5 4 5"/>',
  dialogue:'<path d="M3 14v-3a9 9 0 0 1 18 0v3"/><rect x="2" y="12" width="5" height="8" rx="2"/><rect x="17" y="12" width="5" height="8" rx="2"/>',
  music:'<path d="M9 18V5l12-3v13M9 9l12-3"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="18" cy="15" rx="3" ry="3"/>',
  sfx:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4m-2-2h4"/>',
  stt:'<rect x="4" y="2" width="16" height="20" rx="3"/><path d="M8 7h8M8 12h8M8 17h5"/>',
  realtime:'<path d="M3 10v4m4-7v10m5-14v18m5-14v10m4-7v4"/>',
  isolator:'<path d="M4 12h3l3-8 4 16 3-8h3M18 2v4m-2-2h4"/>',
  changer:'<path d="M3 8h16l-4-4M21 16H5l4 4M19 8l2 2M5 16l-2-2"/>',
  dubbing:'<rect x="2" y="4" width="20" height="16" rx="3"/><path d="m10 8 6 4-6 4V8Z"/>',
  voices:'<circle cx="9" cy="7" r="4"/><path d="M2 22v-4a7 7 0 0 1 14 0v4m1-13a4 4 0 0 0 0-8m2 13a6 6 0 0 1 3 5v3"/>',
  reception:'<path d="M5 3h4l2 5-3 2a16 16 0 0 0 6 6l2-3 5 2v4a2 2 0 0 1-2 2A18 18 0 0 1 3 5a2 2 0 0 1 2-2Z"/>',
  billing:'<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M2 10h20M6 15h3"/>',
  analytics:'<path d="M3 3v18h18M7 16v-4m5 4V7m5 9V4"/>',
  history:'<path d="M3 7h18v14H3V7ZM2 3h20v4H2V3Zm7 8h6"/>',
  'voice-design':'<path d="m4 20 4-1L20 7l-3-3L5 16l-1 4ZM14 7l3 3M3 4h5M5 2v4"/>',
  'voice-remix':'<path d="m4 20 4-1L20 7l-3-3L5 16l-1 4ZM15 6l3 3M4 2v4M2 4h4m14 11v6m-3-3h6"/>',
  alignment:'<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M6 9h4m-4 6h4m4-6h4m-4 6h4"/>',
  settings:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2" fill="var(--panel)"/><circle cx="16" cy="12" r="2" fill="var(--panel)"/><circle cx="10" cy="18" r="2" fill="var(--panel)"/>',
  admin:'<path d="m12 2 8 4v7c0 5-8 9-8 9s-8-4-8-9V6l8-4Z"/><path d="m8 12 3 3 5-6"/>',
  menu:'<path d="M4 6h16M4 12h16M4 18h16"/>'
 };
 const svg=key=>'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(paths[key]||paths.tts)+'</svg>';
 document.querySelectorAll('.nav[data-page]').forEach(button=>{const icon=button.querySelector('.nav-icon');if(icon)icon.innerHTML=svg(button.dataset.page);});
 document.querySelectorAll('.page').forEach(section=>{const icon=section.querySelector('.hero-tool-icon');if(icon)icon.innerHTML=svg(section.id);});
 document.querySelector('#open-menu .nav-icon').innerHTML=svg('menu');
 Object.assign(pageMeta,{'voice-design':['17','Хоолой / Хоолой зохиох'],'voice-remix':['18','Хоолой / Хоолой шинэчлэх'],alignment:['19','Видео / Хадмал тааруулах'],settings:['20','Миний студи / Тохиргоо'],reset:['21','Бүртгэл / Нууц үг сэргээх'],admin:['22','Студийн удирдлага']});
 const drawer=document.getElementById('studio-navigation');
 const trigger=document.getElementById('open-menu');
 const backdrop=document.getElementById('menu-backdrop');
 const mobile=matchMedia('(max-width:860px)');
 let previousFocus=null;
 function setMenu(open,restore=true){
  open=!!open&&mobile.matches;
  if(open)previousFocus=document.activeElement;
  drawer.classList.toggle('is-open',open);
  document.body.classList.toggle('menu-open',open);
  trigger.setAttribute('aria-expanded',String(open));
  backdrop.hidden=!open;
  drawer.inert=mobile.matches&&!open;
  document.querySelector('main').inert=open;
  document.querySelector('.mobile-dock').inert=open;
  if(open)document.getElementById('close-menu').focus();
  else if(restore&&previousFocus){previousFocus.focus();previousFocus=null;}
 }
 trigger.addEventListener('click',()=>setMenu(true));
 document.getElementById('close-menu').addEventListener('click',()=>setMenu(false));
 backdrop.addEventListener('click',()=>setMenu(false));
 document.addEventListener('keydown',event=>{
  if(!drawer.classList.contains('is-open'))return;
  if(event.key==='Escape'){event.preventDefault();setMenu(false);}
  if(event.key==='Tab'){
   const items=[...drawer.querySelectorAll('a,button')].filter(el=>!el.hidden&&!el.disabled&&el.getClientRects().length);
   const first=items[0],last=items[items.length-1];
   if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
 });
 document.addEventListener('rainy:page',()=>{
  const wasOpen=drawer.classList.contains('is-open');setMenu(false,false);
  if(wasOpen){/* page visibility changes just after this event */
   requestAnimationFrame(()=>{const h=document.querySelector('.page:not([hidden]) h1');if(h){h.tabIndex=-1;h.focus({preventScroll:true});}});
  }
  requestAnimationFrame(()=>document.querySelectorAll('.nav[data-page]').forEach(el=>{if(el.classList.contains('active'))el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');}));
 });
 mobile.addEventListener('change',()=>setMenu(false,false));
 setMenu(false,false);
 document.querySelectorAll('.nav.active').forEach(el=>el.setAttribute('aria-current','page'));
})();
