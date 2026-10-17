"use strict";
const base = "/wizard-of-wor";
const lobby = document.getElementById("lobby");
const game = document.getElementById("game");
const status = document.getElementById("status");
const canvas = document.getElementById("screen");
const ctx = canvas.getContext("2d", {alpha:false});
const joystick = document.getElementById("joystick");
const knob = document.getElementById("knob");
const fire = document.getElementById("fire");
const controls = {up:false, down:false, left:false, right:false, fire:false};
let ws = null, room = null, sound = null, muted = false, audioTime = 0, sourceRate = 48000;
let frameNumber = 0, appliedFrame = 0, joyPointer = null, firePointer = null;
const perfStats = document.getElementById("perfStats");
const copyStats = document.getElementById("copyStats");
const perf = {
  start: performance.now(), windowStart: performance.now(),
  networkBytes: 0, arrived: 0, painted: 0, decodeTotal: 0, decodeCount: 0,
  lastPaint: 0, rtt: null, worker: null, dropped: 0, queue: 0, report: ""
};
function reportPerf(){
  if(!room)return;
  const now=performance.now();
  const elapsed=Math.max(0.2,(now-perf.windowStart)/1000);
  const netKbps=perf.networkBytes*8/elapsed/1000;
  const recvFps=perf.arrived/elapsed;
  const paintFps=perf.painted/elapsed;
  const worker=perf.worker;
  const emulator=worker ? worker.fps.toFixed(1)+"/"+worker.target_fps.toFixed(1) : "—";
  const screen=worker && worker.luma!==null ? worker.luma.toFixed(0)+"/255 ("+worker.changed_frames+" változás)" : "—";
  const freshness=perf.lastPaint ? ((now-perf.lastPaint)/1000).toFixed(1)+" s" : "nincs kép";
  const rtt=perf.rtt===null ? "—" : perf.rtt.toFixed(0)+" ms";
  const dec=perf.decodeCount ? (perf.decodeTotal/perf.decodeCount).toFixed(1)+" ms" : "—";
  let cause="";
  if(worker && worker.fps < worker.target_fps*0.75) cause=" | Figyelem: lassú emuláció";
  else if(worker && paintFps<8 && worker.video_fps>=15)
    cause=" | Figyelem: képátvitel vagy megjelenítés lassú";
  if(worker && worker.luma < 10 && worker.changed_frames===0)
    cause+=" | A C64 képe sötét, alig változik";
  perf.report="C64: "+emulator+" FPS | átvett: "+recvFps.toFixed(1)+" FPS"
    +" | kirajzolt: "+paintFps.toFixed(1)+" FPS"
    +" | adat: "+netKbps.toFixed(0)+" kbit/s"
    +" | RTT: "+rtt+" | utolsó kép: "+freshness
    +" | dekódolás: "+dec+" | szerver sor: "+perf.queue
    +" | eldobott csomag: "+perf.dropped
    +" | C64 fényerő: "+screen+cause;
  perfStats.textContent=perf.report;
  perf.windowStart=now;
  perf.networkBytes=perf.arrived=perf.painted=perf.decodeTotal=perf.decodeCount=0;
  if(ws && ws.readyState===WebSocket.OPEN)
    ws.send(JSON.stringify({type:"ping",sent:performance.now()}));
}
window.setInterval(reportPerf,2000);
copyStats.addEventListener("click",async ()=>{
  try{
    await navigator.clipboard.writeText(perf.report || perfStats.textContent);
    notice("A mérés kimásolva; ezt beillesztheted a beszélgetésbe.");
  }catch(err){notice("A böngésző nem engedte a másolást: jelöld ki a mérés szövegét.");}
});

ctx.fillStyle = "#090a1e";ctx.fillRect(0,0,canvas.width,canvas.height);
function notice(message){status.textContent = message;}
function resetControls(){Object.keys(controls).forEach(k=>controls[k]=false);updateKnob();sendInput();}
function sendInput(){if(ws && ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:"input",...controls}));}
function updateKnob(){
  const x = (controls.right?1:0)-(controls.left?1:0);
  const y = (controls.down?1:0)-(controls.up?1:0);
  knob.style.left=(50+22*x)+"%"; knob.style.top=(50+22*y)+"%";
  fire.classList.toggle("pressed", controls.fire);
}
function moveStick(event){
  const box=joystick.getBoundingClientRect();
  const x=event.clientX-(box.left+box.width/2), y=event.clientY-(box.top+box.height/2);
  for(const dir of ["up","down","left","right"])controls[dir]=false;
  if(Math.hypot(x,y)>16){
    if(Math.abs(x)>Math.abs(y)){controls[x>0?"right":"left"]=true;}
    else {controls[y>0?"down":"up"]=true;}
  }
  updateKnob();sendInput();
}
joystick.addEventListener("pointerdown",ev=>{if(joyPointer!==null)return;joyPointer=ev.pointerId;joystick.setPointerCapture(ev.pointerId);moveStick(ev);});
joystick.addEventListener("pointermove",ev=>{if(joyPointer===ev.pointerId)moveStick(ev);});
function releaseJoy(ev){if(joyPointer!==ev.pointerId)return;joyPointer=null;
  for(const dir of ["up","down","left","right"])controls[dir]=false;updateKnob();sendInput();}
joystick.addEventListener("pointerup",releaseJoy);joystick.addEventListener("pointercancel",releaseJoy);
joystick.addEventListener("lostpointercapture",releaseJoy);
fire.addEventListener("pointerdown",ev=>{if(firePointer!==null)return;firePointer=ev.pointerId;fire.setPointerCapture(ev.pointerId);controls.fire=true;updateKnob();sendInput();});
function releaseFire(ev){if(firePointer!==ev.pointerId)return;firePointer=null;controls.fire=false;updateKnob();sendInput();}
fire.addEventListener("pointerup",releaseFire);fire.addEventListener("pointercancel",releaseFire);
fire.addEventListener("lostpointercapture",releaseFire);

// Shared keyboard component owns layout and virtual/physical key lifecycles.
const c64Keyboard = window.createC64Keyboard({
  enabled: () => Boolean(room),
  send: (key,down) => {
    if(ws && ws.readyState === WebSocket.OPEN){
      ws.send(JSON.stringify({type:"key",key,down}));
    }
  }
});

const keys={ArrowUp:"up",ArrowDown:"down",ArrowLeft:"left",ArrowRight:"right",Space:"fire"};
document.addEventListener("keydown",ev=>{
  if(!room || ev.altKey || ev.metaKey)return;
  // A physical C64 keyboard is active only while the drawer is open.
  // Escape is RUN/STOP in either state.
  if(c64Keyboard.isOpen() || ev.code==="Escape"){
    if(c64Keyboard.physical(ev,true))return;
  }
  if(ev.target.closest("input,textarea,select,button,a")||ev.target.isContentEditable)return;
  if(!keys[ev.code])return;
  ev.preventDefault();
  if(!controls[keys[ev.code]]){controls[keys[ev.code]]=true;updateKnob();sendInput();}
});
document.addEventListener("keyup",ev=>{
  if(!room)return;
  if(c64Keyboard.physical(ev,false))return;
  if(c64Keyboard.isOpen() || !keys[ev.code])return;
  ev.preventDefault();
  controls[keys[ev.code]]=false;updateKnob();sendInput();
});
window.addEventListener("blur",()=>{resetControls();c64Keyboard.release();});
document.addEventListener("visibilitychange",()=>{if(document.hidden){resetControls();c64Keyboard.release();}});
async function enableSound(){
  if(sound){await sound.resume();return;}
  sound=new (window.AudioContext||window.webkitAudioContext)({latencyHint:"interactive"});
  await sound.resume();audioTime=sound.currentTime+0.1;
}
function audio(data){
  if(!sound||muted||data.byteLength<4)return;
  const samples=new DataView(data.buffer,data.byteOffset,data.byteLength);
  const count=Math.floor(data.byteLength/4);
  if(count<1)return;
  const buffer=sound.createBuffer(2,count,sourceRate);
  const left=buffer.getChannelData(0),right=buffer.getChannelData(1);
  for(let i=0;i<count;i++){left[i]=samples.getInt16(i*4,true)/32768;right[i]=samples.getInt16(i*4+2,true)/32768;}
  const node=sound.createBufferSource();node.buffer=buffer;node.connect(sound.destination);
  if(audioTime<sound.currentTime+0.025||audioTime>sound.currentTime+0.4)audioTime=sound.currentTime+0.09;
  node.start(audioTime);audioTime+=count/sourceRate;
}
async function drawJPEG(payload,id){
  const decodeStart=performance.now();
  try{
    const bitmap=await createImageBitmap(new Blob([payload],{type:"image/jpeg"}));
    perf.decodeTotal+=performance.now()-decodeStart;
    perf.decodeCount++;
    if(id>appliedFrame){
      if(canvas.width!==bitmap.width||canvas.height!==bitmap.height){canvas.width=bitmap.width;canvas.height=bitmap.height;}
      ctx.drawImage(bitmap,0,0);appliedFrame=id;
      perf.lastPaint=performance.now();perf.painted++;
    }
    bitmap.close();
  }catch(err){console.warn("Frame decode failed",err);}
}
function connect(){
  if(ws)ws.close();
  const scheme=location.protocol==="https:"?"wss:":"ws:";
  ws=new WebSocket(scheme+"//"+location.host+base+"/api/rooms/"+room.code+"/ws");
  ws.binaryType="arraybuffer";
  ws.onopen=()=>ws.send(JSON.stringify({token:room.token}));
  ws.onmessage=ev=>{
    if(typeof ev.data==="string"){
      const msg=JSON.parse(ev.data);
      if(msg.type==="welcome"){sourceRate=msg.sample_rate;notice("Csatlakozva. Jó játékot!");}
      if(msg.type==="pong" && typeof msg.sent==="number")perf.rtt=performance.now()-msg.sent;
      if(msg.type==="stats"){
        perf.worker=msg.emulator;
        perf.dropped=msg.network?.dropped??0;
        perf.queue=msg.network?.queue??0;
      }
      if(msg.type==="players"){document.getElementById("players").textContent=
        "1. játékos: "+(msg.connected[0]?"online":"offline")+"  ·  2. játékos: "+(msg.connected[1]?"online":"offline");}
    }else{
      const b=new Uint8Array(ev.data);
      perf.networkBytes+=b.byteLength;
      if(b[0]===86){perf.arrived++;drawJPEG(b.subarray(1),++frameNumber);}
      if(b[0]===65)audio(b.subarray(1));
    }
  };
  ws.onclose=()=>{resetControls();c64Keyboard.release();c64Keyboard.close();notice("Megszakadt a kapcsolat. Frissítsd az oldalt a visszatéréshez.");};
  ws.onerror=()=>notice("Hálózati hiba történt.");
}
function displayRoom(data){
  room=data;perf.worker=null;perf.lastPaint=0;
  perf.windowStart=performance.now();
  sessionStorage.setItem("wizard_room",JSON.stringify(room));
  lobby.classList.add("hidden");game.classList.remove("hidden");
  document.getElementById("code").textContent=room.code;
  document.getElementById("role").textContent=(room.role===0?"1. játékos":"2. játékos");
  history.replaceState({}, "",base+"/"+room.code);
  connect();
}
async function action(path){
  notice("Szoba indítása...");
  const result=await fetch(path,{method:"POST",credentials:"same-origin",headers:{"Accept":"application/json"}});
  const data=await result.json();
  if(!result.ok)throw new Error(data.error||"Nem sikerült a művelet.");
  displayRoom(data);
}
document.getElementById("create").addEventListener("click",async ev=>{
  ev.target.disabled=true;
  try{await enableSound();await action(base+"/api/rooms");}
  catch(err){notice(err.message);ev.target.disabled=false;}
});
document.getElementById("joinForm").addEventListener("submit",async ev=>{
  ev.preventDefault();
  const code=document.getElementById("roomCode").value.trim();
  if(!/^[0-9]{5}$/.test(code))return notice("A szobakód pontosan öt számjegy.");
  try{await enableSound();await action(base+"/api/rooms/"+code+"/join");}
  catch(err){notice(err.message);}
});
document.getElementById("invite").addEventListener("click",async()=>{
  try{await navigator.clipboard.writeText(location.origin+base+"/"+room.code);notice("Meghívó kimásolva.");}
  catch(err){notice("A szobakód: "+room.code);}
});
document.getElementById("mute").addEventListener("click",ev=>{
  muted=!muted;ev.target.textContent=muted?"Hang: KI":"Hang: BE";
  if(!muted)enableSound().catch(()=>{});
});
document.getElementById("fullscreen").addEventListener("click",()=>{
  if(!document.fullscreenElement)game.requestFullscreen().catch(()=>notice("A teljes képernyő nem támogatott."));
  else document.exitFullscreen();
});
document.getElementById("leave").addEventListener("click",()=>{
  c64Keyboard.close();sessionStorage.removeItem("wizard_room");if(ws)ws.close();location.assign(base+"/");
});
const match=location.pathname.match(/\/([0-9]{5})\/?$/);
if(match)document.getElementById("roomCode").value=match[1];
try{
  const stored=JSON.parse(sessionStorage.getItem("wizard_room")||"null");
  if(stored&&/^[0-9]{5}$/.test(stored.code)&&typeof stored.token==="string"&&(!match||stored.code===match[1]))
    displayRoom(stored);
}catch(err){sessionStorage.removeItem("wizard_room");}
