'use strict';
const $=id=>document.getElementById(id);
const key=new URLSearchParams(location.search).get('key')||'';
let slotsKey='',requestId=null;
function mnDate(){
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Ulaanbaatar',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const get=type=>parts.find(p=>p.type===type)?.value||'';
  return get('year')+'-'+get('month')+'-'+get('day');
}
async function call(path,options){
  const response=await fetch('/api/public/reception/'+encodeURIComponent(key)+path,options);
  let data;try{data=await response.json()}catch{data={}};
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Үйлдэл амжилтгүй. Дахин оролдоно уу.');
  return data;
}
async function slots(){
  $('time').replaceChildren();
  $('availability').textContent='';
  if(!$('service').value||!$('date').value)return;
  const query=new URLSearchParams({service_id:$('service').value,date:$('date').value});
  const marker=query.toString();slotsKey=marker;
  $('availability').textContent='Сул цаг шалгаж байна…';
  try{
    const result=await call('/availability?'+query);
    if(slotsKey!==marker)return;
    for(const time of result.slots)$('time').add(new Option(time,time));
    $('availability').textContent=result.slots.length?
      'Улаанбаатарын цагаар '+result.slots.length+' сул цаг байна.':'Энэ өдөр сул цаг байхгүй. Өөр өдөр сонгоно уу.';
  }catch(e){$('availability').textContent=e.message;}
}
$('service').onchange=()=>{requestId=null;slots();};
$('date').onchange=()=>{requestId=null;slots();};
for(const id of ['time','caller-name','caller-phone']){
  $(id).oninput=()=>{requestId=null;};
}
$('public-booking-form').onsubmit=async event=>{
  event.preventDefault();const button=$('book');button.disabled=true;
  try{
    if(!requestId)requestId=crypto.randomUUID().replaceAll('-','');
    const body={
      service_id:$('service').value,date:$('date').value,time:$('time').value,
      caller_name:$('caller-name').value,phone:$('caller-phone').value,
      request_id:requestId,confirmed:$('consent').checked
    };
    const result=await call('/book',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    $('booking-status').textContent='Таны цаг амжилттай баталгаажлаа: '+result.date+' '+result.time+' · Дугаар: '+result.id;
    requestId=null;
    $('consent').checked=false;
    await slots();
  }catch(e){$('booking-status').textContent=e.message;}
  finally{button.disabled=false;}
};
async function init(){
  $('date').min=mnDate();$('date').value=mnDate();
  try{
    if(!/^[A-Za-z0-9_-]{30,70}$/.test(key))throw new Error('invalid');
    const data=await call('');
    const b=data.business||{};
    $('business-name').textContent=b.name||'Үйлчилгээний цаг захиалах';
    $('business-intro').textContent=b.intro||'Тохирох үйлчилгээ, цагийг сонгоод баталгаажуулна уу.';
    $('business-address').textContent=b.address||'';
    $('business-phone').textContent=b.contact_phone?'☎ '+b.contact_phone:'';
    $('business-hours').textContent=String(b.open_hour).padStart(2,'0')+':00–'+String(b.close_hour).padStart(2,'0')+':00 · Монголын цагаар';
    for(const service of data.services||[])
      $('service').add(new Option(service.name+' · '+service.duration_minutes+' минут · '+Number(service.price_mnt).toLocaleString('mn-MN')+'₮',service.id));
    $('booking-content').hidden=false;
    await slots();
  }catch{$('page-error').hidden=false;$('business-intro').textContent='Байгууллагын холбоосоор дахин нэвтэрнэ үү.';}
}
init();
