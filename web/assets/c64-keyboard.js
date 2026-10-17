"use strict";
/* Reusable Commodore 64 touch/physical keyboard. Networking belongs to the
 * hosting game's adapter; this component only emits named key transitions.
 * Build: KB2. No external dependencies or C64 ROM assets.
 */
(function () {
  const rows = [
    ["BACKARROW","1","2","3","4","5","6","7","8","9","0","PLUS","MINUS","POUND","HOME","DEL"],
    ["CTRL","Q","W","E","R","T","Y","U","I","O","P","AT","ASTERISK","UPARROW"],
    ["RUN_STOP","SHIFT_LOCK","A","S","D","F","G","H","J","K","L","COLON","SEMICOLON","EQUALS","RETURN"],
    ["COMMODORE","SHIFT","Z","X","C","V","B","N","M","COMMA","PERIOD","SLASH","SHIFT"],
    ["RESTORE","F1","F3","F5","F7","SPACE","LEFT","DOWN","UP","RIGHT"]
  ];
  const names = {
    RUN_STOP:"RUN/STOP", SHIFT_LOCK:"SHIFT LOCK", COMMODORE:"C=", CTRL:"CTRL",
    RESTORE:"RESTORE", HOME:"CLR/HOME", DEL:"INST/DEL", RETURN:"RETURN",
    PLUS:"+",MINUS:"−",ASTERISK:"*",AT:"@", COLON:":", SEMICOLON:";",
    EQUALS:"=",COMMA:",",PERIOD:".",SLASH:"/",POUND:"£",
    BACKARROW:"←",UPARROW:"↑",SPACE:"SPACE",
    LEFT:"◀",RIGHT:"▶",UP:"▲",DOWN:"▼"
  };
  const physical = {
    Escape:"RUN_STOP", Enter:"RETURN", NumpadEnter:"RETURN",
    Backspace:"DEL", Home:"HOME", PageUp:"RESTORE", Space:"SPACE",
    ShiftLeft:"SHIFT", ShiftRight:"SHIFT", ControlLeft:"COMMODORE",
    ArrowUp:"UP",ArrowDown:"DOWN",ArrowLeft:"LEFT",ArrowRight:"RIGHT",
    F1:"F1",F3:"F3",F5:"F5",F7:"F7",
    Backquote:"BACKARROW", BracketLeft:"AT", BracketRight:"ASTERISK",
    Minus:"MINUS", Equal:"PLUS", Semicolon:"SEMICOLON", Quote:"COLON",
    Comma:"COMMA", Period:"PERIOD", Slash:"SLASH", Backslash:"EQUALS"
  };
  const physicalKey = code => {
    if (/^Key[A-Z]$/.test(code)) return code.slice(3);
    if (/^Digit[0-9]$/.test(code)) return code.slice(5);
    return physical[code] || null;
  };

  window.createC64Keyboard = function createC64Keyboard(options) {
    const root = document.getElementById("virtualKeyboard");
    const toggle = document.getElementById("keyboardToggle");
    const quick = document.getElementById("runstop");
    const closeButton = document.getElementById("keyboardClose");
    const backdrop = document.getElementById("keyboardBackdrop");
    const keysContainer = document.getElementById("keyboardRows");
    if (![root,toggle,quick,closeButton,backdrop,keysContainer].every(Boolean)) {
      throw new Error("Missing C64 keyboard UI element");
    }
    let open = false;
    let previouslyFocused = null;
    const sources = new Map();
    let serial = 0;
    const send = (key,down) => {
      if (options.enabled()) options.send(key,down);
    };
    const setSource = (key,source,down) => {
      let held = sources.get(key);
      if (!held) { held = new Set(); sources.set(key,held); }
      const before = held.size > 0;
      if (down) held.add(source);
      else held.delete(source);
      const after = held.size > 0;
      if (before !== after) send(key,after);
      if (!after) sources.delete(key);
    };
    const releaseAll = () => {
      for (const key of sources.keys()) send(key,false);
      sources.clear();
    };
    const attachButton = (button,key) => {
      const source = "touch-" + (++serial);
      let pointer = null;
      const finish = ev => {
        if (pointer !== ev.pointerId) return;
        pointer = null;
        button.classList.remove("down");
        setSource(key,source,false);
      };
      button.addEventListener("pointerdown", ev => {
        if (!options.enabled() || pointer !== null) return;
        ev.preventDefault();
        pointer = ev.pointerId;
        button.setPointerCapture(pointer);
        button.classList.add("down");
        setSource(key,source,true);
      });
      button.addEventListener("pointerup",finish);
      button.addEventListener("pointercancel",finish);
      button.addEventListener("lostpointercapture",finish);
      // Keyboard-accessible button activation (Enter/Space).
      button.addEventListener("click",ev => {
        if (ev.detail !== 0 || !options.enabled()) return;
        setSource(key,source,true);
        window.setTimeout(() => setSource(key,source,false),120);
      });
    };
    rows.forEach(items => {
      const line = document.createElement("div");
      line.className = "keyboard-row";
      for (const key of items) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "c64-key" + (key === "SPACE" ? " wide" : "");
        button.textContent = names[key] || key;
        button.setAttribute("aria-label",key==="RUN_STOP"?"C64 RUN/STOP":button.textContent);
        button.dataset.c64Key = key;
        attachButton(button,key);
        line.append(button);
      }
      keysContainer.append(line);
    });
    attachButton(quick,"RUN_STOP");
    const setOpen = value => {
      if (open === value) return;
      open = value;
      if (open) previouslyFocused = document.activeElement;
      else releaseAll();
      root.classList.toggle("hidden",!open);
      document.body.classList.toggle("keyboard-visible",open);
      toggle.setAttribute("aria-expanded",String(open));
      toggle.textContent = open ? "⌨ Billentyűzet bezárása" : "⌨ Billentyűzet megnyitása";
      if (open) closeButton.focus({preventScroll:true});
      else if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus({preventScroll:true});
    };
    toggle.addEventListener("click", () => setOpen(!open));
    closeButton.addEventListener("click", () => setOpen(false));
    backdrop.addEventListener("click", () => setOpen(false));
    return {
      isOpen: () => open,
      release: releaseAll,
      close: () => setOpen(false),
      physical: (ev,down) => {
        // When closed, only Escape belongs to C64; arrows/space stay joystick.
        if (!open && ev.code !== "Escape") return false;
        const key = physicalKey(ev.code);
        if (!key || ev.altKey || ev.metaKey) return false;
        ev.preventDefault();
        if (down && ev.repeat) return true;
        setSource(key,"physical-"+ev.code,down);
        return true;
      }
    };
  };
}());
