/* ---------------- voice: VERONICA listens (Gemini or browser) and speaks (Gemini voice) */
const Voice = {
  speakAll: store.get("rb_speak") !== "0", talk: false, audio: null, rec: null, ctx: null,
  hint(){ return $("#lang").value; },
  audioCtx(){ try { this.ctx = this.ctx || new (window.AudioContext || window.webkitAudioContext)(); if (this.ctx.state === "suspended") this.ctx.resume(); } catch {} return this.ctx; },

  /* ---- speaking: answer is split into sentences; the first one plays while the rest are still being made */
  gen: 0,
  stop(){ this.gen++; try { this.audio && this.audio.pause(); } catch {} this.audio = null; try { speechSynthesis.cancel(); } catch {}
          setLvl(1); },
  chunks(text){
    const t = String(text).replace(/```[\s\S]*?```/g, " ").replace(/\|[^\n]*\|/g, " ").trim();
    const parts = t.split(/(?<=[.!?।])\s+|\n+/).map(x => x.trim()).filter(x => x.replace(/[^\p{L}\p{N}]/gu, "").length > 1);
    const out = [];
    for (const p of parts) {                       // first chunk short (fast start), later ones bigger
      const lim = out.length === 0 ? 90 : 260;
      if (out.length && (out[out.length - 1] + " " + p).length <= lim && out.length > 0 && out.length !== 1) out[out.length - 1] += " " + p;
      else out.push(p);
    }
    return out.slice(0, 8);
  },
  tts(text, tries = 2){
    return fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
                               body: JSON.stringify({ text, lang: this.hint() }) })
      .then(r => { this.lastStatus = r.status; this.backup = r.headers.get("X-Voice") === "backup"; return r.ok ? r.blob() : null; }).catch(() => null)
      .then(b => b || (tries > 1 && this.lastStatus !== 429 ? new Promise(r => setTimeout(r, 1500)).then(() => this.tts(text, tries - 1)) : null));
  },
  async say(text, opts = {}){
    this.stop();
    if (!text) return;
    const my = this.gen;
    setState("speaking");
    try {
      if (!ME?.voice) await this._browser(text);
      else {
        let parts = this.chunks(text);
        if (ME?.voice_one_clip && !this.backup && parts.length > 1) {      // backup voice: sentence by sentence (starts sooner)                  // one request per answer (saves the daily voice limit)
          let one = ""; for (const p of parts) { if ((one + " " + p).length > 420 && one) break; one = (one + " " + p).trim(); }
          parts = [one];
        }
        const jobs = parts.map(p => this.tts(p));            // all requested at once, played in order
        let played = 0;
        for (const job of jobs) {
          const blob = await job;
          if (my !== this.gen) return;                       // user interrupted
          if (blob) { await this._play(blob, my); played++; }
        }
        if (!played) { if (opts.quiet) {} else if (ME?.voice_strict) { if (!this._limitShown || this.lastStatus !== 429) add("bot", this.lastStatus === 429
            ? "🔇 VERONICA's voice limit for today is used up (Gemini free plan: 10 voice clips a day) – answers are shown as text until it resets."
            : "🔇 Voice is busy right now – answer shown as text."); if (this.lastStatus === 429) this._limitShown = true; } else await this._browser(text); }
      }
    } catch (e) { console.warn("voice", e); }
    if (my === this.gen && document.body.classList.contains("speaking")) setState("ready");
  },
  async _play(blob, my){
    if (my !== this.gen) return;
    const url = URL.createObjectURL(blob);
    const a = new Audio(url); this.audio = a;
    const ctx = this.audioCtx(); let raf = 0;
    if (ctx) { try { const src = ctx.createMediaElementSource(a); const an = ctx.createAnalyser(); an.fftSize = 256;
        src.connect(an); an.connect(ctx.destination); const buf = new Uint8Array(an.frequencyBinCount);
        
        const loop = () => { an.getByteFrequencyData(buf); const lvl = buf.reduce((x, y) => x + y, 0) / buf.length / 255;
          setLvl((1 + lvl * 0.9)); raf = requestAnimationFrame(loop); }; loop();
      } catch {} }
    await new Promise(res => { a.onended = a.onerror = a.onpause = res; a.play().catch(res); });
    cancelAnimationFrame(raf); URL.revokeObjectURL(url);
    setLvl(1);
  },

  /* ---- short "one moment" while the report is being prepared (pre-made, plays instantly) */
  ACKS: { "en-IN": "Sure, one moment please.", "hi-IN": "Ji, ek minute, main check kar rahi hoon.",
          "gu-IN": "Ji, ek minute, hu joi rahi chhu.", "mr-IN": "Ho, ek minute, mi baghte.",
          "raj-IN": "Hukum, ek minute, mhain dekh rai hoon.", "or-IN": "ଆଜ୍ଞା, ଗୋଟିଏ ମିନିଟ୍, ମୁଁ ଦେଖୁଛି।" },
  ackCache: {},
  ackLang(q){ return /[\u0B00-\u0B7F]/.test(q) ? "or-IN" : /[઀-૿]/.test(q) ? "gu-IN" : /[ऀ-ॿ]/.test(q) ? (["mr-IN", "raj-IN"].includes(this.hint()) ? this.hint() : "hi-IN")
                     : (this.hint() === "en-IN" && /\b(hai|kya|ka|ki|kitna|batao|kal|aaj|mahine)\b/i.test(q) ? "hi-IN" : this.hint()); },
  prefetchAcks(){ if (!ME?.voice) return; for (const l of new Set([this.hint(), "hi-IN"])) if (!this.ackCache[l])
      this.ackCache[l] = fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({ text: this.ACKS[l], lang: l }) }).then(r => r.ok ? r.blob() : null).catch(() => null); },
  async ack(q){
    if (!ME?.voice) return;
    const l = this.ackLang(q); const blob = await (this.ackCache[l] || Promise.resolve(null));
    if (blob && document.body.classList.contains("busy")) { const my = this.gen; const a = new Audio(URL.createObjectURL(blob)); this.audio = a; a.play().catch(() => {}); }
  },

  _browser(text){   /* fallback when the Gemini key is not set: the device's own voice */
    return new Promise(res => {
      if (!("speechSynthesis" in window)) return res();
      const u = new SpeechSynthesisUtterance(text.replace(/[*_`#]/g, ""));
      u.lang = /[\u0B00-\u0B7F]/.test(text) ? "or-IN" : /[઀-૿]/.test(text) ? "gu-IN" : /[ऀ-ॿ]/.test(text) ? (this.hint() === "mr-IN" ? "mr-IN" : "hi-IN") : (this.hint() === "raj-IN" ? "hi-IN" : this.hint());
      const MALE = /\b(male|man|ravi|hemant|prabhat|madhur|aarav|kunal|rehaan|david|mark|guy|george|james|daniel|niranjan|manohar)\b/i;
      const FEMALE = /female|woman|heera|kalpana|swara|neerja|lekha|aarohi|ananya|aashi|kavya|pallavi|dhwani|sukanya|sapna|zira|aria|jenny|google/i;
      const all = speechSynthesis.getVoices(), same = all.filter(v => v.lang === u.lang || v.lang.startsWith(u.lang.slice(0, 2)));
      u.voice = same.find(x => FEMALE.test(x.name) && !/\bmale\b/i.test(x.name)) || same.find(x => !MALE.test(x.name))
             || all.find(x => /^en-IN|^hi-IN/.test(x.lang) && FEMALE.test(x.name)) || null;
      u.pitch = 1.08;
      u.rate = 0.97; u.onend = u.onerror = res; speechSynthesis.speak(u);
    });
  },

  /* ---- listening */
  async listen(){
    this.stop();
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const gemini = ME?.voice && navigator.mediaDevices?.getUserMedia && window.MediaRecorder;
    if (SR && (ME?.voice_input !== "gemini" || !gemini)) return this._browserListen();   // fastest: live, no upload
    if (gemini) return this._record();
    return this._browserListen();
  },
  async _record(){
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch { add("bot", "🎙️ Microphone permission was refused. Allow the microphone for this site in the browser settings, then try again."); return ""; }
    setState("listening"); $("#mic").classList.add("rec");
    const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find(t => MediaRecorder.isTypeSupported?.(t)) || "";
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined); this.rec = rec;
    const chunks = []; rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    const ctx = this.audioCtx(); let an = null, buf = null;
    if (ctx) { try { const src = ctx.createMediaStreamSource(stream); an = ctx.createAnalyser(); an.fftSize = 1024; src.connect(an); buf = new Float32Array(an.fftSize); } catch { an = null; } }
    const start = performance.now(); let heard = false, lastVoice = start;
    const done = new Promise(res => rec.onstop = res);
    rec.start(250);
    
    await new Promise(res => {
      const tick = () => {
        if (rec.state !== "recording") return res();
        const now = performance.now();
        if (an) { an.getFloatTimeDomainData(buf); const rms = Math.sqrt(buf.reduce((s, x) => s + x * x, 0) / buf.length);
          setLvl((1 + Math.min(rms * 6, .9)));
          if (rms > 0.025) { heard = true; lastVoice = now; } }
        const silentFor = now - lastVoice, total = now - start;
        if ((heard && silentFor > 1000) || (!heard && total > 7000) || total > 45000) { rec.stop(); return res(); }
        requestAnimationFrame(tick);
      }; tick();
    });
    await done; stream.getTracks().forEach(t => t.stop()); this.rec = null;
    $("#mic").classList.remove("rec"); setLvl(1);
    if (!heard && an) { setState("ready"); return ""; }
    setState("thinking"); $("#aiState").textContent = "Hearing";
    const fd = new FormData(); fd.append("audio", new Blob(chunks, { type: rec.mimeType || type || "audio/webm" }), "voice.webm");
    try {
      const r = await fetch("/api/stt", { method: "POST", headers: { Authorization: "Bearer " + token }, body: fd });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "Could not understand");
      return (d.text || "").trim();
    } catch (e) {
      setState("ready");
      if (window.SpeechRecognition || window.webkitSpeechRecognition) {   // Chrome/Edge: listen again with the browser
        add("bot", "🎙️ Voice service is busy – please say it once more.");
        return this._browserListen();
      }
      add("bot", "🎙️ " + esc(e.message)); return "";
    }
    finally { if (!this.rec) setState("ready"); }
  },
  _browserListen(){
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { add("bot", "🎙️ Voice input is not available in this browser. Please use Chrome or Edge, or type."); return Promise.resolve(""); }
    return new Promise(res => {
      const rec = new SR(); this.rec = rec; rec.lang = this.hint() === "raj-IN" ? "hi-IN" : this.hint(); rec.interimResults = true; rec.continuous = false;
      let finalText = ""; setState("listening"); $("#mic").classList.add("rec");
      rec.onresult = e => { const t = Array.from(e.results).map(r => r[0].transcript).join(""); $("#t").value = t; autosize(); finalText = t; };
      rec.onerror = ev => { if (ev.error === "not-allowed") add("bot", "🎙️ Microphone permission was refused. Allow the microphone for this site in the browser settings, then try again."); };
      rec.onend = () => { this.rec = null; $("#mic").classList.remove("rec"); $("#t").value = ""; autosize(); setState("ready"); res(finalText.trim()); };
      try { rec.start(); } catch { res(""); }
    });
  },
  stopListening(){ try { this.rec && this.rec.stop(); } catch {} },

  /* ---- hands-free conversation */
  async talkLoop(){
    if (this.talk) return this.endTalk();
    this.talk = true; this.audioCtx(); $("#talkbar").hidden = false; chatMode(true);
    let empties = 0;
    while (this.talk) {
      const text = await this.listen();
      if (!this.talk) break;
      if (!text) { if (++empties >= 2) break; continue; }
      empties = 0;
      await send(text, { spoken: true });
    }
    this.endTalk();
  },
  endTalk(){ this.talk = false; this.stopListening(); this.stop(); $("#talkbar").hidden = true; setState("ready"); },
};

try { const l = store.get("rb_lang"); if (l) $("#lang").value = l; } catch {}
$("#lang").onchange = () => store.set("rb_lang", $("#lang").value);
const paintSpk = () => { $("#spk").classList.toggle("on", Voice.speakAll); $("#spk").setAttribute("aria-pressed", String(Voice.speakAll)); };
paintSpk();
$("#spk").onclick = () => { Voice.speakAll = !Voice.speakAll; store.set("rb_speak", Voice.speakAll ? "1" : "0"); paintSpk(); if (!Voice.speakAll) Voice.stop(); };
$("#mic").onclick = async () => {
  if (Voice.rec) return Voice.stopListening();
  if (Voice.audio) { Voice.stop(); setState("ready"); return; }
  const text = await Voice.listen();
  if (text) send(text, { spoken: true });
};
/* ---------------- Gemini Live: real-time conversation (streams audio both ways, can be interrupted) */
const MIC_WORKLET = `
class Down16k extends AudioWorkletProcessor {
  constructor(){ super(); this.ratio = sampleRate / 16000; this.acc = []; this.pos = 0; }
  process(inputs){
    const ch = inputs[0] && inputs[0][0]; if (!ch) return true;
    for (let i = 0; i < ch.length; i++) { this.pos += 1; if (this.pos >= this.ratio) { this.pos -= this.ratio; this.acc.push(ch[i]); } }
    if (this.acc.length >= 1600) {                           // 100 ms chunks
      const f = this.acc.splice(0, 1600), pcm = new Int16Array(f.length); let e = 0;
      for (let i = 0; i < f.length; i++) { const v = Math.max(-1, Math.min(1, f[i])); pcm[i] = v * 32767; e += v * v; }
      this.port.postMessage({ pcm: pcm.buffer, rms: Math.sqrt(e / f.length) }, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor("down16k", Down16k);`;
const Live = {
  ws: null, ctx: null, stream: null, node: null, an: null, playHead: 0, sources: [], userEl: null, botEl: null, on: false, raf: 0,
  b64(buf){ let s = ""; const b = new Uint8Array(buf); for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000)); return btoa(s); },
  speaking(){ return this.ctx && this.playHead > this.ctx.currentTime + 0.05; },
  async start(){
    if (this.on) return this.stop();
    this.on = true; Voice.stop(); chatMode(true); $("#talkbar").hidden = false; $("#talkState").textContent = "Connecting…"; setState("thinking");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch { add("bot", "🎙️ Microphone permission was refused. Allow the microphone for this site, then tap Talk again."); return this.stop(); }
    this.ctx = new (window.AudioContext || window.webkitAudioContext)(); await this.ctx.resume();
    this.an = this.ctx.createAnalyser(); this.an.fftSize = 256; this.an.connect(this.ctx.destination);
    await this.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([MIC_WORKLET], { type: "application/javascript" })));
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "down16k"); src.connect(this.node);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/api/live?token=${encodeURIComponent(token)}&lang=${encodeURIComponent(Voice.hint())}`);
    this.ws.onmessage = ev => this.onMsg(JSON.parse(ev.data));
    this.ws.onclose = () => { if (this.on) { add("bot", "🎙️ Voice connection closed. Tap Talk to start again."); this.stop(); } };
    this.ws.onerror = () => {};
    this.node.port.onmessage = ({ data }) => {
      if (!this.ws || this.ws.readyState !== 1) return;
      // while VERONICA speaks, only a clearly louder voice (you interrupting) goes up - avoids hearing her own voice
      const pcm = this.speaking() && data.rms < 0.06 ? new ArrayBuffer(data.pcm.byteLength) : data.pcm;
      this.ws.send(JSON.stringify({ type: "audio", data: this.b64(pcm) }));
      if (!this.speaking()) setLvl((1 + Math.min(data.rms * 6, .9)));
    };
    const loop = () => { if (!this.on) return; if (this.speaking()) { const b = new Uint8Array(this.an.frequencyBinCount); this.an.getByteFrequencyData(b);
        const l = b.reduce((x, y) => x + y, 0) / b.length / 255; setLvl((1 + l * 1.1));
        if (!document.body.classList.contains("speaking")) setState("speaking"); }
      else if (document.body.classList.contains("speaking")) setState("listening");
      this.raf = requestAnimationFrame(loop); }; loop();
  },
  play(b64){
    const raw = atob(b64), n = raw.length >> 1, buf = this.ctx.createBuffer(1, n, 24000), ch = buf.getChannelData(0);
    for (let i = 0; i < n; i++) { let v = raw.charCodeAt(2 * i) | (raw.charCodeAt(2 * i + 1) << 8); if (v >= 32768) v -= 65536; ch[i] = v / 32768; }
    const s = this.ctx.createBufferSource(); s.buffer = buf; s.connect(this.an);
    const t = Math.max(this.ctx.currentTime + 0.03, this.playHead); s.start(t); this.playHead = t + buf.duration;
    this.sources.push(s); s.onended = () => { this.sources = this.sources.filter(x => x !== s); };
  },
  /* "tts" voice mode: mp3 sentences in the chat voice, played back to back in order */
  clipChain: Promise.resolve(), clipGen: 0,
  clip(b64){
    const gen = this.clipGen, bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer;
    const dec = this.ctx.decodeAudioData(bytes).catch(() => null);
    this.clipChain = this.clipChain.then(() => dec).then(buf => {
      if (!buf || gen !== this.clipGen || !this.ctx) return;
      const s = this.ctx.createBufferSource(); s.buffer = buf; s.connect(this.an);
      const t = Math.max(this.ctx.currentTime + 0.03, this.playHead); s.start(t); this.playHead = t + buf.duration;
      this.sources.push(s); s.onended = () => { this.sources = this.sources.filter(x => x !== s); };
    });
  },
  flush(){ this.clipGen++; for (const s of this.sources) { try { s.stop(); } catch {} } this.sources = []; this.playHead = this.ctx ? this.ctx.currentTime : 0; },
  bubble(kind, txt){
    const key = kind === "me" ? "userEl" : "botEl";
    if (!this[key]) { this[key] = add(kind + " live", ""); this[key].dataset.t = ""; }
    this[key].dataset.t += txt; this[key].innerHTML = (kind === "me" ? "🎙️ " : "") + esc(this[key].dataset.t.trim());
    $("#log").scrollTop = $("#log").scrollHeight;
  },
  onMsg(m){
    switch (m.type) {
      case "ready": setState("listening"); $("#talkState").textContent = "Live – listening…";
        { const box = $("#trace"); if (box.querySelector(".empty")) box.innerHTML = "";
          box.insertAdjacentHTML("afterbegin", `<div class="tr done"><i></i><span>Voice connected · ${esc(m.model || "")} · ${esc(m.voice || "")}</span><em>ok</em></div>`); }
        break;
      case "audio": this.play(m.data); break;
      case "clip": this.clip(m.data); break;
      case "heard": if (this.botEl) { this.botEl.classList.remove("live"); this.botEl = null; } this.bubble("me", m.text); break;
      case "said": if (this.userEl) { this.userEl.classList.remove("live"); this.userEl = null; } this.bubble("bot", m.text); break;
      case "interrupted": this.flush(); if (this.botEl) { this.botEl.classList.remove("live"); this.botEl = null; } setState("listening"); break;
      case "turn": for (const k of ["userEl", "botEl"]) if (this[k]) { this[k].classList.remove("live"); this[k] = null; } break;
      case "tool": trace(m); if (m.status === "running") $("#talkState").textContent = "Checking the data…"; else $("#talkState").textContent = "Live – listening…"; break;
      case "report": renderReply(m.reply); loadDashboard(); break;
      case "error": add("bot", "🎙️ " + esc(m.message)); if (/unavailable|not switched on/i.test(m.message)) { this.stop(); Voice.talkLoop(); } break;
    }
  },
  stop(){
    this.on = false; cancelAnimationFrame(this.raf);
    try { this.ws && this.ws.readyState === 1 && this.ws.send(JSON.stringify({ type: "end" })); } catch {}
    try { this.ws && this.ws.close(); } catch {} this.ws = null;
    try { this.stream && this.stream.getTracks().forEach(t => t.stop()); } catch {} this.stream = null;
    try { this.flush(); this.ctx && this.ctx.close(); } catch {} this.ctx = null;
    this.userEl = this.botEl = null; $("#talkbar").hidden = true; setState("ready");
    setLvl(1);
  },
};

