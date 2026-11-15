/* ================================================================ HOLO theme - VERONICA's own hologram
   A holographic projector above a glowing grid floor. The projection follows her state AND the answer:
     idle    wireframe globe + segmented rings          listening  green, rings ripple with your voice
     thinking globe breaks into a spinning data ring, code streams, "ANALYSING"
     speaking gold equaliser ring pulsing with her voice
     answer  KPI cards -> rising 3D bars with the real numbers · tables -> floating data panel typing in
             files / dashboard -> stacked screens · warning -> red alert prism · private data -> lock
   BGM = the boss's own track (/bgm.mp3, looped with a soft crossfade) - plays while she is NOT working and
   fades out while a task runs. Screen / packet / typing sounds are still synthesised (Web Audio). */
const HoloAudio = (() => {
  let ctx = null, master = null, music = null, sfx = null, started = false, arpT = 0, step = 0, busy = false, duck = 1, lastWork = 0, hold = false, speaking = false;
  // music: "on" (only while idle - pauses while a task runs) | "always" | "off" ; screen sounds: on/off
  let musicMode = store.get("rb_holo_music") || (store.get("rb_holo_sound") === "0" ? "off" : "on"), sfxOn = store.get("rb_holo_sfx") !== "0";
  if (!["on", "always", "off"].includes(musicMode)) musicMode = "on";                // old "while working" setting -> idle music
  if (store.get("rb_snd_v2") !== "1") { store.set("rb_snd_v2", "1"); sfxOn = true; store.set("rb_holo_sfx", "1"); if (musicMode === "off") musicMode = "on"; }
  // the Iron-Man track plays only when nothing is happening: not during the login intro, a question, or her voice;
  // it returns QUIET_MS after the last answer, fading in / out over FADE seconds
  const QUIET_MS = 6000, FADE = 4;
  const musicNow = () => !hold && (musicMode === "always" || (musicMode === "on" && !busy && !speaking && Date.now() - lastWork > QUIET_MS));
  let bgmBuf = null, bgmLoading = false, bgmNext = 0, bgmSrcs = [];
  const XF = 1.6;                                                                    // crossfade seconds at the loop seam
  function loadBgm(){
    if (bgmBuf || bgmLoading || !ctx) return; bgmLoading = true;
    fetch("/bgm.mp3").then(r => r.ok ? r.arrayBuffer() : Promise.reject(r.status))
      .then(b => new Promise((res, rej) => ctx.decodeAudioData(b, res, rej)))
      .then(buf => { bgmBuf = buf; bgmNext = 0; }).catch(() => {}).finally(() => { bgmLoading = false; });
  }
  function bgmPump(){                                                                // keeps the loop going, overlapping each pass by XF
    if (!ctx || !bgmBuf || !musicNow()) return;
    const now = ctx.currentTime;
    if (bgmNext && bgmNext > now + .3) return;
    const t0 = Math.max(now + .05, bgmNext || 0), d = bgmBuf.duration;
    const s = ctx.createBufferSource(), g = ctx.createGain(); s.buffer = bgmBuf; s.connect(g); g.connect(music);
    g.gain.setValueAtTime(0, t0); g.gain.linearRampToValueAtTime(1, t0 + XF);
    g.gain.setValueAtTime(1, t0 + d - XF); g.gain.linearRampToValueAtTime(0, t0 + d);
    s.start(t0); s.stop(t0 + d + .05); bgmSrcs.push(s); s.onended = () => { bgmSrcs = bgmSrcs.filter(x => x !== s); };
    bgmNext = t0 + d - XF;
  }
  function bgmHalt(){ bgmSrcs.forEach(s => { try { s.stop(ctx.currentTime + 1.2); } catch {} }); bgmSrcs = []; bgmNext = 0; }
  let on = true;
  const SCALES = { holo: [57, 60, 62, 64, 67, 69, 72, 74],                         // A minor pentatonic (MIDI)
                   nova: [50, 53, 55, 57, 60, 62, 65, 67],                         // D dorian-ish, darker and lower
                   forge: [52, 53, 57, 59, 60, 64, 65, 69] };                      // E phrygian: heavy, industrial
  const PADS = { holo: [45, 52, 57], nova: [38, 45, 50], forge: [40, 47, 52], titan: [43, 50, 55] };
  SCALES.titan = [55, 57, 59, 62, 64, 66, 69, 71];                                   // G lydian-ish: clean, technical
  let NOTES = SCALES.holo, mode = "holo", pads = [];
  const hz = m => 440 * Math.pow(2, (m - 69) / 12);
  function init(){
    if (ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
    ctx = new AC(); master = ctx.createGain(); master.gain.value = 1; master.connect(ctx.destination);
    music = ctx.createGain(); music.gain.value = .0; music.connect(master);
    sfx = ctx.createGain(); sfx.gain.value = .32; sfx.connect(master);
    HoloAudio._arpOut = sfx;                                                         // (old synth BGM removed - real track now)
    loadBgm();
  }
  function env(o, g, t0, a, d, peak){ g.gain.setValueAtTime(0, t0); g.gain.linearRampToValueAtTime(peak, t0 + a); g.gain.exponentialRampToValueAtTime(.0001, t0 + a + d); o.start(t0); o.stop(t0 + a + d + .05); }
  function pluck(m, t0, vol = .08, out){
    const o = ctx.createOscillator(), g = ctx.createGain(), f = ctx.createBiquadFilter(); o.type = "triangle"; o.frequency.value = hz(m);
    f.type = "lowpass"; f.frequency.value = 2400; o.connect(f); f.connect(g); g.connect(out || HoloAudio._arpOut); env(o, g, t0, .005, .5, vol);
  }
  const ready = () => ctx && sfxOn && document.body.classList.contains("theme-holo");
  function sweep(f1, f2, dur, vol, type = "triangle", t0 = ctx.currentTime){
    const o = ctx.createOscillator(), g = ctx.createGain(); o.type = type;
    o.frequency.setValueAtTime(f1, t0); o.frequency.exponentialRampToValueAtTime(f2, t0 + dur); o.connect(g); g.connect(sfx); env(o, g, t0, dur * .6, dur * .5, vol);
  }
  function bandSweep(t0, dur, f1, f2, vol){
    const n = Math.floor(ctx.sampleRate * dur), b = ctx.createBuffer(1, n, ctx.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.sin(Math.PI * i / n);
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain(); s.buffer = b; f.type = "bandpass"; f.Q.value = 6;
    f.frequency.setValueAtTime(f1, t0); f.frequency.exponentialRampToValueAtTime(f2, t0 + dur); g.gain.value = vol; s.connect(f); f.connect(g); g.connect(sfx); s.start(t0);
  }
  function tick(){ if (!ctx) return; if (!bgmBuf) loadBgm(); bgmPump(); }
  function noise(t0, dur, hp, vol){
    const n = Math.max(1, Math.floor(ctx.sampleRate * dur)), b = ctx.createBuffer(1, n, ctx.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n);
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain(); s.buffer = b; f.type = "highpass"; f.frequency.value = hp; g.gain.value = vol;
    s.connect(f); f.connect(g); g.connect(sfx); s.start(t0);
  }
  function blip(f1, f2, dur = .12, vol = .25, type = "sine"){
    if (!ctx || !sfxOn) return; const t0 = ctx.currentTime, o = ctx.createOscillator(), g = ctx.createGain(); o.type = type;
    o.frequency.setValueAtTime(f1, t0); o.frequency.exponentialRampToValueAtTime(f2, t0 + dur); o.connect(g); g.connect(sfx); env(o, g, t0, .005, dur, vol);
  }
  setInterval(tick, 250);
  let fadeTo = -1, fadeEnd = 0;
  const fadeMusic = () => { if (!ctx || !music) return;
    const want = musicNow() && document.body.classList.contains("theme-holo"), target = want ? .6 * duck : 0, now = ctx.currentTime;
    if (Math.abs(target - fadeTo) > .001) {                                         // 4-second linear fade in / out
      const g = music.gain, cur = g.value; g.cancelScheduledValues(now); g.setValueAtTime(cur, now);
      g.linearRampToValueAtTime(target, now + FADE); fadeTo = target; fadeEnd = now + FADE;
      if (want) bgmPump();
    }
    if (!want && bgmSrcs.length && now > fadeEnd + .2) bgmHalt(); };
  setInterval(fadeMusic, 400);
  // "data loading" texture while she works: soft data ticks + a low pulse every beat
  let loadT = 0;
  setInterval(() => { if (!busy || !ready()) return; const t0 = ctx.currentTime; loadT++;
    noise(t0, .018, 5200, .05); if (loadT % 2 === 0) blip(hz(NOTES[loadT % 8] + 24), hz(NOTES[loadT % 8] + 24), .05, .035, "square");
    if (loadT % 8 === 0) sweep(hz(NOTES[0]), hz(NOTES[0] + 12), .35, .045, "triangle"); }, 140);
  return {
    start(){ if (!document.body.classList.contains("theme-holo")) return; init(); if (!ctx) return; if (ctx.state === "suspended") ctx.resume(); if (!started) { started = true; } loadBgm(); bgmPump(); fadeMusic(); },
    toggle(){ const off = musicMode === "off" && !sfxOn; this.setMusic(off ? "on" : "off"); this.setSfx(off); return off; },
    get on(){ return musicMode !== "off" || sfxOn; },
    get music(){ return musicMode; }, get sfx(){ return sfxOn; },
    setMusic(m){ musicMode = ["on", "always", "off"].includes(m) ? m : "on"; store.set("rb_holo_music", musicMode); if (musicMode !== "off") this.start(); fadeMusic(); },
    setSfx(b){ sfxOn = !!b; store.set("rb_holo_sfx", sfxOn ? "1" : "0"); if (sfxOn) this.start(); },
    busy(b){ if (busy && !b) lastWork = Date.now(); busy = b; if (b) lastWork = Date.now(); fadeMusic(); },
    duck(b){ if (speaking && !b) lastWork = Date.now(); speaking = !!b; fadeMusic(); },
    hold(b){ hold = !!b; if (!b) lastWork = Date.now() - QUIET_MS + 1500; fadeMusic(); },     // login intro: BGM waits, then fades in
    success(){ if (!ready()) return; const t0 = ctx.currentTime;                     // answer ready: bright rising triad + sparkle
      [0, 2, 4].forEach((n, k) => pluck(NOTES[n] + 24, t0 + k * .09, .09, sfx)); pluck(NOTES[7] + 24, t0 + .3, .07, sfx); noise(t0 + .3, .08, 8000, .04); },
    stop(){ fadeMusic(); },
    key(){ if (ctx && sfxOn && Math.random() < .55) noise(ctx.currentTime, .012, 3500, .09); },
    scene(){ blip(660, 1320, .09, .18); setTimeout(() => blip(990, 1980, .12, .12), 90); },
    whoosh(){ if (ctx && sfxOn) { noise(ctx.currentTime, .45, 900, .12); blip(180, 60, .4, .15, "sawtooth"); } },
    mode(m){ if (m === "atlas") m = "titan"; m = ["nova", "forge", "titan"].includes(m) ? m : "holo"; if (m === mode) return; mode = m; NOTES = SCALES[m];
      },
    // a light packet flies to the next screen: rising sweep that ends on the screen's note
    transfer(i = 0){ if (!ready()) return; const t0 = ctx.currentTime, m = NOTES[i % 8] + 12;
      sweep(hz(m - 12), hz(m), .3, .06); bandSweep(t0, .32, 500, 5000, .05); },
    // the screen unfolds: its note + a fifth, so a cascade of screens plays a phrase
    open(i = 0, red = false){ if (!ready()) return; const t0 = ctx.currentTime, m = NOTES[i % 8] + 12;
      if (red) { blip(440, 220, .22, .16, "square"); return; }
      pluck(m, t0, .1, sfx); pluck(m + 7, t0 + .05, .05, sfx); noise(t0, .03, 6000, .05);
      if (mode === "forge") { blip(hz(m + 24), hz(m + 23.6), .5, .05, "sine"); noise(t0, .06, 1800, .07); }
      if (mode === "titan") { blip(hz(m + 19), hz(m + 31), .16, .05, "square"); noise(t0 + .04, .02, 9000, .06); } },   // a crisp CNC "lock-in" chirp     // a hammer-on-steel ring
    scan(){ if (!ready()) return; const t0 = ctx.currentTime;
      bandSweep(t0, 1.1, 300, 6000, .09); bandSweep(t0 + 1.1, 1.1, 6000, 300, .07);
      [0, .18, .36].forEach((d, k) => pluck(NOTES[(k * 2) % 8] + 24, t0 + 1.25 + d, .06, sfx)); },
    boot(){ if (!ready()) return; const t0 = ctx.currentTime;
      sweep(hz(NOTES[0] - 24), hz(NOTES[0] - 12), 1.2, .14, "sawtooth");
      [0, 2, 4, 5, 7].forEach((n, k) => pluck(NOTES[n] + 12, t0 + .5 + k * .11, .08, sfx)); },
    alert(){ blip(440, 220, .25, .22, "square"); setTimeout(() => blip(440, 220, .25, .18, "square"), 300); },
  };
})();

const Holo = (() => {
  const cv = $("#holo"); if (!cv) return { theme(){}, state(){}, react(){} };
  const x = cv.getContext("2d");
  let W = 0, H = 0, dpr = 1, t = 0, last = performance.now(), on = false, st = "ready", scene = { k: "idle" }, glitch = 0, born = 0;
  const fit = () => { dpr = Math.min(devicePixelRatio || 1, 2); W = cv.clientWidth; H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr; };
  new ResizeObserver(fit).observe(cv);
  const PAL = { holo: { c: "120,230,255", g: "120,255,200", o: "255,196,110", r: "255,90,110" },
                nova: { c: "64,140,255", g: "120,255,215", o: "190,220,255", r: "255,80,110" },
                forge: { c: "90,180,255", g: "120,245,230", o: "200,235,255", r: "255,80,100" },
                titan: { c: "85,185,255", g: "110,245,220", o: "205,238,255", r: "255,95,120" } };
  let C = PAL.holo, nova = false, forgeOn = false, titanOn = false, atlasOn = false;
  const col = () => scene.k === "alert" || scene.k === "lock" ? C.r : st === "listening" ? C.g : st === "speaking" ? C.o : C.c;
  const rgba = (c, a) => `rgba(${c},${a})`;
  const CODE = "SELECT SUM(QTY) FROM VIEW WHERE DATE>= GROUP BY PLANT 0x3F A9 ∑ Δ λ ⟶ JOIN ON KEY 101101 RUN ENGINE VERIFY ✓ KPI ".split(" ");
  const streams = Array.from({ length: 14 }, (_, i) => ({ x: Math.random(), y: Math.random(), v: .2 + Math.random() * .6, s: CODE[i % CODE.length] }));
  function floor(c){
    const hz = H * .74, cx = W / 2;
    x.lineWidth = 1;
    for (let i = -14; i <= 14; i++) { const a = .05 + .1 * (1 - Math.abs(i) / 14); x.strokeStyle = rgba(c, a); x.beginPath(); x.moveTo(cx + i * 14, hz); x.lineTo(cx + i * W * .09, H); x.stroke(); }
    const off = (t * 22) % 18;
    for (let j = 0; j < 9; j++) { const y = hz + Math.pow((j * 18 + off) / 162, 1.8) * (H - hz); x.strokeStyle = rgba(c, .04 + (y - hz) / (H - hz) * .12); x.beginPath(); x.moveTo(0, y); x.lineTo(W, y); x.stroke(); }
    // projector + light cone
    const g = x.createLinearGradient(0, hz, 0, H * .12); g.addColorStop(0, rgba(c, .16)); g.addColorStop(1, rgba(c, 0));
    x.fillStyle = g; x.beginPath(); x.moveTo(cx - 16, hz + 6); x.lineTo(cx - W * .2, H * .1); x.lineTo(cx + W * .2, H * .1); x.lineTo(cx + 16, hz + 6); x.fill();
    x.fillStyle = rgba(c, .85); x.beginPath(); x.ellipse(cx, hz + 6, 34, 6, 0, 0, 7); x.fill();
    x.strokeStyle = rgba(c, .5); x.beginPath(); x.ellipse(cx, hz + 6, 58 + Math.sin(t * 3) * 3, 10, 0, 0, 7); x.stroke();
  }
  function rings(cx, cy, R, c, k = 1){
    const segs = [[1.25, 24, .9, 1], [1.42, 60, .35, -1.6], [1.6, 8, .55, .5]];
    segs.forEach(([rr, n, a, sp], j) => {
      x.strokeStyle = rgba(j === 2 ? C.o : c, a); x.lineWidth = j === 0 ? 3 : 1.2;
      const rot = t * sp * k * .4;
      for (let i = 0; i < n; i++) { if ((i + j) % 4 === 3) continue; const a0 = rot + i / n * Math.PI * 2, a1 = a0 + Math.PI * 2 / n * .7;
        x.beginPath(); x.ellipse(cx, cy, R * rr, R * rr * .32, 0, a0, a1); x.stroke(); }
    });
  }
  function globe(cx, cy, R, c, burst = 0){
    const rot = t * .5;
    x.lineWidth = 1;
    for (let la = -60; la <= 60; la += 30) { x.strokeStyle = rgba(c, .3); x.beginPath();
      for (let lo = 0; lo <= 360; lo += 10) { const L = la * Math.PI / 180, O = lo * Math.PI / 180 + rot, px = cx + Math.cos(L) * Math.cos(O) * R * (1 + burst),
        py = cy - Math.sin(L) * R * (1 + burst * .5) + Math.cos(L) * Math.sin(O) * R * .18; lo ? x.lineTo(px, py) : x.moveTo(px, py); } x.stroke(); }
    for (let lo = 0; lo < 180; lo += 30) { x.strokeStyle = rgba(c, .22); x.beginPath(); x.ellipse(cx, cy, Math.abs(Math.cos(lo * Math.PI / 180 + rot)) * R * (1 + burst), R * (1 + burst * .5), 0, 0, 7); x.stroke(); }
    const gl = x.createRadialGradient(cx, cy, 0, cx, cy, R * 1.2); gl.addColorStop(0, rgba(c, .22 + VLVL * .3)); gl.addColorStop(1, rgba(c, 0));
    x.fillStyle = gl; x.beginPath(); x.arc(cx, cy, R * 1.2, 0, 7); x.fill();
  }
  function reactor(cx, cy, R, c){                         // Nova idle core: rotating reactor rings + triangle + breathing heart
    const o = C.o, k = 1 + VLVL * .35 + Math.sin(t * 2.4) * .025, sp = st === "listening" ? 2.4 : 1;
    x.lineWidth = 1;
    for (let i = 0; i < 72; i++) { const a = i / 72 * Math.PI * 2 + t * .04, r0 = R * 1.34, r1 = R * (i % 6 ? 1.4 : 1.5);
      x.strokeStyle = rgba(c, i % 6 ? .3 : .7); x.beginPath(); x.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0); x.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); x.stroke(); }
    x.lineWidth = R * .16; x.lineCap = "butt";
    for (let i = 0; i < 10; i++) { const a0 = t * .5 * sp + i / 10 * Math.PI * 2; x.strokeStyle = rgba(c, .5 + .3 * Math.sin(t * 3 + i));
      x.beginPath(); x.arc(cx, cy, R * 1.04, a0, a0 + .46); x.stroke(); }
    x.lineWidth = 3; x.setLineDash([R * .12, R * .07]); x.strokeStyle = rgba(o, .85);
    x.beginPath(); x.arc(cx, cy, R * .78, -t * .9 * sp, -t * .9 * sp + Math.PI * 2); x.stroke(); x.setLineDash([]);
    x.lineWidth = 1.2; x.strokeStyle = rgba(c, .6); x.beginPath(); x.arc(cx, cy, R * .64, 0, 7); x.stroke();
    x.save(); x.translate(cx, cy); x.rotate(t * .25); x.lineWidth = 2.6; x.strokeStyle = rgba(c, .95); x.beginPath();
    for (let i = 0; i < 3; i++) { const a = -Math.PI / 2 + i * Math.PI * 2 / 3; x[i ? "lineTo" : "moveTo"](Math.cos(a) * R * .55, Math.sin(a) * R * .55); }
    x.closePath(); x.stroke(); x.restore();
    const g = x.createRadialGradient(cx, cy, 0, cx, cy, R * .5 * k); g.addColorStop(0, "rgba(255,255,255,.95)"); g.addColorStop(.25, rgba(c, .8)); g.addColorStop(1, rgba(c, 0));
    x.fillStyle = g; x.beginPath(); x.arc(cx, cy, R * .5 * k, 0, 7); x.fill();
    const halo = x.createRadialGradient(cx, cy, R * .5, cx, cy, R * 1.9); halo.addColorStop(0, rgba(o, .12 + VLVL * .2)); halo.addColorStop(1, rgba(o, 0));
    x.fillStyle = halo; x.beginPath(); x.arc(cx, cy, R * 1.9, 0, 7); x.fill();
  }
  /* Forge idle core: a white-hot steel tube cross-section, slowly turning, heat rippling off it, embers rising */
  const embers = Array.from({ length: 70 }, () => ({ x: Math.random(), y: Math.random(), v: .15 + Math.random() * .5, s: .6 + Math.random() * 1.6, p: Math.random() * 6 }));
  const fsparks = [];
  function forge(cx, cy, R, c){
    const hot = C.o, k = 1 + VLVL * .25 + Math.sin(t * 1.7) * .02, rot = t * .25 * (st === "listening" ? 2.5 : 1);
    // heat glow
    const halo = x.createRadialGradient(cx, cy, R * .4, cx, cy, R * 2.3); halo.addColorStop(0, rgba(c, .28 + VLVL * .2)); halo.addColorStop(.5, rgba("255,70,20", .1)); halo.addColorStop(1, rgba(c, 0));
    x.fillStyle = halo; x.beginPath(); x.arc(cx, cy, R * 2.3, 0, 7); x.fill();
    // tube wall: dark outer skin -> glowing -> white-hot inner edge
    const Ro = R * 1.05 * k, Ri = R * .62 * k;
    const wall = x.createRadialGradient(cx, cy, Ri, cx, cy, Ro);
    wall.addColorStop(0, "rgba(255,250,235,.95)"); wall.addColorStop(.18, rgba(hot, .9)); wall.addColorStop(.55, rgba(c, .75)); wall.addColorStop(1, "rgba(120,30,5,.55)");
    x.fillStyle = wall; x.beginPath(); x.arc(cx, cy, Ro, 0, 7); x.arc(cx, cy, Ri, 0, 7, true); x.fill();
    // rolling marks on the wall (shows it turning)
    x.lineWidth = 1.2;
    for (let i = 0; i < 36; i++) { const a = rot + i / 36 * Math.PI * 2; x.strokeStyle = rgba("255,240,220", i % 3 ? .1 : .3);
      x.beginPath(); x.moveTo(cx + Math.cos(a) * Ri * 1.04, cy + Math.sin(a) * Ri * 1.04); x.lineTo(cx + Math.cos(a) * Ro * .97, cy + Math.sin(a) * Ro * .97); x.stroke(); }
    // bore: dark with a hot rim
    const bore = x.createRadialGradient(cx, cy, 0, cx, cy, Ri); bore.addColorStop(0, "rgba(10,4,2,.9)"); bore.addColorStop(.85, "rgba(40,12,4,.7)"); bore.addColorStop(1, rgba(hot, .6));
    x.fillStyle = bore; x.beginPath(); x.arc(cx, cy, Ri, 0, 7); x.fill();
    // heat shimmer rings
    for (let i = 0; i < 3; i++) { const f = (t * .35 + i / 3) % 1, rr = Ro + f * R * .9;
      x.strokeStyle = rgba(c, (1 - f) * .35); x.lineWidth = 1.5; x.beginPath();
      for (let a = 0; a <= 6.3; a += .12) { const w = rr + Math.sin(a * 6 + t * 3 + i) * 3; a ? x.lineTo(cx + Math.cos(a) * w, cy + Math.sin(a) * w) : x.moveTo(cx + Math.cos(a) * w, cy + Math.sin(a) * w); }
      x.closePath(); x.stroke(); }
    // outer measuring ring with ticks (OD gauge)
    x.strokeStyle = rgba(hot, .55); x.lineWidth = 1; x.beginPath(); x.arc(cx, cy, R * 1.55, 0, 7); x.stroke();
    for (let i = 0; i < 60; i++) { const a = i / 60 * Math.PI * 2 - t * .05, l = i % 5 ? 4 : 10;
      x.strokeStyle = rgba(hot, i % 5 ? .3 : .7); x.beginPath(); x.moveTo(cx + Math.cos(a) * R * 1.55, cy + Math.sin(a) * R * 1.55); x.lineTo(cx + Math.cos(a) * (R * 1.55 + l), cy + Math.sin(a) * (R * 1.55 + l)); x.stroke(); }
    const ga = -t * .6; x.strokeStyle = rgba(hot, .95); x.lineWidth = 3; x.beginPath(); x.arc(cx, cy, R * 1.66, ga, ga + .7); x.stroke();
    // embers rising from the floor
    for (const e of embers) { e.y -= e.v * .006 * (st === "thinking" ? 2.2 : 1); if (e.y < -.05) { e.y = 1.02; e.x = Math.random(); }
      const ex = (e.x + Math.sin(t * .8 + e.p) * .02) * W, ey = e.y * H * .78, fl = .5 + .5 * Math.sin(t * 9 + e.p * 7);
      x.fillStyle = rgba(e.s > 1.4 ? hot : c, (.25 + fl * .55) * Math.min(1, (1 - e.y) * 3)); x.beginPath(); x.arc(ex, ey, e.s, 0, 7); x.fill(); }
  }
  /* TITAN idle: a detailed 3D wireframe PIPE SPOOL as on a fabrication isometric:
     WN flange - pipe (on a support shoe) - equal TEE with a branch + concentric REDUCER + small flange - 90° LR ELBOW -
     riser with a GATE VALVE (handwheel) - top flange. Double wall (OD + bore), weld seams numbered W1…W6, fluid flowing,
     dimension lines and callouts; an atom orbits (nuclear) and a jet climbs past (aerospace). */
  const V = { add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], mul: (a, k) => [a[0] * k, a[1] * k, a[2] * k],
    cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]],
    norm: a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; } };
  const basis = tn => { const up = Math.abs(tn[1]) < .9 ? [0, 1, 0] : [1, 0, 0], n1 = V.norm(V.cross(tn, up)); return [n1, V.cross(tn, n1)]; };
  const SP = (() => {
    const R0 = .15, line = (a, b, n, r) => Array.from({ length: n + 1 }, (_, i) => ({ p: V.add(a, V.mul(V.add(b, V.mul(a, -1)), i / n)), t: V.norm(V.add(b, V.mul(a, -1))), r }));
    const main = [...line([-1.15, -.5, 0], [-.12, -.5, 0], 14, R0)];
    for (let i = 1; i <= 10; i++) { const q = i / 10 * Math.PI / 2; main.push({ p: [-.12 + .3 * Math.sin(q), -.5 + .3 * (1 - Math.cos(q)), 0], t: [Math.cos(q), Math.sin(q), 0], r: R0 }); }
    main.push(...line([.18, -.2, 0], [.18, .78, 0], 14, R0).slice(1));
    const branch = [...line([-.62, -.5, R0], [-.62, -.5, .42], 4, R0 * .92), ...line([-.62, -.5, .42], [-.62, -.5, .56], 3, R0 * .92).map((s2, i) => ({ ...s2, r: R0 * (.92 - i / 3 * .35) })),
                    ...line([-.62, -.5, .56], [-.62, -.5, .74], 3, R0 * .57).slice(1)];
    const welds = [{ seg: main, i: 1, n: "W1" }, { seg: main, i: 14, n: "W2" }, { seg: main, i: 24, n: "W3" }, { seg: branch, i: 4, n: "W4" }, { seg: main, i: 30, n: "W5" }, { seg: main, i: main.length - 2, n: "W6" }];
    return { R0, main, branch, welds, valveAt: 31 }; })();
  const flow = Array.from({ length: 30 }, (_, i) => i / 30);
  function titan(cx, cy, R, c){
    const ry = t * .36, rx = .48 + Math.sin(t * .27) * .1, S = R * .8, o = C.o;
    const P3 = ([X, Y, Z]) => { const x1 = X * Math.cos(ry) + Z * Math.sin(ry), z1 = -X * Math.sin(ry) + Z * Math.cos(ry);
      const y2 = Y * Math.cos(rx) - z1 * Math.sin(rx), z2 = Y * Math.sin(rx) + z1 * Math.cos(rx), k = 3 / (3.4 - z2);
      return [cx + x1 * k * S, cy - y2 * k * S + S * .05, z2]; };
    const ring = (pos, tn, rr, n = 16) => { const [n1, n2] = basis(tn);
      return Array.from({ length: n + 1 }, (_, i) => { const a = i / n * Math.PI * 2; return P3(V.add(pos, V.add(V.mul(n1, Math.cos(a) * rr), V.mul(n2, Math.sin(a) * rr)))); }); };
    const path = (q, close) => { x.beginPath(); q.forEach((p, i) => i ? x.lineTo(p[0], p[1]) : x.moveTo(p[0], p[1])); if (close) x.closePath(); x.stroke(); };
    const g = x.createRadialGradient(cx, cy, 0, cx, cy, R * 1.5); g.addColorStop(0, rgba(c, .13)); g.addColorStop(1, rgba(c, 0));
    x.fillStyle = g; x.beginPath(); x.arc(cx, cy, R * 1.5, 0, 7); x.fill();
    // atom orbits (nuclear)
    for (let k = 0; k < 3; k++) { const rot = k * Math.PI / 3 + t * .12;
      x.strokeStyle = rgba(c, .16); x.lineWidth = 1; x.beginPath(); x.ellipse(cx, cy, R * 1.4, R * .44, rot, 0, 7); x.stroke();
      const a = t * (1.1 + k * .3) + k * 2, ex = Math.cos(a) * R * 1.4, ey = Math.sin(a) * R * .44;
      const px = cx + ex * Math.cos(rot) - ey * Math.sin(rot), py = cy + ex * Math.sin(rot) + ey * Math.cos(rot);
      x.fillStyle = rgba(o, .95); x.beginPath(); x.arc(px, py, 2.4, 0, 7); x.fill(); }
    // pipe shell: outer rings, 12 longitudinal lines, inner bore
    const shell = (seg, bright) => { const rings3 = seg.map(sg => ring(sg.p, sg.t, sg.r, 24)), bore = seg.map(sg => ring(sg.p, sg.t, sg.r * .86, 24));
      x.lineWidth = 1;
      rings3.forEach((q, i) => { if (i % 2) return; x.strokeStyle = rgba(c, .14 + Math.max(0, q[0][2]) * .2); path(q); });
      for (let j = 0; j < 24; j += 2) { x.strokeStyle = rgba(c, bright); path(rings3.map(q => q[j])); }
      for (let j = 1; j < 24; j += 6) { x.strokeStyle = rgba(c, .16); x.setLineDash([3, 4]); path(bore.map(q => q[j])); x.setLineDash([]); }
      return rings3; };
    const mainR = shell(SP.main, .55), brR = shell(SP.branch, .5);
    // tee crotch saddle (where the branch meets the run)
    x.strokeStyle = rgba(o, .8); x.lineWidth = 1.5; path(ring([-.62, -.5, SP.R0 * .98], [0, 0, 1], SP.R0 * .93, 24));
    // weld seams + numbered tags
    for (const w of SP.welds) { const sg = w.seg[Math.min(w.i, w.seg.length - 1)], q = ring(sg.p, sg.t, sg.r * 1.03, 24);
      x.strokeStyle = rgba(o, .9); x.lineWidth = 1.7; path(q);
      x.strokeStyle = rgba(o, .45); x.lineWidth = 1; x.setLineDash([1, 2]); path(ring(sg.p, sg.t, sg.r * 1.09, 24)); x.setLineDash([]);
      const tp = P3(V.add(sg.p, [0, sg.r * 2.1, 0])); x.strokeStyle = rgba(o, .5); x.beginPath(); x.moveTo(q[6][0], q[6][1]); x.lineTo(tp[0], tp[1]); x.stroke();
      x.strokeStyle = rgba(o, .8); x.strokeRect(tp[0] - 9, tp[1] - 12, 18, 11); label(w.n, tp[0], tp[1] - 3, o, 8, "center", .95); }
    // flanges: WN raised face with bolt circle (8 bolts) + nuts
    const flange = (sg, dir, rr, nb) => { const p0 = sg.p, p1 = V.add(p0, V.mul(sg.t, .045 * dir)), p2 = V.add(p0, V.mul(sg.t, -.05 * dir));
      x.strokeStyle = rgba(c, .95); x.lineWidth = 1.4; path(ring(p0, sg.t, rr, 32)); path(ring(p1, sg.t, rr, 32));
      x.strokeStyle = rgba(c, .5); x.lineWidth = 1; path(ring(p1, sg.t, sg.r * 1.25, 24)); path(ring(p2, sg.t, sg.r * 1.12, 24));   // raised face + hub
      const A = ring(p0, sg.t, rr, 32), B = ring(p1, sg.t, rr, 32); for (let i = 0; i < 32; i += 4) { x.beginPath(); x.moveTo(A[i][0], A[i][1]); x.lineTo(B[i][0], B[i][1]); x.stroke(); }
      const bolts = ring(V.add(p1, V.mul(sg.t, .02 * dir)), sg.t, rr * .78, nb);
      for (let i = 0; i < nb; i++) { x.fillStyle = rgba(o, .95); x.beginPath(); x.arc(bolts[i][0], bolts[i][1], 1.9, 0, 7); x.fill();
        x.strokeStyle = rgba(o, .45); x.beginPath(); x.arc(bolts[i][0], bolts[i][1], 3.6, 0, 7); x.stroke(); } };
    flange(SP.main[0], -1, SP.R0 * 2, 8); flange(SP.main[SP.main.length - 1], 1, SP.R0 * 2, 8); flange(SP.branch[SP.branch.length - 1], 1, SP.R0 * 1.25, 4);
    // gate valve on the riser: body block, bonnet, stem + handwheel
    const vs = SP.main[SP.valveAt], vb = SP.R0 * 1.5, box = [];
    for (const dy of [-1, 1]) for (const dx of [-1, 1]) for (const dz of [-1, 1]) box.push(P3(V.add(vs.p, [dx * vb, dy * vb * .9, dz * vb * .8])));
    x.strokeStyle = rgba(c, .95); x.lineWidth = 1.3; [[0, 1], [1, 3], [3, 2], [2, 0], [4, 5], [5, 7], [7, 6], [6, 4], [0, 4], [1, 5], [2, 6], [3, 7]].forEach(([i, j]) => { x.beginPath(); x.moveTo(box[i][0], box[i][1]); x.lineTo(box[j][0], box[j][1]); x.stroke(); });
    const st0 = P3(V.add(vs.p, [vb, 0, 0])), st1 = P3(V.add(vs.p, [vb * 3.2, 0, 0]));
    x.beginPath(); x.moveTo(st0[0], st0[1]); x.lineTo(st1[0], st1[1]); x.stroke();
    const hw = ring(V.add(vs.p, [vb * 3.2, 0, 0]), [1, 0, 0], vb * 1.3, 28); x.strokeStyle = rgba(o, .95); x.lineWidth = 1.6; path(hw);
    for (let i = 0; i < 28; i += 7) { x.beginPath(); x.moveTo(st1[0], st1[1]); x.lineTo(hw[i][0], hw[i][1]); x.stroke(); }
    // support shoe under the run
    const sh = SP.main[5].p, s1 = P3(V.add(sh, [-.08, -SP.R0, 0])), s2 = P3(V.add(sh, [.08, -SP.R0, 0])), s3 = P3(V.add(sh, [.12, -.36, 0])), s4 = P3(V.add(sh, [-.12, -.36, 0]));
    x.strokeStyle = rgba(c, .6); x.lineWidth = 1; path([s1, s2, s3, s4], true);
    x.strokeStyle = rgba(c, .3); for (let i = -2; i <= 2; i++) { const a2 = P3(V.add(sh, [i * .06, -.36, 0])), b2 = P3(V.add(sh, [i * .06 - .04, -.42, 0])); x.beginPath(); x.moveTo(a2[0], a2[1]); x.lineTo(b2[0], b2[1]); x.stroke(); }
    // fluid flow along the main run and into the branch
    const along = (seg, f) => { const L2 = seg.length - 1, k = f * L2, a2 = Math.floor(k), b2 = Math.min(L2, a2 + 1), u = k - a2; return V.add(seg[a2].p, V.mul(V.add(seg[b2].p, V.mul(seg[a2].p, -1)), u)); };
    for (let i = 0; i < flow.length; i++) { flow[i] = (flow[i] + .0022 * (st === "thinking" ? 3 : 1)) % 1;
      const [px, py] = P3(i % 5 === 0 ? along(SP.branch, flow[i]) : along(SP.main, flow[i])); x.fillStyle = rgba(o, .85); x.beginPath(); x.arc(px, py, 1.7, 0, 7); x.fill(); }
    // dimension line + callouts
    const d1 = P3([-1.15, -.92, 0]), d2 = P3([-.12, -.92, 0]);
    x.strokeStyle = rgba(o, .5); x.lineWidth = 1; x.beginPath(); x.moveTo(d1[0], d1[1]); x.lineTo(d2[0], d2[1]); x.stroke();
    [d1, d2].forEach(d => { x.beginPath(); x.moveTo(d[0], d[1] - 5); x.lineTo(d[0], d[1] + 5); x.stroke(); });
    label("1030", (d1[0] + d2[0]) / 2, (d1[1] + d2[1]) / 2 - 5, o, 9, "center", .8);
    const call = (pt, dx, dy, txt) => { const p0 = P3(pt); x.strokeStyle = rgba(o, .45); x.beginPath(); x.moveTo(p0[0], p0[1]); x.lineTo(p0[0] + dx, p0[1] + dy); x.lineTo(p0[0] + dx + (dx > 0 ? 18 : -18), p0[1] + dy); x.stroke();
      x.fillStyle = rgba(o, .9); x.beginPath(); x.arc(p0[0], p0[1], 1.8, 0, 7); x.fill(); label(txt, p0[0] + dx + (dx > 0 ? 20 : -20), p0[1] + dy + 3, o, 9, dx > 0 ? "left" : "right", .85); };
    call(SP.main[SP.main.length - 1].p, R * .3, -R * .16, "WN FLG #300");
    call([-.62, -.5, 0], R * .1, R * .6, "TEE");
    label("SPOOL SP-01 · 6\" SCH40 · TP316L", cx, cy - R * 1.15, c, 10, "center", .75);
    label("6 WELDS · 100% RT", cx, cy + R * 1.32, c, 9, "center", .45);
    // jet climbing past (aerospace)
    const ja = (t * .16) % 1, jx = cx - R * 1.9 + ja * R * 3.8, jy = cy + R * .95 - Math.sin(ja * Math.PI) * R * 2;
    x.strokeStyle = rgba(c, .22); x.beginPath(); for (let i = 0; i <= 30; i++) { const f = i / 30 * ja, qx = cx - R * 1.9 + f * R * 3.8, qy = cy + R * .95 - Math.sin(f * Math.PI) * R * 2; i ? x.lineTo(qx, qy) : x.moveTo(qx, qy); } x.stroke();
    const dir = Math.atan2(-Math.cos(ja * Math.PI) * Math.PI * R * 2, R * 3.8);
    x.save(); x.translate(jx, jy); x.rotate(dir); x.fillStyle = rgba(o, .95); x.beginPath(); x.moveTo(8, 0); x.lineTo(-6, -5); x.lineTo(-3, 0); x.lineTo(-6, 5); x.closePath(); x.fill(); x.restore();
  }
  function forgeSparks(cx, cy, R){
    if (Math.random() < .6) for (let i = 0; i < 3; i++) { const a = Math.random() * 6.28; fsparks.push({ x: cx + Math.cos(a) * R, y: cy + Math.sin(a) * R, vx: Math.cos(a) * (2 + Math.random() * 3), vy: Math.sin(a) * (2 + Math.random() * 3) - 1.5, l: 1 }); }
    for (let i = fsparks.length - 1; i >= 0; i--) { const p = fsparks[i]; p.x += p.vx; p.y += p.vy; p.vy += .12; p.l -= .025; if (p.l <= 0) { fsparks.splice(i, 1); continue; }
      x.strokeStyle = rgba(C.o, p.l); x.lineWidth = 1.4; x.beginPath(); x.moveTo(p.x, p.y); x.lineTo(p.x - p.vx * 2.2, p.y - p.vy * 2.2); x.stroke(); }
  }
  function label(txt, px, py, c, size = 11, align = "center", a = .9){ x.font = `600 ${size}px "JetBrains Mono",monospace`; x.textAlign = align; x.fillStyle = rgba(c, a); x.fillText(txt, px, py); }
  const typed = (s, since, cps = 60) => s.slice(0, Math.max(0, Math.floor((t - since) * cps)));
  function kpiBars(cx, cy, R, c){
    const ks = scene.kpis, n = ks.length, mx = Math.max(...ks.map(k => Math.abs(k.value) || 0), 1e-9), bw = Math.min(46, W * .6 / n), gap = bw * .55;
    const total = n * bw + (n - 1) * gap, x0 = cx - total / 2, base = cy + R * .9, hmax = R * 1.7, grow = Math.min(1, (t - born) / 1.1);
    ks.forEach((k, i) => {
      const v = Math.abs(k.value) || 0, h = Math.max(4, v / mx * hmax * (1 - Math.pow(1 - grow, 3)) * (k.format === "percent" ? .9 : 1)), bx = x0 + i * (bw + gap), d = bw * .35;
      const cc = i % 3 === 2 ? C.o : c;
      x.fillStyle = rgba(cc, .16); x.fillRect(bx, base - h, bw, h);
      x.fillStyle = rgba(cc, .32); x.beginPath(); x.moveTo(bx, base - h); x.lineTo(bx + d, base - h - d * .6); x.lineTo(bx + bw + d, base - h - d * .6); x.lineTo(bx + bw, base - h); x.fill();
      x.fillStyle = rgba(cc, .1); x.beginPath(); x.moveTo(bx + bw, base - h); x.lineTo(bx + bw + d, base - h - d * .6); x.lineTo(bx + bw + d, base - d * .6); x.lineTo(bx + bw, base); x.fill();
      x.strokeStyle = rgba(cc, .9); x.lineWidth = 1.2; x.strokeRect(bx, base - h, bw, h);
      for (let yy = base - 6; yy > base - h; yy -= 7) { x.strokeStyle = rgba(cc, .18); x.beginPath(); x.moveTo(bx, yy); x.lineTo(bx + bw, yy); x.stroke(); }
      const val = (k.format === "percent" ? k.value.toFixed(2) + "%" : k.value.toLocaleString("en-IN", { maximumFractionDigits: 1 }));
      label(typed(val, born + .5 + i * .12, 40), bx + bw / 2 + d / 2, base - h - d - 6, cc, 11);
      const maxc = Math.max(4, Math.floor((bw + gap) * 1.9 / 5.6));
      label(typed(String(k.label).toUpperCase().slice(0, maxc), born + .2 + i * .1, 50), bx + bw / 2, base + 15 + (i % 2) * 12, cc, 8.5, "center", .75);
    });
    x.strokeStyle = rgba(c, .5); x.beginPath(); x.moveTo(x0 - 20, base); x.lineTo(x0 + total + 30, base); x.stroke();
  }
  function panel(cx, cy, R, c){
    const pw = Math.min(W * .78, 520), ph = R * 2.1, px = cx - pw / 2, py = cy - ph / 2 - 4, sk = .08;
    x.save(); x.translate(cx, cy); x.transform(1, 0, -sk, 1, 0, 0); x.translate(-cx, -cy);
    x.fillStyle = rgba(c, .06); x.fillRect(px, py, pw, ph); x.strokeStyle = rgba(c, .7); x.lineWidth = 1.2; x.strokeRect(px, py, pw, ph);
    x.fillStyle = rgba(c, .25); x.fillRect(px, py, pw, 20);
    label(typed(scene.title.toUpperCase().slice(0, 58), born, 70), px + 10, py + 14, c, 10.5, "left", 1);
    const rows = scene.rows, cols = Math.min(scene.cols.length, 5), cw = (pw - 20) / cols;
    scene.cols.slice(0, cols).forEach((h, j) => label(typed(String(h).toUpperCase().slice(0, 14), born + .2, 60), px + 10 + j * cw, py + 36, C.o, 9, "left"));
    rows.slice(0, 6).forEach((r, i) => r.slice(0, cols).forEach((v, j) => {
      const s = v == null ? "" : typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : String(v);
      label(typed(s.slice(0, 15), born + .35 + i * .14, 55), px + 10 + j * cw, py + 56 + i * ((ph - 66) / 6), c, 10, "left", .85);
    }));
    const sy = py + ((t * 60) % ph); x.fillStyle = rgba(c, .12); x.fillRect(px, sy, pw, 3);
    x.restore();
  }
  function screens(cx, cy, R, c){
    for (let i = 0; i < 3; i++) { const w = R * 1.5, h = R * .95, ox = cx + (i - 1) * w * .55, oy = cy - R * .3 + i * 14 + Math.sin(t * 1.2 + i) * 3;
      x.fillStyle = rgba(i === 1 ? C.o : c, .07); x.fillRect(ox - w / 2, oy - h / 2, w, h); x.strokeStyle = rgba(i === 1 ? C.o : c, .75); x.strokeRect(ox - w / 2, oy - h / 2, w, h);
      for (let b = 0; b < 6; b++) { const bh = (Math.sin(b * 1.7 + i + t * .6) * .5 + .6) * h * .55; x.fillStyle = rgba(c, .35); x.fillRect(ox - w / 2 + 8 + b * (w - 16) / 6, oy + h / 2 - 8 - bh, (w - 16) / 8, bh); } }
    label(typed((scene.title || "DASHBOARD READY").toUpperCase().slice(0, 40), born, 60), cx, cy + R * 1.05, c, 11);
  }
  function prism(cx, cy, R, c, lock){
    const p = 1 + Math.sin(t * 6) * .06;
    x.strokeStyle = rgba(c, .9); x.lineWidth = 2;
    if (lock) { x.strokeRect(cx - R * .5, cy - R * .2, R, R * .8); x.beginPath(); x.arc(cx, cy - R * .2, R * .32, Math.PI, 0); x.stroke(); x.beginPath(); x.arc(cx, cy + R * .18, R * .09, 0, 7); x.stroke(); }
    else { x.beginPath(); x.moveTo(cx, cy - R * p); x.lineTo(cx + R * .9 * p, cy + R * .6 * p); x.lineTo(cx - R * .9 * p, cy + R * .6 * p); x.closePath(); x.stroke(); label("!", cx, cy + R * .35, c, R * .7 | 0); }
    for (let i = 0; i < 3; i++) { x.strokeStyle = rgba(c, .35 - i * .1); x.beginPath(); x.arc(cx, cy, R * (1.3 + ((t * .8 + i / 3) % 1) * .9), 0, 7); x.stroke(); }
    label(typed(lock ? "ACCESS RESTRICTED" : "ATTENTION REQUIRED", born, 40), cx, cy + R * 1.4, c, 11);
  }
  function think(cx, cy, R, c){
    x.lineWidth = 2;
    for (let i = 0; i < 48; i++) { const a = t * 2.2 + i / 48 * Math.PI * 2, rr = R * (.95 + Math.sin(i * 3 + t * 4) * .08);
      x.strokeStyle = rgba(i % 7 ? c : C.o, .7); x.beginPath(); x.ellipse(cx, cy, rr, rr * .36, 0, a, a + .07); x.stroke(); }
    x.font = '600 10px "JetBrains Mono",monospace'; x.textAlign = "left";
    streams.forEach(s => { s.y += s.v * .012; if (s.y > 1) { s.y = 0; s.x = Math.random(); s.s = CODE[Math.random() * CODE.length | 0]; }
      x.fillStyle = rgba(c, .25 + s.v * .5); x.fillText(s.s, s.x * (W - 80) + 10, s.y * H * .72); });
    const sw = (t * 1.6) % 1; x.strokeStyle = rgba(c, .5); x.beginPath(); x.arc(cx, cy, R * .55, -Math.PI / 2, -Math.PI / 2 + sw * Math.PI * 2); x.stroke();
    label("ANALYSING" + ".".repeat(1 + (t * 3 | 0) % 3), cx, cy + R * 1.25, c, 11);
  }
  function eq(cx, cy, R, c){
    for (let i = 0; i < 64; i++) { const a = i / 64 * Math.PI * 2, v = (Math.sin(i * .9 + t * 9) * .5 + .5) * (.2 + VLVL * 1.4) + .08, r0 = R * 1.08, r1 = r0 + v * R * .6;
      x.strokeStyle = rgba(i % 2 ? C.o : c, .8); x.lineWidth = 2; x.beginPath(); x.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0 * .5); x.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1 * .5); x.stroke(); }
  }
  function frame(now){
    const dt = Math.min(.05, (now - last) / 1000); last = now;
    if (on && !document.hidden && W > 0 && cv.offsetParent !== null) {
      t += dt; x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, W, H); x.globalCompositeOperation = "lighter";
      const c = col(), cx = W / 2, cy = H * .4, R = Math.min(W * .2, H * .26);
      if (!forgeOn) floor(c);                          // Forge draws its own projector platform
      const flick = .85 + Math.random() * .15 * (glitch > 0 ? 3 : .4); x.globalAlpha = Math.min(1, flick);
      if (st === "thinking") think(cx, cy, R, c);
      else if (scene.k === "kpi") { kpiBars(cx, cy, R, c); rings(cx, cy + R * .95, R * .55, c, .6); }
      else if (scene.k === "table") panel(cx, cy, R, c);
      else if (scene.k === "files") screens(cx, cy, R, c);
      else if (scene.k === "alert" || scene.k === "lock") prism(cx, cy, R * .8, c, scene.k === "lock");
      else if (atlasOn && typeof Atlas !== "undefined") Atlas.draw(x, cx, cy, R * .8, c, C.o, t);
      else if (titanOn) titan(cx, cy, R * .8, c);
      else if (forgeOn) { if (typeof Forge3D === "undefined" || !Forge3D.active) forge(cx, cy, R * .8, c); else if (st === "listening") rings(cx, cy, R * .7, c, 2 + VLVL * 4); }   // 3D steel scene is drawn by Forge3D
      else if (nova) reactor(cx, cy, R * .82, c);
      else { globe(cx, cy, R * .9, c); rings(cx, cy, R * .9, c, st === "listening" ? 2 + VLVL * 4 : 1); }
      if (st === "speaking") eq(cx, cy, R * .9, c);
      x.globalAlpha = 1;
      for (let y = 0; y < H; y += 3) { x.fillStyle = "rgba(0,0,0,.18)"; x.fillRect(0, y, W, 1); }            // scan lines
      if (glitch > 0) { glitch -= dt; for (let i = 0; i < 6; i++) { const y = Math.random() * H, h = 4 + Math.random() * 14, o = (Math.random() - .5) * 30;
          x.drawImage(cv, 0, y * dpr, W * dpr, h * dpr, o, y, W, h); } }
      x.globalCompositeOperation = "source-over";
    }
    if (!REDUCE) requestAnimationFrame(frame); else setTimeout(() => requestAnimationFrame(frame), 33);   // calm motion (e.g. Remote Desktop): slow, never blank
  }
  requestAnimationFrame(frame);
  function setScene(s){ scene = s; born = t; glitch = .35; }
  return {
    theme(th){ on = th === "holo" || th === "nova" || th === "forge" || th === "titan" || th === "atlas"; nova = th === "nova"; forgeOn = th === "forge"; titanOn = th === "titan" || th === "atlas"; atlasOn = th === "atlas";
      C = PAL[titanOn ? "titan" : forgeOn ? "forge" : nova ? "nova" : "holo"]; HoloAudio.mode(th);
      if (on) { fit(); HoloAudio.start(); } else HoloAudio.stop(); $("#bgmBtn")?.classList.toggle("off", !HoloAudio.on); if (!on && $("#sndPop")) $("#sndPop").hidden = true; },
    state(s){ const prev = st; st = s; HoloAudio.busy(s === "thinking"); HoloAudio.duck(s === "speaking");
      if (on && s === "thinking" && prev !== "thinking") { glitch = .3; HoloAudio.whoosh(); } },
    react(r){
      if (!r) return; const txt = r.text || "";
      if (r.denied || /🔒|not in your access/i.test(txt)) { setScene({ k: "lock" }); HoloAudio.alert(); }
      else if (/⚠️|error|not found|failed/i.test(txt) && !(r.kpis || []).length) { setScene({ k: "alert" }); HoloAudio.alert(); }
      else { setScene({ k: "idle" }); HoloAudio.success(); }
    },
  };
})();

/* hooks: state changes, answers (typing effect), first tap starts the sound */
{
  const _setState = setState;
  setState = function(st){ _setState(st); Holo.state(st === "busy" ? "thinking" : st); };
  const _render = renderReply;
  renderReply = function(r, el){
    const out = _render(r, el);
    if (document.body.classList.contains("theme-holo")) {
      Holo.react(r);
      const bt = out && out.querySelector(".bt");
      if (bt && !REDUCE) {                        // type the answer in: fast, ~1 s max, keyboard ticks
        const nodes = []; const w = document.createTreeWalker(bt, NodeFilter.SHOW_TEXT); let n; while ((n = w.nextNode())) { nodes.push([n, n.textContent]); n.textContent = ""; }
        const total = nodes.reduce((a, [, s]) => a + s.length, 0), per = Math.max(1, Math.ceil(total / 70)); let i = 0;
        bt.classList.add("typing-on");
        const iv = setInterval(() => {
          let left = per;
          while (left > 0 && i < nodes.length) { const [nd, s] = nodes[i]; const k = Math.min(left, s.length - nd.textContent.length); nd.textContent = s.slice(0, nd.textContent.length + k); left -= k; if (nd.textContent.length >= s.length) i++; }
          HoloAudio.key(); $("#log").scrollTop = $("#log").scrollHeight;
          if (i >= nodes.length) { clearInterval(iv); bt.classList.remove("typing-on"); }
        }, 14);
      }
    }
    return out;
  };
  const kick = () => HoloAudio.start();
  addEventListener("pointerdown", kick); addEventListener("keydown", kick);
  /* ♪ opens one small panel: music on / while working / off · screen sounds · idle screens */
  const b = $("#bgmBtn"), pop = $("#sndPop");
  const paint = () => { if (!pop) return;
    pop.querySelectorAll("[data-music]").forEach(x => x.classList.toggle("on", x.dataset.music === HoloAudio.music));
    $("#sfxTgl").checked = HoloAudio.sfx; $("#idleTgl").checked = store.get("rb_idle_screens") !== "0";
    b.classList.toggle("off", !HoloAudio.on); b.title = "Sound & screens"; };
  if (b && pop) {
    document.body.appendChild(pop);                       // outside the top bar so it floats above the chat window
    const place = () => { const r = b.getBoundingClientRect(); pop.style.top = Math.round(r.bottom + 8) + "px"; pop.style.right = Math.round(innerWidth - r.right) + "px"; };
    addEventListener("resize", () => { if (!pop.hidden) place(); });
    b.onclick = e => { e.stopPropagation(); HoloAudio.start(); pop.hidden = !pop.hidden; if (!pop.hidden) place(); paint(); };
    pop.addEventListener("click", e => { e.stopPropagation(); const m = e.target.closest("[data-music]"); if (m) { HoloAudio.setMusic(m.dataset.music); paint(); } });
    $("#sfxTgl").onchange = e => { HoloAudio.setSfx(e.target.checked); paint(); };
    $("#idleTgl").onchange = e => { store.set("rb_idle_screens", e.target.checked ? "1" : "0"); if (typeof HoloOS !== "undefined") HoloOS.idle(e.target.checked); paint(); };
    addEventListener("click", () => { pop.hidden = true; });
    addEventListener("keydown", e => { if (e.key === "Escape") pop.hidden = true; });
    paint();
  }
}


/* ---------------- TITAN: fighter-jet hologram screen (draws on every canvas.jetcv inside a hologram screen)
   A 3D wireframe delta-wing fighter banks and turns in the middle; a two-ship formation streaks past with
   afterburner trails; a radar lock reticle tracks the lead. Original drawing - no real aircraft model. */
const JetFx = (() => {
  // top-view planform of an original twin-tail delta fighter (x = forward, y = right), mirrored for the left side
  const HALF = [[5, 0], [3.6, .32], [2.1, .55], [1.1, .72], [.4, .8], [.1, .86], [-2.2, 3.4], [-2.95, 3.4], [-2.6, .95], [-3.1, .9], [-4.25, 2.05], [-4.75, 2.05], [-4.45, .8], [-4.7, .5], [-5, .32], [-5, 0]];
  const OUT = [...HALF, ...HALF.slice(0, -1).reverse().map(([a, b]) => [a, -b])];
  let t = 0, last = performance.now();
  const col = () => { const cs = getComputedStyle(document.body); return [cs.getPropertyValue("--ac").trim() || "#55b8ff", cs.getPropertyValue("--gold").trim() || "#a8e4ff"]; };
  const rgba = (hex, a) => { const h = hex.replace("#", ""), n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };
  function jet(x, cx, cy, S, head, bank, c, g, a = 1, detail = true){
    const cb = Math.cos(bank), sk = Math.sin(bank) * .18;                         // banking: wings foreshorten + slight skew
    const T = ([px, py]) => { const yy = py * cb, xx = px + py * sk; return [cx + (xx * Math.cos(head) - yy * Math.sin(head)) * S, cy + (xx * Math.sin(head) + yy * Math.cos(head)) * S]; };
    const poly = (pts, close) => { x.beginPath(); pts.map(T).forEach((p, i) => i ? x.lineTo(p[0], p[1]) : x.moveTo(p[0], p[1])); if (close) x.closePath(); };
    poly(OUT, true); x.fillStyle = rgba(c, .1 * a); x.fill(); x.strokeStyle = rgba(c, .95 * a); x.lineWidth = detail ? 1.4 : 1.1; x.stroke();
    if (!detail) return T([-5, 0]);
    x.lineWidth = 1; x.strokeStyle = rgba(c, .45 * a);
    poly([[4.6, 0], [-4.9, 0]]); x.stroke();                                                   // spine
    for (const s2 of [1, -1]) {
      poly([[1.1, .72 * s2], [-2.4, .9 * s2]]); x.stroke();                                      // intake / fuselage edge
      poly([[.1, .86 * s2], [-2.6, 2.6 * s2]]); x.stroke();                                      // wing spar
      x.strokeStyle = rgba(g, .8 * a); x.lineWidth = 1.6; poly([[-2.9, .55 * s2], [-4.5, .72 * s2]]); x.stroke();   // canted fins
      x.lineWidth = 1; x.strokeStyle = rgba(c, .45 * a);
      const tip = T([-2.6, 3.4 * s2]); x.fillStyle = rgba(g, .9 * a); x.beginPath(); x.arc(tip[0], tip[1], 1.6, 0, 7); x.fill(); }   // wing-tip lights
    const cp = T([2.7, 0]); x.strokeStyle = rgba(g, .85 * a); x.beginPath(); x.ellipse(cp[0], cp[1], .95 * S, .3 * S * Math.max(.4, cb), head, 0, 7); x.stroke();   // canopy
    for (const s2 of [1, -1]) { const m = T([-1.2, 2 * s2]); x.strokeStyle = rgba(c, .7 * a); x.beginPath(); x.moveTo(m[0], m[1]); const m2 = T([.2, 2 * s2]); x.lineTo(m2[0], m2[1]); x.stroke(); }   // missiles
    return T([-5, 0]);
  }
  function draw(cv){
    const w = cv.clientWidth, h = cv.clientHeight; if (!w || !h) return;
    const dpr = Math.min(devicePixelRatio || 1, 2); if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const x = cv.getContext("2d"), [c, g] = col(); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, w, h);
    x.strokeStyle = rgba(c, .07); x.lineWidth = 1; for (let gx = .5; gx < w; gx += 16) { x.beginPath(); x.moveTo(gx, 0); x.lineTo(gx, h); x.stroke(); } for (let gy = .5; gy < h; gy += 16) { x.beginPath(); x.moveTo(0, gy); x.lineTo(w, gy); x.stroke(); }
    const cx = w / 2, cy = h * .55, rr = Math.min(w, h) * .36;
    // radar range rings + sweep
    x.strokeStyle = rgba(c, .16); for (let i = 1; i <= 3; i++) { x.beginPath(); x.arc(cx, cy, rr * i / 3 * 1.25, 0, 7); x.stroke(); }
    const sa = t * 1.3, sg = x.createConicGradient ? x.createConicGradient(sa - .9, cx, cy) : null;
    if (sg) { sg.addColorStop(0, rgba(c, 0)); sg.addColorStop(.14, rgba(c, .18)); sg.addColorStop(.145, rgba(c, 0)); x.fillStyle = sg; x.beginPath(); x.arc(cx, cy, rr * 1.25, 0, 7); x.fill(); }
    // wingmen: two-ship formation crossing with afterburner trails
    for (let k = 0; k < 2; k++) { const f = ((t * .16 + k * .07) % 1), px = -40 + f * (w + 80), py = h * .24 + k * 16;
      const tr = x.createLinearGradient(px - 80, 0, px - 10, 0); tr.addColorStop(0, rgba(g, 0)); tr.addColorStop(1, rgba(g, .6)); x.strokeStyle = tr; x.lineWidth = 2;
      x.beginPath(); x.moveTo(px - 80, py); x.lineTo(px - 10, py); x.stroke();
      jet(x, px, py, 2.1, 0, .2, c, g, .9, false); }
    // lead fighter: turning slowly, banking into the turn
    const head = t * .35, bank = Math.sin(t * .7) * .6, S = Math.min(w * .048, h * .072);
    const nz = jet(x, cx, cy, S, head, bank, c, g, 1, true);
    const fl = 4 + Math.random() * 3, gr = x.createRadialGradient(nz[0], nz[1], 0, nz[0], nz[1], fl * 2.2); gr.addColorStop(0, rgba(g, .95)); gr.addColorStop(1, rgba(g, 0));
    x.fillStyle = gr; x.beginPath(); x.arc(nz[0], nz[1], fl * 2.2, 0, 7); x.fill();
    // lock brackets
    const lk = (Math.sin(t * 2.2) + 1) / 2, b = S * 5.8 + lk * 4; x.strokeStyle = rgba(g, .85); x.lineWidth = 1.4;
    for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) { x.beginPath(); x.moveTo(cx + sx * b, cy + sy * (b - 8)); x.lineTo(cx + sx * b, cy + sy * b); x.lineTo(cx + sx * (b - 8), cy + sy * b); x.stroke(); }
    x.font = '600 9px "JetBrains Mono",monospace'; x.fillStyle = rgba(g, .9); x.textAlign = "left";
    x.fillText("LOCK ◆ LEAD", 8, 13); x.textAlign = "right"; x.fillText(`M ${(1.4 + Math.sin(t * .5) * .3).toFixed(2)} · FL${Math.round(380 + Math.sin(t * .3) * 40)}`, w - 8, 13);
    x.textAlign = "left"; x.fillStyle = rgba(c, .6); x.fillText("Ti-6Al-4V AIRFRAME · HYDRAULIC TUBING", 8, h - 6);
  }
  (function frame(now){
    t += Math.min(.05, (now - last) / 1000); last = now;
    if (!document.hidden) document.querySelectorAll("canvas.jetcv").forEach(cv => { try { draw(cv); } catch {} });
    requestAnimationFrame(frame);
  })(performance.now());
  return {};
})();
