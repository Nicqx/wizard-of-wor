"use strict";
const assert = require("node:assert/strict");

class MockElement {
  constructor(id="") {
    this.id=id; this.attributes={}; this.handlers={};this.children=[];
    this.dataset={}; this.textContent=""; this.type="button";
    this.className=""; this.classList={
      contains: name => this.className.split(" ").includes(name),
      toggle: (name,enabled) => {
        const parts=new Set(this.className.split(" ").filter(Boolean));
        if(enabled)parts.add(name); else parts.delete(name);
        this.className=[...parts].join(" ");
      },
      add: name => this.classList.toggle(name,true),
      remove: name => this.classList.toggle(name,false),
    };
  }
  addEventListener(name,fn){(this.handlers[name]??=[]).push(fn);}
  emit(name,options={}){
    const event={detail:1,pointerId:1,code:"",repeat:false,altKey:false,
      metaKey:false,preventDefault(){this.defaultPrevented=true;},...options};
    for(const fn of this.handlers[name]??[])fn(event);
    return event;
  }
  append(child){this.children.push(child);}
  setAttribute(k,v){this.attributes[k]=v;}
  setPointerCapture(){}
  focus(){document.activeElement=this;}
}
const els={};
for(const id of ["virtualKeyboard","keyboardToggle","keyboardClose",
                 "keyboardBackdrop","keyboardRows"]){
  els[id]=new MockElement(id);
}
els.virtualKeyboard.classList.add("hidden");
global.document={
  activeElement:els.keyboardToggle,
  body:new MockElement("body"),
  createElement:()=>new MockElement(),
  getElementById:id=>els[id]||null
};
global.window={setTimeout:setTimeout};
require("../web/assets/c64-keyboard.js");
const messages=[];
const keyboard=window.createC64Keyboard({
  enabled:()=>true,
  send:(key,down)=>messages.push({key,down})
});
assert.equal(keyboard.isOpen(),false);
assert.equal(els.keyboardToggle.textContent,"");
assert.ok(els.keyboardRows.children.length>=5);
els.keyboardToggle.emit("click");
assert.equal(keyboard.isOpen(),true);
assert.equal(els.virtualKeyboard.classList.contains("hidden"),false);
assert.equal(els.keyboardToggle.attributes["aria-expanded"],"true");
assert.match(els.keyboardToggle.textContent,/bezárása/);
const runKey=els.keyboardRows.children.flatMap(r=>r.children)
  .find(button=>button.dataset.c64Key==="RUN_STOP");
assert.ok(runKey);
runKey.emit("pointerdown");
runKey.emit("pointerup");
assert.deepEqual(messages.slice(-2),[
  {key:"RUN_STOP",down:true},{key:"RUN_STOP",down:false}
]);
const enter={code:"Enter",altKey:false,metaKey:false,repeat:false,
  preventDefault(){this.prevented=true;}};
assert.equal(keyboard.physical(enter,true),true);
assert.equal(keyboard.physical(enter,false),true);
assert.deepEqual(messages.slice(-2),[
  {key:"RETURN",down:true},{key:"RETURN",down:false}
]);
const letter={...enter,code:"KeyA"};
keyboard.physical(letter,true);
els.keyboardClose.emit("click");
assert.equal(keyboard.isOpen(),false);
assert.equal(els.virtualKeyboard.classList.contains("hidden"),true);
assert.equal(messages.at(-1).key,"A");
assert.equal(messages.at(-1).down,false);
const joy={...enter,code:"Space"};
assert.equal(keyboard.physical(joy,true),false); // remains joystick
assert.equal(keyboard.physical({...enter,code:"Escape"},true),true);
assert.equal(keyboard.physical({...enter,code:"Escape"},false),true);
assert.deepEqual(messages.slice(-2),[
  {key:"RUN_STOP",down:true},{key:"RUN_STOP",down:false}
]);
console.log("C64 keyboard modal, key events, RUN/STOP inside keyboard and joystick isolation: PASS");
