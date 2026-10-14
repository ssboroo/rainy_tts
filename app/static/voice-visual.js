'use strict';
/* One responsive audio-reactive sample player per voice card.
   Wave bars are generated from decoded REAL preview PCM (not random animation).
   Playback is the browser's native audio element. Web Audio analyser is optional
   for live amplitude; if unavailable, waveform position still tracks real time.
*/
let activeVoicePreview=null;
function createVoicePreviewPlayer({audio,listen,feedback,voiceName}){
  const box=document.createElement('div');box.className='rv-sample-player';
  const top=document.createElement('div');top.className='rv-sample-head';
  const brand=document.createElement('span');brand.className='rv-sample-label';brand.textContent='◉ VOICE PREVIEW';
  const indicator=document.createElement('span');indicator.className='rv-sample-indicator';indicator.textContent='Сонсох дээж';
  top.append(brand,indicator);
  const wave=document.createElement('div');wave.className='rv-wave';wave.setAttribute('aria-hidden','true');
  const columns=[];
  for(let i=0;i<48;i++){
    const bar=document.createElement('i');bar.className='rv-wave-bar';
    bar.style.setProperty('--rv-peak','12%');wave.append(bar);columns.push(bar);
  }
  const controls=document.createElement('div');controls.className='rv-sample-controls';
  const play=document.createElement('button');play.type='button';play.className='rv-sample-play';play.textContent='▶';
  play.setAttribute('aria-label',voiceName+' дээж тоглуулах');
  const timeline=document.createElement('input');timeline.className='rv-sample-seek';timeline.type='range';timeline.min='0';timeline.max='1000';timeline.step='1';timeline.value='0';timeline.setAttribute('aria-label','Дээжийн явц');
  const clock=document.createElement('span');clock.className='rv-sample-time';clock.textContent='0:00 / 0:00';
  controls.append(play,timeline,clock);box.append(top,wave,controls);
  let frame=0,context=null,analyser=null,source=null,hasPeaks=false,disposed=false,level=0;
  const format=s=>{if(!Number.isFinite(s))return '0:00';return Math.floor(s/60)+':'+String(Math.floor(s%60)).padStart(2,'0')};
  function sync(){
    if(disposed)return;
    const duration=Number.isFinite(audio.duration)?audio.duration:0;
    const ratio=duration>0?Math.max(0,Math.min(1,audio.currentTime/duration)):0;
    timeline.value=String(Math.round(ratio*1000));
    timeline.style.setProperty('--rv-progress',(ratio*100).toFixed(2)+'%');
    clock.textContent=format(audio.currentTime)+' / '+format(duration);
    const played=Math.round(ratio*columns.length);
    for(let i=0;i<columns.length;i++)columns[i].classList.toggle('is-played',i<played);
  }
  function tick(){
    if(disposed||audio.paused){frame=0;return;}
    sync();
    if(analyser){
      const data=new Uint8Array(analyser.fftSize);analyser.getByteTimeDomainData(data);
      let squares=0;
      for(let i=0;i<data.length;i+=4){const v=(data[i]-128)/128;squares+=v*v;}
      level=Math.min(1,Math.sqrt(squares/Math.ceil(data.length/4))*4);
      box.style.setProperty('--rv-audio-level',level.toFixed(3));
    }
    frame=requestAnimationFrame(tick);
  }
  async function graph(){
    if(disposed||context)return;
    const AudioCtx=window.AudioContext||window.webkitAudioContext;
    if(!AudioCtx)return;
    try{
      context=new AudioCtx();
      analyser=context.createAnalyser();analyser.fftSize=512;
      source=context.createMediaElementSource(audio);
      source.connect(analyser);analyser.connect(context.destination);
      await context.resume();
    }catch{
      // Native audio preview must remain usable if Web Audio is unavailable.
      try{await context?.close();}catch{}
      context=null;analyser=null;source=null;
    }
  }
  async function prepareWaveform(blob){
    if(disposed||hasPeaks)return;
    const AudioCtx=window.AudioContext||window.webkitAudioContext;
    if(!AudioCtx)return;
    let decoder;
    try{
      decoder=new AudioCtx();
      const decoded=await decoder.decodeAudioData(await blob.arrayBuffer());
      if(disposed)return;
      const data=decoded.getChannelData(0),samples=data.length,chunk=Math.max(1,Math.floor(samples/columns.length));
      for(let i=0;i<columns.length;i++){
        const start=i*chunk,end=Math.min(samples,start+chunk),step=Math.max(1,Math.floor(chunk/220));
        let power=0,count=0;
        for(let j=start;j<end;j+=step){power+=data[j]*data[j];count++;}
        const rms=Math.sqrt(power/Math.max(1,count));
        const height=Math.min(95,Math.max(9,Math.round(12+rms*270)));
        columns[i].style.setProperty('--rv-peak',height+'%');
      }
      hasPeaks=true;
    }catch{
      // A codec may play natively even when decodeAudioData cannot decode it.
      indicator.textContent='Дээж бэлэн';
    }finally{try{await decoder?.close();}catch{}}
  }
  function onPlay(){
    if(activeVoicePreview&&activeVoicePreview!==player)activeVoicePreview.pause();
    activeVoicePreview=player;play.textContent='Ⅱ';play.setAttribute('aria-label','Түр зогсоох');
    indicator.textContent='ДУУ ТОГЛОЖ БАЙНА';box.classList.add('is-playing');
    cancelAnimationFrame(frame);frame=requestAnimationFrame(tick);
    if(context?.state==='suspended')context.resume().catch(()=>{});
  }
  function onPause(){
    play.textContent='▶';play.setAttribute('aria-label',voiceName+' дээж тоглуулах');
    indicator.textContent='Түр зогссон';box.classList.remove('is-playing');
    cancelAnimationFrame(frame);frame=0;box.style.setProperty('--rv-audio-level','0');
    if(activeVoicePreview===player)activeVoicePreview=null;sync();
  }
  function onEnd(){onPause();indicator.textContent='Дахин сонсох';}
  function onError(){onPause();indicator.textContent='Дээж олдсонгүй';}
  async function toggle(){
    if(disposed)return;
    if(!audio.paused){audio.pause();return;}
    try{
      // Begin WebAudio inside real click gesture before awaiting network.
      graph();
      if(audio.src){await audio.play();}
      else listen.click(); // Existing authenticated preview endpoint and errors.
    }catch(e){feedback.hidden=false;feedback.textContent=String(e.message||'Тоглуулж чадсангүй.');}
  }
  play.onclick=toggle;
  wave.onclick=event=>{
    if(!Number.isFinite(audio.duration)||audio.duration<=0)return;
    const rect=wave.getBoundingClientRect(),ratio=(event.clientX-rect.left)/Math.max(1,rect.width);
    audio.currentTime=Math.max(0,Math.min(audio.duration,ratio*audio.duration));sync();
  };
  timeline.oninput=()=>{if(Number.isFinite(audio.duration)&&audio.duration>0){audio.currentTime=audio.duration*Number(timeline.value)/1000;sync();}};
  audio.addEventListener('play',onPlay);audio.addEventListener('pause',onPause);
  audio.addEventListener('ended',onEnd);audio.addEventListener('error',onError);
  audio.addEventListener('timeupdate',sync);audio.addEventListener('loadedmetadata',sync);
  const player={root:box,prepareWaveform,pause:()=>audio.pause(),dispose:()=>{
    if(disposed)return;disposed=true;cancelAnimationFrame(frame);audio.pause();
    if(activeVoicePreview===player)activeVoicePreview=null;
    try{source?.disconnect();analyser?.disconnect();}catch{}
    try{context?.close();}catch{}
    context=null;
  }};
  return player;
}
