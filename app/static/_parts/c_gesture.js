/* ---------------- Hand-gesture control (admin / manager roles · every theme · laptop, PC or mobile with a camera)
   The camera starts only after tapping ✋; every frame is processed in this browser by the self-hosted
   MediaPipe Hands model (/hands/...). Nothing from the camera is sent anywhere.
   ONE HAND   point = move cursor · quick pinch (thumb+index) = click / tap
              pinch + hold still ¾ s on a screen/card = EXPAND it · hold again = COMPRESS (back to normal)
              pinch a title bar and move = drag it · pinch elsewhere and move = scroll
              open palm SLIDE left / right = next / previous screens (hologram themes) or next / previous look (Aurora / Arc)
              open palm SLIDE up / down = scroll the page / chat / table under the cursor up / down
              ✌ hold = add a hologram screen · three fingers swipe = change theme · fist 1 s = close all screens
   TWO HANDS  pinch with both hands on a screen/card, then: pull apart = ZOOM IN · push together = ZOOM OUT
              turn both hands like a steering wheel = SPIN it (let go near 0° and it snaps straight)
   Once switched on, ✋ stays on for the next sign-ins on that device (until you switch it off). */
const Gesture = (() => {
  const LOCAL = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(location.hostname);
  let btn, cur, hud, vid, cvs, ctx, hands, stream, running = false, busy = false, raf = 0;
  let sx = 0, sy = 0, pinched = false, pin = null, palmHist = [], fistAt = 0, vAt = 0, triHist = [], lastSwipe = 0, hoverEl = null, lastSeen = 0;

  const css = `
  #gestBtn.on{background:rgba(0,229,255,.22);box-shadow:0 0 14px rgba(0,229,255,.6)}
  #gCur{position:fixed;left:0;top:0;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;z-index:2147483000;pointer-events:none;
    border:2px solid #00e5ff;box-shadow:0 0 12px #00e5ff,inset 0 0 8px rgba(0,229,255,.6);transition:width .12s,height .12s,margin .12s,background .12s;display:none}
  #gCur.pinch{width:16px;height:16px;margin:-8px 0 0 -8px;background:rgba(0,229,255,.85)}
  #gCur.drag{border-color:#ffb547;box-shadow:0 0 14px #ffb547;background:rgba(255,181,71,.6)}
  #gCur.lost{opacity:.25}
  #gCam{position:fixed;left:calc(50% - 110px);bottom:14px;width:220px;height:165px;min-width:140px;min-height:105px;max-width:90vw;max-height:70vh;
    z-index:2147482999;border-radius:10px;overflow:hidden;display:none;resize:both;
    border:1px solid rgba(0,229,255,.55);box-shadow:0 0 18px rgba(0,229,255,.25);background:#020a12}
  #gBar{position:absolute;left:0;right:0;top:0;height:24px;z-index:2;display:flex;align-items:center;gap:6px;padding:0 6px;cursor:move;touch-action:none;
    background:linear-gradient(rgba(0,10,20,.9),rgba(0,10,20,.35));font:700 10px/1 var(--ui,system-ui);letter-spacing:.1em;color:#bff6ff;user-select:none}
  #gBar .gdot{width:7px;height:7px;border-radius:50%;background:#ff4d5e;box-shadow:0 0 8px #ff4d5e}
  #gBar button{margin-left:auto;cursor:pointer;border:1px solid rgba(255,90,100,.7);background:rgba(120,10,20,.55);color:#ffd6da;
    border-radius:6px;font:700 10px/1 var(--ui,system-ui);padding:3px 7px}
  #gBar button:hover{background:rgba(200,20,40,.8)}
  #gestBtn{white-space:nowrap}
  #gCam video,#gCam canvas{position:absolute;inset:0;width:100%;height:100%;transform:scaleX(-1);object-fit:cover}
  #gCam video{opacity:.55}
  #gHud{position:absolute;left:0;right:0;bottom:0;padding:3px 8px;font:600 10px/1.4 var(--ui,system-ui);letter-spacing:.08em;color:#bff6ff;
    background:linear-gradient(transparent,rgba(0,10,20,.85));text-transform:uppercase}
  .ghover{outline:2px solid rgba(0,229,255,.75)!important;outline-offset:2px}
  .gexp{position:fixed!important;inset:5vh 4vw!important;width:auto!important;height:auto!important;max-height:none!important;z-index:9000!important;overflow:auto!important;
    box-shadow:0 30px 120px rgba(0,0,0,.65),0 0 0 2px rgba(0,229,255,.55)!important;scale:1!important;rotate:0deg!important}
  .gzoom{transition:scale .08s linear,rotate .08s linear;will-change:scale,rotate}`;

  const allowed = () => (LOCAL || !ME?.gesture_local_only) && !!ME && !!ME.power             // admin / manager roles only (POWER_ROLES)
    && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

  function init(){
    if (btn || !allowed()) return;
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    btn = document.createElement("button");
    btn.className = "hb ritem"; btn.id = "gestBtn"; btn.type = "button";
    btn.innerHTML = '<svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12"/><path d="M11 11.5v-7a1.5 1.5 0 0 1 3 0V12"/><path d="M14 11.5V6a1.5 1.5 0 0 1 3 0v7"/><path d="M17 9.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-1a7 7 0 0 1-5.4-2.6L3.3 15a1.5 1.5 0 0 1 2.3-2l2.4 2.5"/></svg><span>Hand gestures</span>';
    btn.title = "Camera ON / OFF — hand-gesture control (the camera picture never leaves this device)";
    btn.setAttribute("aria-label", "Camera on or off");
    const where = document.querySelector(".tright .sndwrap") || document.querySelector(".tright");
    where.parentNode.insertBefore(btn, where.nextSibling);
    btn.onclick = e => { e.stopPropagation(); if (running) { remember(false); stop(); } else start(); };
    cur = document.createElement("div"); cur.id = "gCur";
    const cam = document.createElement("div"); cam.id = "gCam";
    cam.innerHTML = `<div id="gBar" title="Drag to move · double-click = back to centre bottom · drag the corner to resize"><span class="gdot"></span>CAMERA<button type="button" id="gOff">⏻ OFF</button></div>`
      + `<video playsinline muted></video><canvas width="320" height="240"></canvas><div id="gHud">starting…</div>`;
    document.body.append(cur, cam);
    cam.querySelector("#gOff").onclick = e => { e.stopPropagation(); remember(false); stop(); };
    dragCam(cam);
    vid = cam.querySelector("video"); cvs = cam.querySelector("canvas"); ctx = cvs.getContext("2d"); hud = cam.querySelector("#gHud");
    document.addEventListener("keydown", e => { if (e.key === "Escape" && running) { remember(false); stop(); } });
    document.addEventListener("visibilitychange", () => { if (document.hidden && running) stop(); else if (!document.hidden && !running && wanted()) start(); });
    if (wanted()) setTimeout(start, 1200);                                           // was on last time -> camera comes back by itself
  }
  // camera window: centre bottom by default, drag the bar to move it, corner to resize; place remembered on this device
  function dragCam(cam){
    const bar = cam.querySelector("#gBar");
    const put = p => { if (!p) { cam.style.left = ""; cam.style.top = ""; cam.style.bottom = ""; return; }
      const w = cam.offsetWidth || 220, h = cam.offsetHeight || 165;
      cam.style.left = Math.max(0, Math.min(innerWidth - w, p.x)) + "px"; cam.style.top = Math.max(0, Math.min(innerHeight - h, p.y)) + "px"; cam.style.bottom = "auto"; };
    try { const p = JSON.parse(store.get("rb_gcam_pos") || "null"); if (p) { if (p.w) { cam.style.width = p.w + "px"; cam.style.height = p.h + "px"; } setTimeout(() => put(p), 0); } } catch {}
    const save = () => { try { const r = cam.getBoundingClientRect(); store.set("rb_gcam_pos", JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height })); } catch {} };
    let d = null;
    bar.addEventListener("pointerdown", e => { if (e.target.closest("button")) return; const r = cam.getBoundingClientRect();
      d = { dx: e.clientX - r.left, dy: e.clientY - r.top }; bar.setPointerCapture(e.pointerId); e.preventDefault(); });
    bar.addEventListener("pointermove", e => { if (d) put({ x: e.clientX - d.dx, y: e.clientY - d.dy }); });
    const end = () => { if (d) { d = null; save(); } };
    bar.addEventListener("pointerup", end); bar.addEventListener("pointercancel", end);
    bar.addEventListener("dblclick", () => { cam.style.width = ""; cam.style.height = ""; put(null); try { store.set("rb_gcam_pos", "null"); } catch {} });
    if (window.ResizeObserver) { let t; new ResizeObserver(() => { clearTimeout(t); t = setTimeout(() => { if (cam.style.display === "block" && cam.style.width) save(); }, 400); }).observe(cam); }
    addEventListener("resize", () => { if (cam.style.top && cam.style.top !== "auto") { const r = cam.getBoundingClientRect(); put({ x: r.left, y: r.top }); } });
  }
  const wanted = () => { try { return store.get("rb_gesture") === "1"; } catch { return false; } };
  const remember = b => { try { store.set("rb_gesture", b ? "1" : "0"); } catch {} };

  const loadScript = src => new Promise((res, rej) => {
    if (window.Hands) return res();
    const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = () => rej(new Error("could not load " + src));
    document.head.appendChild(s);
  });

  async function start(){
    if (running) return;
    btn.classList.add("on"); show(true); say("starting camera…");
    try {
      await loadScript("/hands/hands.js");
      if (!hands) {
        hands = new window.Hands({ locateFile: f => "/hands/" + f });
        hands.setOptions({ maxNumHands: 2, modelComplexity: 0, minDetectionConfidence: .7, minTrackingConfidence: .6, selfieMode: false });
        hands.onResults(onResults);
      }
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: "user" }, audio: false });
      vid.srcObject = stream; await vid.play();
      running = true; sx = innerWidth / 2; sy = innerHeight / 2; remember(true);
      say("show your hand ✋");
      loop();
    } catch (e) {
      say(e.name === "NotAllowedError" ? "camera blocked" : "error"); if (e.name === "NotAllowedError") remember(false);
      if (typeof add === "function") add("bot", `<div class="bt">⚠️ Gesture control could not start: ${esc(e.name === "NotAllowedError" ? "camera permission was refused." : e.message || String(e))}</div>`);
      stop();
    }
  }

  function stop(){
    running = false; cancelAnimationFrame(raf);
    if (stream) stream.getTracks().forEach(t => t.stop()); stream = null;
    if (vid) vid.srcObject = null;
    release(true); setHover(null);
    if (btn) btn.classList.remove("on"); show(false);
  }

  function show(v){ cur.style.display = v ? "block" : "none"; document.getElementById("gCam").style.display = v ? "block" : "none"; }
  function say(t){ if (hud) hud.textContent = t; }

  async function loop(){
    if (!running) return;
    if (!busy && vid.readyState >= 2) {
      busy = true;
      try { await hands.send({ image: vid }); } catch {}
      busy = false;
    }
    raf = requestAnimationFrame(loop);
  }

  /* ---------- geometry helpers */
  const d = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const ext = (L, tip, pip) => d(L[0], L[tip]) > d(L[0], L[pip]) * 1.12;
  function pose(L){
    const f = [ext(L, 8, 6), ext(L, 12, 10), ext(L, 16, 14), ext(L, 20, 18)];
    const size = d(L[0], L[9]) || .1, pinch = d(L[4], L[8]) / size;
    const n = f.filter(Boolean).length;
    return { pinch, open: n === 4 && pinch > .7, fist: n === 0 && pinch > .25, index: f[0],
             v: f[0] && f[1] && !f[2] && !f[3] && pinch > .6, three: f[0] && f[1] && f[2] && !f[3] && pinch > .6 };
  }
  // camera box (mirrored) -> screen, using the middle 70% of the frame so the edges are easy to reach
  function toScreen(p){
    const m = .15, x = (1 - p.x - m) / (1 - 2 * m), y = (p.y - m) / (1 - 2 * m);
    return [Math.max(0, Math.min(1, x)) * innerWidth, Math.max(0, Math.min(1, y)) * innerHeight];
  }

  /* two hands, both pinching = grab a screen and pull your hands apart (zoom in / expand) or together (zoom out / compress) */
  let zoom = null;
  const TARGETS = ".hp:not(.out), .gexp, .card, .chat, .dock, .kpis > *, .panel, section";
  function grabTarget(x, y){
    const hit = document.elementFromPoint(x, y);
    return (hit && hit.closest(TARGETS)) || document.querySelector(".hp.focus:not(.out), .gexp") || [...document.querySelectorAll(".hp:not(.out)")].pop()
      || document.querySelector(".chat, .card");
  }
  function twoHand(A, B){
    const pa = toScreen({ x: (A[4].x + A[8].x) / 2, y: (A[4].y + A[8].y) / 2 }), pb = toScreen({ x: (B[4].x + B[8].x) / 2, y: (B[4].y + B[8].y) / 2 });
    const mx = (pa[0] + pb[0]) / 2, my = (pa[1] + pb[1]) / 2, dist = Math.hypot(pa[0] - pb[0], pa[1] - pb[1]);
    const ang = Math.atan2(pb[1] - pa[1], pb[0] - pa[0]) * 180 / Math.PI;
    sx += (mx - sx) * .5; sy += (my - sy) * .5; cur.style.transform = `translate(${sx}px,${sy}px)`;
    // ATLAS: two hands on the platform or a side screen = explode (apart) / assemble (together)
    if (typeof Atlas !== "undefined" && Atlas.on() && (!zoom || zoom.atlas)) {
      if (!zoom) {
        const hit = document.elementFromPoint(mx, my), sideId = Atlas.sideAt(mx, my);
        const id = sideId || (!(hit && hit.closest(".hp, .card, .chat, .dock, button, input")) ? "core" : null);
        if (id) { zoom = { atlas: id, d0: Math.max(40, dist), e0: Atlas.getExplode(id) }; flash(); }
      }
      if (zoom && zoom.atlas) {
        const ev = Math.max(0, Math.min(1, zoom.e0 + (dist / zoom.d0 - 1) * 1.4));
        Atlas.setExplode(zoom.atlas, ev);
        say(`🤏🤏 ${ev > zoom.e0 + .02 ? "exploding" : ev < zoom.e0 - .02 ? "assembling" : "hold"} ${Math.round(ev * 100)}% — apart = explode · together = assemble`);
        return;
      }
    }
    if (!zoom) {
      const el = grabTarget(mx, my);
      if (!el) { say("no screen to zoom"); return; }
      zoom = { el, d0: Math.max(40, dist), s0: parseFloat(el.style.scale) || 1, a0: ang, r0: parseFloat(el.style.rotate) || 0 };
      el.classList.add("gzoom"); el.style.transformOrigin = "50% 40%"; el.style.zIndex = 9; el.style.position = el.style.position || (getComputedStyle(el).position === "static" ? "relative" : ""); flash();
    }
    const sc = Math.max(.5, Math.min(2.8, zoom.s0 * dist / zoom.d0));
    let da = ang - zoom.a0; if (da > 180) da -= 360; if (da < -180) da += 360;
    const rot = zoom.r0 + da;
    zoom.el.style.scale = sc.toFixed(3); zoom.el.style.rotate = rot.toFixed(1) + "deg";
    say(`🤏🤏 zoom ${Math.round(sc * 100)}% · spin ${Math.round(rot)}° — apart/together = zoom · turn = spin`);
  }
  function endZoom(){ if (!zoom) return; if (zoom.atlas) { zoom = null; return; } const el = zoom.el, sc = parseFloat(el.style.scale) || 1, rot = parseFloat(el.style.rotate) || 0;
    if (Math.abs(rot % 360) < 8 || Math.abs(Math.abs(rot % 360) - 360) < 8) el.style.rotate = "";   // snap straight
    if (Math.abs(sc - 1) < .06) el.style.scale = "";                                                 // snap to normal size
    if (!el.style.scale && !el.style.rotate) { el.style.zIndex = ""; el.classList.remove("gzoom"); }
    zoom = null; }

  function onResults(r){
    if (!running) return;
    ctx.clearRect(0, 0, cvs.width, cvs.height);
    const HS = r.multiHandLandmarks || [];
    if (HS.length >= 2 && pose(HS[0]).pinch < .4 && pose(HS[1]).pinch < .4) {
      release(true); setHover(null); draw(HS[0]); draw(HS[1]); lastSeen = performance.now(); cur.classList.remove("lost"); cur.classList.add("pinch");
      twoHand(HS[0], HS[1]); return;
    }
    if (zoom) { endZoom(); cur.classList.remove("pinch"); }
    const L = HS.length >= 2 ? HS.reduce((a, b) => (a[0].x < b[0].x ? a : b)) : HS[0];     // with two hands up, follow the right hand (mirrored)
    if (!L) { cur.classList.add("lost"); if (performance.now() - lastSeen > 600) { release(true); say("no hand"); } return; }
    lastSeen = performance.now(); cur.classList.remove("lost");
    draw(L);
    const P = pose(L), now = performance.now();
    // pointer: between index tip and thumb tip while pinching (steadier), index tip otherwise
    const tip = P.pinch < .6 ? { x: (L[4].x + L[8].x) / 2, y: (L[4].y + L[8].y) / 2 } : L[8];
    const [tx, ty] = toScreen(tip), k = pinched ? .45 : .35;
    sx += (tx - sx) * k; sy += (ty - sy) * k;
    cur.style.transform = `translate(${sx}px,${sy}px)`;

    // fist held -> close all screens
    if (P.fist) {
      if (!fistAt) fistAt = now;
      const left = 1000 - (now - fistAt);
      say(left > 0 ? `fist… closing all in ${Math.ceil(left / 100) / 10}s` : "closed all");
      if (left <= 0 && fistAt > 0) { fistAt = -1; if (typeof HoloOS !== "undefined") HoloOS.closeAll(); }
      release(true); return;
    }
    if (fistAt) fistAt = 0;

    // ✌ held 0.7 s -> one more hologram screen (hold again for the next one)
    if (P.v) {
      release(true); setHover(null);
      if (!vAt) vAt = now;
      const left = 700 - (now - vAt);
      if (left > 0) say("✌ hold — add a screen");
      else if (vAt > 0) { vAt = -1; addScreen(); }
      return;
    }
    if (vAt) vAt = 0;

    // three fingers swipe -> change hologram theme
    if (P.three) {
      release(true); setHover(null);
      triHist.push([now, sx]); triHist = triHist.filter(h => now - h[0] < 450);
      const dx = triHist.length > 2 ? sx - triHist[0][1] : 0;
      say("3 fingers — swipe to change theme");
      if (Math.abs(dx) > innerWidth * .22 && now - lastSwipe > 1100) { lastSwipe = now; triHist = []; nextTheme(dx > 0 ? 1 : -1, true); }
      return;
    }
    triHist = [];

    // open palm wave left / right -> the hologram screens change (next / previous set)
    if (P.open) {
      release(true);
      const px = 1 - L[9].x, py = L[9].y;                                            // palm centre, mirrored, 0..1
      palmHist.push([now, px, py]); palmHist = palmHist.filter(h => now - h[0] < 450);
      const dx = palmHist.length > 2 ? px - palmHist[0][1] : 0, dy = palmHist.length > 2 ? py - palmHist[0][2] : 0;
      say("✋ slide left / right = screens · up / down = scroll");
      if (now - lastSwipe > 900) {
        if (Math.abs(dx) > .18 && Math.abs(dx) > Math.abs(dy) * 1.3) { lastSwipe = now; palmHist = []; changeScreens(dx > 0 ? 1 : -1); }
        else if (Math.abs(dy) > .16 && Math.abs(dy) > Math.abs(dx) * 1.3) { lastSwipe = now; palmHist = []; slideScroll(dy > 0 ? 1 : -1); }
      }
      setHover(null); return;
    }
    palmHist = [];

    // pinch with hysteresis
    if (!pinched && P.pinch < .33) press();
    else if (pinched && P.pinch > .5) release(false);
    if (pinched) moveWhilePinched(); else { say("point · pinch to click"); setHover(target(sx, sy)); }
  }

  function draw(L){
    const W = cvs.width, H = cvs.height, C = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];
    ctx.strokeStyle = "rgba(0,229,255,.9)"; ctx.lineWidth = 2; ctx.beginPath();
    for (const [a, b] of C) { ctx.moveTo(L[a].x * W, L[a].y * H); ctx.lineTo(L[b].x * W, L[b].y * H); }
    ctx.stroke(); ctx.fillStyle = "#fff";
    for (const i of [4, 8, 12, 16, 20]) { ctx.beginPath(); ctx.arc(L[i].x * W, L[i].y * H, 3, 0, 7); ctx.fill(); }
  }

  /* ---------- targets */
  function target(x, y){
    const el = document.elementFromPoint(x, y);
    return el && el.closest("button,a,[role=button],.chip,label,input,select,textarea,summary,.hp header,[onclick]") || el;
  }
  function setHover(el){
    if (hoverEl === el) return;
    if (hoverEl) hoverEl.classList.remove("ghover");
    hoverEl = el && el !== document.body && el !== document.documentElement && el.closest("button,a,[role=button],.chip,.hp header,label") ? el : null;
    if (hoverEl) hoverEl.classList.add("ghover");
  }
  function scroller(el){
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (/(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 4) return e;
    }
    return document.scrollingElement;
  }

  function press(){
    pinched = true; cur.classList.add("pinch");
    const el = document.elementFromPoint(sx, sy), head = el && el.closest(".hp header"), panel = head && head.closest(".hp");
    pin = { x: sx, y: sy, t: performance.now(), el: target(sx, sy), raw: el, moved: 0, scroll: el ? scroller(el) : null, lastY: sy,
            any: el && !el.closest(".x, button, a, input, select, textarea") ? el.closest(".hp:not(.out), .gexp, .card, .chat, .kpis > *, .panel") : null };
    if (panel && !el.closest(".x")) {
      pin.panel = panel; pin.left = parseFloat(panel.style.left) || panel.offsetLeft; pin.top = parseFloat(panel.style.top) || panel.offsetTop;
    }
    const scr = !panel && el && el.closest(".hudc:not(.mfocus)");                     // a side screen: pinch anywhere on it and move
    if (scr && typeof Manip !== "undefined") { pin.mov = scr; pin.p0 = Manip.startPos(scr); }
  }
  function moveWhilePinched(){
    if (!pin) return;
    pin.moved = Math.max(pin.moved, Math.hypot(sx - pin.x, sy - pin.y));
    if (pin.mov && pin.moved > 14) {
      cur.classList.add("drag"); say("moving screen"); Manip.move(pin.mov, pin.p0, sx - pin.x, sy - pin.y); pin.dragged = true;
    } else if (pin.panel && pin.moved > 14) {
      cur.classList.add("drag"); say("dragging screen");
      pin.panel.style.left = Math.round(pin.left + sx - pin.x) + "px";
      pin.panel.style.top = Math.round(pin.top + sy - pin.y) + "px";
      pin.dragged = true;
    } else if (pin.any && !pin.held && pin.moved < 14 && performance.now() - pin.t > 750) {
      pin.held = true; flash();                                           // pinch + hold still on a screen = expand / back to normal
      let big;
      if (pin.any.classList.contains("hp")) { const h = pin.any.querySelector("header"); if (h) h.click(); big = pin.any.classList.contains("focus"); }
      else if (pin.any.classList.contains("hudc") && typeof Manip !== "undefined") { Manip.focus(pin.any); big = !!Manip.focused; }   // side screen: assemble in the centre
      else { big = pin.any.classList.toggle("gexp"); }
      if (!big) { pin.any.style.scale = ""; pin.any.style.rotate = ""; pin.any.style.zIndex = ""; pin.any.classList.remove("gzoom"); }
      say(big ? "⤢ expanded — pinch & hold again to compress" : "⤡ compressed back to normal");
    } else if (!pin.panel && pin.moved > 30 && pin.scroll) {
      say("scrolling"); pin.scrolled = true;
      pin.scroll.scrollTop -= (sy - pin.lastY) * 1.6;
    } else say("pinch");
    pin.lastY = sy;
  }
  function release(cancel){
    if (!pinched) return;
    pinched = false; cur.classList.remove("pinch", "drag");
    const p = pin; pin = null;
    if (cancel || !p || p.dragged || p.scrolled || p.held) return;
    if (p.moved < 40 && performance.now() - p.t < 900 && p.el) click(p.el);
  }
  function click(el){
    flash();
    if (typeof Atlas !== "undefined" && Atlas.on() && !el.closest(".hp, button, a, input, select, textarea, .card, .chat, .dock")) {
      const part = Atlas.pick(sx, sy);                                          // pinch a part of the hologram = remove / fit it
      if (part) { Atlas.toggle(part); say("part " + part + " toggled"); return; }
    }
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) { el.focus(); if (el.type === "checkbox" || el.type === "radio") el.click(); return; }
    if (typeof el.click === "function") el.click();
    else el.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: sx, clientY: sy }));
  }
  function flash(){ cur.animate([{ boxShadow: "0 0 0 0 rgba(0,229,255,.9)" }, { boxShadow: "0 0 0 22px rgba(0,229,255,0)" }], { duration: 380 }); }

  async function addScreen(){
    if (!document.body.classList.contains("theme-holo")) { nextTheme(0); say("hologram on"); return; }
    flash(); say("adding screen…");
    const p = typeof HoloOS !== "undefined" ? await HoloOS.spawn() : null;
    say(p ? "screen added ✌" : "no room — close one first");
  }
  function curTheme(){ const b = document.body.classList;
    return b.contains("theme-atlas") ? "atlas" : b.contains("theme-titan") ? "titan" : b.contains("theme-nova") ? "nova" : b.contains("theme-forge") ? "forge" : b.contains("theme-holo") ? "holo" : b.contains("theme-arc") ? "arc" : "aurora"; }
  function nextTheme(dir, all){
    const mine = (ME && ME.themes && ME.themes.length ? ME.themes : ["aurora", "arc", "holo", "forge", "titan", "atlas"]);
    const T = all ? mine : mine.filter(t => !["aurora", "arc"].includes(t));
    if (!T.length) { say("no other look allowed"); return; }
    const cur = curTheme(), i = T.indexOf(cur);
    const t = i < 0 ? T[0] : T[(i + (dir || 1) + T.length) % T.length];
    if (typeof setTheme === "function") setTheme(t);
    say("theme: " + t);
  }
  function slideScroll(dir){
    const hit = document.elementFromPoint(sx, sy);
    let el = hit; while (el && el !== document.body) { const st = getComputedStyle(el); if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 4) break; el = el.parentElement; }
    if (!el || el === document.body) el = document.querySelector("#log") && document.querySelector("#log").scrollHeight > document.querySelector("#log").clientHeight ? document.querySelector("#log") : document.scrollingElement;
    el.scrollBy({ top: dir * el.clientHeight * .8, behavior: "smooth" }); flash();
    say(dir > 0 ? "⬇ slid down" : "⬆ slid up");
  }
  async function changeScreens(dir){
    if (!document.body.classList.contains("theme-holo")) { nextTheme(dir, true); return; }      // Aurora / Arc: next / previous look
    flash(); say(dir > 0 ? "next screens →" : "← previous screens");
    if (typeof HoloOS !== "undefined" && HoloOS.cycle) await HoloOS.cycle(dir);
  }
  function swipeClose(dx){
    const list = [...document.querySelectorAll(".hp:not(.out)")];
    if (!list.length) { say("no screens open"); return; }
    const under = document.elementFromPoint(sx, sy), hit = under && under.closest(".hp:not(.out)");
    const p = document.querySelector(".hp.focus:not(.out)") || hit || list[list.length - 1];
    const x = p.querySelector(".x");
    if (x) x.click();
    say(dx > 0 ? "closed →" : "← closed");
  }

  return { init, start, stop, get on(){ return running; }, allowed };
})();
