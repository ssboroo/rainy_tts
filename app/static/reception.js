'use strict';
// RAINY receptionist UI: web admin books real slots; ElevenAgents voice preview
// is only enabled when the provider agent is explicitly configured and metered.
const receptionUI={
  pendingKey:null,
  lastPayload:null,
  async refreshServices(){
    if(!state.user?.admin)return;
    try{
      const response=await api('/reception/services');
      const selected=$('reception-service-select').value;
      $('reception-service-select').replaceChildren();
      $('reception-services-list').replaceChildren();
      for(const service of response.items){
        const option=new Option(service.name+' · '+service.duration_minutes+' мин · '+Number(service.price_mnt).toLocaleString('mn-MN')+'₮',service.id);
        $('reception-service-select').add(option);
        const item=document.createElement('div');item.className='ledger-row';
        item.textContent=service.name+' · '+service.duration_minutes+' минут · '+Number(service.price_mnt).toLocaleString('mn-MN')+'₮';
        $('reception-services-list').append(item);
      }
      if(response.items.some(item=>item.id===selected))$('reception-service-select').value=selected;
      await receptionUI.refreshSlots();
    }catch(e){$('reception-slot-status').textContent=customerMessage(e.message);}
  },
  async refreshSlots(){
    const serviceId=$('reception-service-select').value, day=$('reception-book-date').value;
    $('reception-book-time').replaceChildren();
    if(!serviceId||!day){$('reception-slot-status').textContent='Өдөр болон үйлчилгээг сонгоно уу.';return;}
    $('reception-slot-status').textContent='Сул цаг шалгаж байна…';
    try{
      const key=serviceId+'|'+day;
      const result=await api('/reception/availability?'+new URLSearchParams({service_id:serviceId,date:day}).toString());
      if(key!==$('reception-service-select').value+'|'+$('reception-book-date').value)return;
      for(const time of result.slots)$('reception-book-time').add(new Option(time,time));
      $('reception-slot-status').textContent=result.slots.length?'Бодит сул цаг: '+result.slots.length+' · Улаанбаатарын цагаар':'Энэ өдөр сул цаг байхгүй.';
    }catch(e){$('reception-slot-status').textContent=customerMessage(e.message);}
  },
  async refreshBookings(){
    if(!state.user?.admin)return;
    try{
      const response=await api('/reception/appointments');
      const list=$('reception-bookings-list');list.replaceChildren();
      if(!response.items.length){list.textContent='Одоогоор захиалга бүртгэгдээгүй байна.';return;}
      for(const item of response.items){
        const row=document.createElement('div');row.className='ledger-row';
        const info=document.createElement('span');
        info.textContent=item.date+' · '+item.time+' · '+item.service_name+' · '+item.caller_name+' · '+item.phone+' · '+(item.status==='booked'?'Баталгаажсан':'Цуцлагдсан');
        row.append(info);
        if(item.status==='booked'){
          const button=document.createElement('button');button.className='secondary';button.type='button';button.textContent='Цуцлах';
          button.onclick=async()=>{
            if(!confirm(item.caller_name+'-ийн '+item.date+' '+item.time+' цагийг цуцлах уу?'))return;
            try{await api('/reception/appointments/'+encodeURIComponent(item.id)+'/cancel',{method:'POST',body:{}});
              await receptionUI.refreshBookings();await receptionUI.refreshSlots();}
            catch(e){notice(customerMessage(e.message));}
          };
          row.append(button);
        }
        list.append(row);
      }
    }catch(e){$('reception-bookings-list').textContent=customerMessage(e.message);}
  },
  async status(){
    const target=$('reception-agent-availability');
    if(!state.user?.admin){target.textContent='Энэ хэсэг зөвхөн админд харагдана.';return;}
    try{
      const status=await api('/production/agent-status');
      target.textContent=status.enabled?
        'Live AI Agent идэвхтэй. “AI-тай шууд ярих” дарснаар ElevenLabs минутын төлбөртэй туршилт эхэлнэ.':
        'Шууд ярьдаг AI агент идэвхгүй. ElevenLabs Agent ID болон LIVE_AGENT_ADMIN_PREVIEW_ENABLED=true шаардлагатай. Календарь болон webhook нь тусдаа ажиллана.';
    }catch(e){target.textContent=customerMessage(e.message);}
  }
};
const oldAgent=$('voice-agent-preview'),agentTarget=$('reception-agent-target');
if(oldAgent&&agentTarget)agentTarget.append(oldAgent);
$('reception-service-select').onchange=()=>{receptionUI.pendingKey=null;receptionUI.refreshSlots();};
$('reception-book-date').onchange=()=>{receptionUI.pendingKey=null;receptionUI.refreshSlots();};
for(const id of ['reception-book-time','reception-book-name','reception-book-phone'])
  $(id).addEventListener('input',()=>{receptionUI.pendingKey=null;});
$('reception-service-form').onsubmit=async event=>{
  event.preventDefault();if(!state.user?.admin)return;
  const button=event.currentTarget.querySelector('[type=submit]');button.disabled=true;
  try{
    const form=new FormData(event.currentTarget);
    await api('/reception/services',{method:'POST',body:{
      name:form.get('name'),duration_minutes:Number(form.get('duration_minutes')),price_mnt:Number(form.get('price_mnt'))
    }});
    event.currentTarget.reset();await receptionUI.refreshServices();notice('Шинэ үйлчилгээ бодитоор бүртгэгдлээ.');
  }catch(e){notice(customerMessage(e.message));}finally{button.disabled=false;}
};
$('reception-booking-form').onsubmit=async event=>{
  event.preventDefault();if(!state.user?.admin)return;
  const button=event.currentTarget.querySelector('[type=submit]');button.disabled=true;
  try{
    if(!$('reception-book-time').value)throw new Error('Эхлээд бодит сул цаг сонгоно уу.');
    if(!receptionUI.pendingKey)receptionUI.pendingKey=crypto.randomUUID().replaceAll('-','');
    const payload={
      service_id:$('reception-service-select').value,date:$('reception-book-date').value,
      time:$('reception-book-time').value,caller_name:$('reception-book-name').value,
      phone:$('reception-book-phone').value,request_id:receptionUI.pendingKey
    };
    const result=await api('/reception/appointments',{method:'POST',body:payload});
    $('reception-booking-status').textContent='Баталгаажсан: '+result.date+' '+result.time+' · Захиалгын дугаар: '+result.id;
    receptionUI.pendingKey=null;
    await receptionUI.refreshBookings();
    await receptionUI.refreshSlots();
  }catch(e){$('reception-booking-status').textContent=customerMessage(e.message);}
  finally{button.disabled=false;}
};
$('reception-bookings-refresh').onclick=()=>receptionUI.refreshBookings();
document.addEventListener('rainy:page',event=>{
  if(event.detail?.name==='reception'&&state.user?.admin){
    receptionUI.refreshServices();receptionUI.refreshBookings();receptionUI.status();
  }
});
