'use strict';
// Admin-only RAINY knowledge management. All document excerpts are rendered as
// text nodes: uploaded untrusted HTML/script can never execute in the browser.
const workDays=['Даваа','Мягмар','Лхагва','Пүрэв','Баасан','Бямба','Ням'];
for(let hour=0;hour<=23;hour++){
  const label=String(hour).padStart(2,'0')+':00';
  if(hour<=22)$('reception-business-open').add(new Option(label,String(hour)));
  if(hour>=1)$('reception-business-close').add(new Option(label,String(hour)));
}
for(let day=0;day<7;day++){
  const label=document.createElement('label');label.className='field-help';
  const input=document.createElement('input');input.type='checkbox';input.value=String(day);input.checked=day===6;
  label.append(input,document.createTextNode(' '+workDays[day]+' '));
  $('reception-closed-days').append(label);
}
const publicBooking={
  async refresh(){
    if(!state.user?.admin)return;
    try{
      const result=await api('/reception/public-link');
      $('reception-public-status').textContent=result.enabled?
        'Нийтийн захиалга идэвхтэй. Холбоосыг үйлчлүүлэгчид түгээнэ.':'Нийтийн захиалга идэвхгүй. Идэвхжүүлэх үед нууц санамсаргүй холбоос үүснэ.';
      $('reception-public-enable').disabled=result.enabled;
      $('reception-public-disable').disabled=!result.enabled;
      const target=$('reception-public-url');target.replaceChildren();
      if(result.url){
        const address=document.createElement('code');address.textContent=result.url;
        const copy=document.createElement('button');copy.type='button';copy.className='secondary';copy.textContent='Холбоос хуулах';
        copy.onclick=async()=>{await navigator.clipboard.writeText(result.url);notice('Захиалгын холбоос хуулагдлаа.');};
        const link=document.createElement('a');link.href=result.url;link.textContent='Захиалгын хуудас нээх';link.target='_blank';link.rel='noopener noreferrer';
        target.append(address,copy,link);
      }
    }catch(e){$('reception-public-status').textContent=customerMessage(e.message);}
  },
  async set(enabled){
    try{
      const result=await api('/reception/public-link',{method:'POST',body:{enabled}});
      await this.refresh();
      notice(result.enabled?'Захиалгын нийтийн холбоос идэвхтэй.':'Захиалгын холбоос зогслоо.');
    }catch(e){notice(customerMessage(e.message));}
  }
};
$('reception-public-enable').onclick=()=>publicBooking.set(true);
$('reception-public-disable').onclick=()=>{
  if(confirm('Нийтийн захиалгын холбоосыг идэвхгүй болгох уу?'))publicBooking.set(false);
};
const kbUI={
  async business(){
    if(!state.user?.admin)return;
    try{
      const b=await api('/reception/business');
      $('reception-business-open').value=String(b.open_hour??9);
      $('reception-business-close').value=String(b.close_hour??18);
      for(const input of $('reception-closed-days').querySelectorAll('input[type=checkbox]'))
        input.checked=(b.closed_weekdays||[6]).includes(Number(input.value));
      for(const [key,id] of [
        ['name','reception-business-name'],['address','reception-business-address'],
        ['contact_phone','reception-business-phone'],['intro','reception-business-intro']]){
        $(id).value=b[key]||'';
      }
    }catch(e){$('reception-business-status').textContent=customerMessage(e.message);}
  },
  async sources(){
    if(!state.user?.admin)return;
    try{
      const google=await api('/reception/knowledge/google-status');
      $('reception-sheet-status').textContent=google.mode==='service_account'?
        'Private Google Sheets идэвхтэй: '+google.account_email+' имэйлд Sheet-ийн Viewer эрх олгоно. 6 цагийн синк.':
        'Нийтэлсэн CSV холбоос ашиглана. Хувийн Sheet бол админ Google service account тохируулна. 6 цагийн синк.';
      const data=await api('/reception/knowledge/sources');
      const list=$('reception-knowledge-sources');list.replaceChildren();
      if(!data.items.length){list.textContent='Одоогоор баримт оруулаагүй байна.';return;}
      for(const source of data.items){
        const row=document.createElement('div');row.className='ledger-row';
        const title=document.createElement('span');
        title.textContent=source.name+' · '+source.passages+' хэсэг · '+(source.kind==='sheet'?'Google Sheets / 6 цагийн шинэчлэл':'Файл')+
          (source.last_error?' · Анхааруулга: '+source.last_error:'');
        const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Устгах';
        button.onclick=async()=>{
          if(!confirm(source.name+' файлыг мэдлэгийн сангаас устгах уу?'))return;
          try{await api('/reception/knowledge/sources/'+encodeURIComponent(source.id),{method:'DELETE'});
            await kbUI.sources();notice('Баримтын эх сурвалж устлаа.');}
          catch(e){notice(customerMessage(e.message));}
        };
        row.append(title,button);list.append(row);
      }
    }catch(e){$('reception-knowledge-sources').textContent=customerMessage(e.message);}
  },
  async load(){
    await Promise.all([this.business(),this.sources(),publicBooking.refresh()]);
  }
};
document.addEventListener('rainy:page',event=>{
  if(event.detail?.name==='reception'&&state.user?.admin)kbUI.load();
});
$('reception-knowledge-refresh').onclick=()=>kbUI.sources();
$('reception-business-form').onsubmit=async event=>{
  event.preventDefault();if(!state.user?.admin)return;
  const button=event.currentTarget.querySelector('[type=submit]');button.disabled=true;
  try{
    await api('/reception/business',{method:'POST',body:{
      name:$('reception-business-name').value,address:$('reception-business-address').value,
      contact_phone:$('reception-business-phone').value,intro:$('reception-business-intro').value,
      open_hour:Number($('reception-business-open').value),close_hour:Number($('reception-business-close').value),
      closed_weekdays:[...$('reception-closed-days').querySelectorAll('input[type=checkbox]:checked')].map(x=>Number(x.value))
    }});
    $('reception-business-status').textContent='Байгууллагын мэдээлэл хадгалагдлаа.';
  }catch(e){$('reception-business-status').textContent=customerMessage(e.message);}
  finally{button.disabled=false;}
};
$('reception-knowledge-file-form').onsubmit=async event=>{
  event.preventDefault();if(!state.user?.admin)return;
  const file=$('reception-knowledge-file').files?.[0],button=event.currentTarget.querySelector('[type=submit]');
  if(!file)return;
  if(file.size>5*1024*1024){$('reception-knowledge-upload-status').textContent='Файл хамгийн ихдээ 5 MB байна.';return;}
  const form=new FormData();form.append('file',file,file.name);
  button.disabled=true;
  $('reception-knowledge-upload-status').textContent='Файлын агуулгыг шинжилж байна…';
  try{
    const result=await api('/reception/knowledge/upload',{method:'POST',body:form,form:true});
    $('reception-knowledge-upload-status').textContent=result.name+' · '+result.passages+' хэсгийг мэдлэгийн санд хадгаллаа.';
    event.currentTarget.reset();await kbUI.sources();
  }catch(e){$('reception-knowledge-upload-status').textContent=customerMessage(e.message);}
  finally{button.disabled=false;}
};
$('reception-sheet-form').onsubmit=async event=>{
  event.preventDefault();if(!state.user?.admin)return;
  const button=event.currentTarget.querySelector('[type=submit]');button.disabled=true;
  $('reception-sheet-status').textContent='Google Sheets уншиж байна…';
  try{
    const result=await api('/reception/knowledge/sheet',{method:'POST',body:{url:$('reception-sheet-url').value}});
    $('reception-sheet-status').textContent=result.passages+' хэсэг нэмэгдлээ. Хуудсыг 6 цаг тутам автоматаар шинэчилнэ.';
    event.currentTarget.reset();await kbUI.sources();
  }catch(e){$('reception-sheet-status').textContent=customerMessage(e.message);}
  finally{button.disabled=false;}
};
$('reception-knowledge-search-form').onsubmit=async event=>{
  event.preventDefault();if(!state.user?.admin)return;
  const results=$('reception-knowledge-results');results.replaceChildren();
  try{
    const response=await api('/reception/knowledge/search?'+new URLSearchParams({query:$('reception-knowledge-query').value}));
    if(!response.matches.length){results.textContent='Эх сурвалжаас баттай хариу олдсонгүй. Баримтын мэдээллээ шинэчлэх эсвэл ажилтнаас лавлана уу.';return;}
    for(const item of response.matches){
      const row=document.createElement('div');row.className='ledger-row';
      const content=document.createElement('span');content.textContent=item.text;
      const label=document.createElement('small');label.textContent='Эх сурвалж: '+item.source;
      row.append(content,label);results.append(row);
    }
  }catch(e){results.textContent=customerMessage(e.message);}
};
$('reception-time-form').onsubmit=async event=>{
  event.preventDefault();if(!state.user?.admin)return;
  const output=$('reception-time-result');
  try{
    const result=await api('/reception/time/interpret',{method:'POST',body:{text:$('reception-time-query').value}});
    output.textContent=result.confidence==='exact'?
      'Танигдсан: '+result.date+' · '+result.time+' · '+result.timezone+' — Сул цагийг календарь дээр шалгаж баталгаажуулна.':
      'Тодруулга шаардлагатай: '+result.message;
  }catch(e){output.textContent=customerMessage(e.message);}
};
