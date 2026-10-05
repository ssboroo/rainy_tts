const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('app/static/app.js','utf8');
const roots={};const make=()=>({children:[],replaceChildren(...x){this.children=x},append(x){this.children.push(x)}});
let resolve;
const context={state:{user:{email:'owner'}},toolKinds:{music:'music',alignment:['alignment','forced_alignment']},toolResultRequests:new Map(),$:id=>roots[id],document:{createElement:make},customerMessage:x=>x,renderHistoryItem:x=>x,rawApi:async()=>({items:[{tool_type:'tts'},{tool_type:'music',id:1},{tool_type:'music',id:2},{tool_type:'music',id:3},{tool_type:'music',id:4}]})};
vm.createContext(context);vm.runInContext(source.slice(source.indexOf('async function loadToolResults('),source.indexOf('async function watchTtsResult(')),context);
(async()=>{roots['music-output-items']=make();await context.loadToolResults('music');assert.equal(roots['music-output-items'].children.length,3);assert.equal(roots['music-output-items'].children[0].id,1);
roots['alignment-output-items']=make();context.rawApi=async()=>({items:[{tool_type:'alignment',id:5},{tool_type:'forced_alignment',id:6}]});await context.loadToolResults('alignment');assert.equal(roots['alignment-output-items'].children.length,2);
context.rawApi=()=>new Promise(r=>resolve=r);const pending=context.loadToolResults('music');context.state.user=null;resolve({items:[{tool_type:'music',id:9}]});await pending;assert.equal(roots['music-output-items'].children[0].id,1);await context.loadToolResults('music');assert.equal(roots['music-output-items'].children.length,1);assert.match(roots['music-output-items'].children[0].textContent,/Нэвтэрсний/);
assert(!source.includes("if(state.page==='history')loadHistory();"));console.log('Tool result filtering, latest-three limit, stale-account isolation and signed-out guidance passed.');})();

const html=fs.readFileSync('app/static/index.html','utf8');assert(html.includes('<option value="story">Ном, өгүүлэмж</option>'));assert(!/<\/option\s+value=/.test(html));
