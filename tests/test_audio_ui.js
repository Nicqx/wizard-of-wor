"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class FakeContext {
  constructor() {
    this.currentTime = 0;
    this.state = "suspended";
    this.destination = {};
    this.nodes = [];
    this.lastBuffer = null;
    FakeContext.instance = this;
  }
  async resume() { this.state = "running"; }
  createBuffer(channels, length, rate) {
    assert.equal(channels,2);
    assert.equal(rate,48000);
    const arr = [new Float32Array(length), new Float32Array(length)];
    this.lastBuffer = {getChannelData: index => arr[index]};
    return this.lastBuffer;
  }
  createBufferSource() {
    const node = {
      playbackRate:{value:1},
      connect(destination){assert.ok(destination);},
      start(at){this.startTime=at;},
    };
    this.nodes.push(node);
    return node;
  }
}
const sandbox={window:{}, console};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("web/assets/audio-stream.js","utf8"),sandbox);
const player=sandbox.window.createC64Audio(FakeContext);
function pcm(samples=960) {
  const out=new Uint8Array(samples*4);
  const view=new DataView(out.buffer);
  for(let i=0;i<samples;i++){
    view.setInt16(i*4, 16384, true);
    view.setInt16(i*4+2, -8192, true);
  }
  return out;
}
(async () => {
  const chunk=pcm();
  player.receive(chunk,48000);
  assert.equal(player.stats().skipped,1); // No user gesture.
  await player.enable();
  const context=FakeContext.instance;
  for(let i=0;i<250;i++){
    // 5s of uninterrupted 20ms SID chunks, with jitter every 25th packet
    // compensated by slightly earlier/later next packet.
    context.currentTime=i*0.02+((i%25===0 && i>0)?0.08:0);
    player.receive(chunk,48000);
  }
  assert.equal(context.nodes.length,250);
  assert.ok(context.nodes[0].startTime>=0.2);
  for(let i=1;i<context.nodes.length;i++){
    assert.ok(context.nodes[i].startTime>context.nodes[i-1].startTime,
      "Audio buffer sources may never overlap or restart backwards");
    assert.ok(context.nodes[i].playbackRate.value>=0.975);
    assert.ok(context.nodes[i].playbackRate.value<=1.025);
  }
  assert.equal(context.lastBuffer.getChannelData(0)[0],0.5);
  assert.equal(context.lastBuffer.getChannelData(1)[0],-0.25);
  assert.equal(player.stats().underflows,0);
  assert.ok(player.stats().leadMs>=100&&player.stats().leadMs<500,
    "Retained jitter buffer should not drift unbounded");
  player.setMuted(true);
  player.receive(chunk,48000);
  assert.equal(context.nodes.length,250);
  player.setMuted(false);
  context.currentTime=5.0;
  player.receive(chunk,48000);
  assert.ok(context.nodes.at(-1).startTime>=5.2);
  player.reset();
  assert.equal(player.stats().underflows,0);
  assert.equal(player.stats().played,0);
  console.log("SID audio continuity, jitter buffer, mute and drift correction: PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});
