"use strict";
/* Regression: a WebSocket that fails during an old room token must bring the
 * user back to the lobby, not leave a black C64 canvas forever. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("web/assets/app.js", "utf8");
const start = source.indexOf("function returnToLobby(");
const end = source.indexOf("function displayRoom(", start);
assert.ok(start > -1 && end > start);
class MockWs {
  static OPEN = 1;
  constructor(url) {
    this.url = url;
    this.readyState = MockWs.OPEN;
    this.sent = [];
    this.closed = false;
    this.binaryType = "blob";
    MockWs.last = this;
  }
  send(payload) {this.sent.push(JSON.parse(payload));}
  close() {this.closed = true;}
}
const state = {};
const cls = name => ({
  add: value => {state[name + "-" + value] = "added";},
  remove: value => {state[name + "-" + value] = "removed";}
});
const events = [];
const sandbox = {
  WebSocket: MockWs,
  location: {protocol:"https:",host:"pmqxyz.hopto.org"},
  perfStats: {textContent:""},
  perf: {connection:"",rtt:null,worker:null,queue:0,dropped:0},
  sourceRate: 0,
  frameNumber: 0,
  base: "/wizard-of-wor",
  room: {code:"12345",token:"private-token"},
  ws: null,
  game: {classList:cls("game")},
  lobby: {classList:cls("lobby")},
  c64Keyboard: {release:()=>events.push("release"),close:()=>events.push("close")},
  resetControls:()=>events.push("reset"),
  sessionStorage: {removeItem: id=>events.push("clear:"+id)},
  history: {replaceState:(_,__,path)=>events.push("location:"+path)},
  notice: message=>events.push("notice:"+message),
  document: {getElementById:()=>({disabled:true,textContent:""})},
  performance: {now:()=>300},
  window: {setTimeout:()=>1,clearTimeout:()=>{}},
  drawJPEG:()=>{},audio:()=>{},
  console
};
vm.createContext(sandbox);
vm.runInContext(source.slice(start,end),sandbox);
sandbox.connect();
const old = MockWs.last;
assert.equal(old.url, "wss://pmqxyz.hopto.org/wizard-of-wor/api/rooms/12345/ws");
old.onopen();
assert.equal(old.sent[0].token, "private-token");
assert.ok(!old.url.includes("private-token"));
old.onclose({code:1006});
assert.ok(events.includes("clear:wizard_room"));
assert.ok(events.includes("location:/wizard-of-wor/"));
assert.equal(state["game-hidden"],"added");
assert.equal(state["lobby-hidden"],"removed");
assert.ok(events.some(x=>x.includes("korábbi szoba")));
assert.equal(sandbox.room, null);
// Even a formerly authenticated connection must release its black screen.
sandbox.room={code:"54321",token:"second-token"};
sandbox.connect();
const second=MockWs.last;
second.onopen();
second.onmessage({data:JSON.stringify({type:"welcome",sample_rate:48000})});
assert.equal(sandbox.perf.connection,"kapcsolódva");
second.onclose({code:1001});
assert.equal(sandbox.room,null);
assert.ok(events.some(x=>x.includes("kapcsolat megszakadt")));
console.log("Expired/reloaded WebSocket returns to lobby: PASS");
