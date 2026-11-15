/* ================================================================ ARC KEYBOARD - holographic curved keyboard
   A rainbow-shaped touch keyboard (rings of keys around a hub) for tablets and touch screens - and a show piece
   on a PC: physical key presses light up the matching arc key. Types into the chat box (#t), SEND submits,
   MIC starts voice. Toggle with the ⌨ button in the top bar; remembered per browser. */
const ArcKey = (() => {
  // DESK: a rainbow over the chat box. PHONE: a quarter fan in the bottom-right corner, sized for the right thumb.
  const LAYOUTS = {
    desk: { W: 1000, H: 490, CX: 500, CY: 476, A1: -166, A2: -14, hub: 146, rim: 446, font: [22, 15], scan: [150, 442],
      rings: [[154, 206, [["⇧", 1.2, "shift"], ["/", 1, "/"], ["SPACE", 4.4, " "], ["MIC", 1.3, "mic"], ["SEND", 1.7, "send"]]],
              [212, 264, ["z", "x", "c", "v", "b", "n", "m", ",", ".", ["DEL", 1.6, "back"]]],
              [270, 322, ["a", "s", "d", "f", "g", "h", "j", "k", "l", "?"]],
              [328, 380, ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"]],
              [386, 438, ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-"]]] },
    phone: { W: 1000, H: 1000, CX: 1000, CY: 1000, A1: -180, A2: -90, hub: 222, rim: 966, font: [42, 27], scan: [228, 960],
      rings: [[230, 368, [["⇧", 1, "shift"], ["SPACE", 2, " "], ["SEND", 1.5, "send"]]],
              [374, 512, ["z", "x", "c", "v", "b", "n", "m", ["DEL", 1.5, "back"]]],
              [518, 656, ["a", "s", "d", "f", "g", "h", "j", "k", "l"]],
              [662, 800, ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"]],
              [806, 944, ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "/", "?", ",", ".", "-"]]] },
  };
  let L = LAYOUTS.desk, mode = "";
  const phoneNow = () => Math.min(innerWidth, innerHeight) < 600 || (innerWidth < 760 && matchMedia("(pointer:coarse)").matches);
  const GAP = 4.5;
  const rad = d => d * Math.PI / 180, pt = (r, a) => [L.CX + r * Math.cos(rad(a)), L.CY + r * Math.sin(rad(a))];
  const f = n => n.toFixed(1);
  function sector(r0, r1, a0, a1){
    const gap = mode === "phone" ? 7 : GAP, g0 = gap / r0 * 90 / Math.PI, g1 = gap / r1 * 90 / Math.PI;   // half the gap, in degrees
    const [x1, y1] = pt(r1, a0 + g1), [x2, y2] = pt(r1, a1 - g1), [x3, y3] = pt(r0, a1 - g0), [x4, y4] = pt(r0, a0 + g0);
    const big = a1 - a0 > 180 ? 1 : 0;
    return `M${f(x1)} ${f(y1)}A${r1} ${r1} 0 ${big} 1 ${f(x2)} ${f(y2)}L${f(x3)} ${f(y3)}A${r0} ${r0} 0 ${big} 0 ${f(x4)} ${f(y4)}Z`;
  }
  const ID = Math.random().toString(36).slice(2, 10);                       // this browser tab, so it ignores its own keys
  let cast = false, listening = false, sendQ = Promise.resolve(), subT = 0;
  let el = null, shift = 0, lastShift = 0, on = false, repT = 0;            // shift: 0 off, 1 once, 2 caps lock
  const box = () => document.getElementById("t");
  function build(){
    mode = phoneNow() ? "phone" : "desk"; L = LAYOUTS[mode];
    const { W, H, CX, CY, A1, A2 } = L, HUB = L.hub, RIM = L.rim, ph = mode === "phone";
    let keys = "", ring = 0;
    for (const [r0, r1, list] of L.rings) {
      const items = list.map(k => Array.isArray(k) ? { label: k[0], w: k[1], act: k[2] } : { label: k, w: 1, act: k });
      const tot = items.reduce((s, k) => s + k.w, 0); let a = A1;
      items.forEach((k, i) => {
        const span = (A2 - A1) * k.w / tot, a0 = a, a1 = a + span, am = (a0 + a1) / 2, [tx, ty] = pt((r0 + r1) / 2, am); a = a1;
        const fn = k.label.length > 2 ? L.font[1] : L.font[0], cls = k.label.length > 1 && !/^[0-9]$/.test(k.label) ? " fn" : "";
        keys += `<g class="ak${cls}" data-act="${k.act}" style="--d:${ring * 70 + i * 18}ms"><path d="${sector(r0, r1, a0, a1)}"/>` +
                `<text x="${f(tx)}" y="${f(ty)}" font-size="${fn}" transform="rotate(${f(am + 90)} ${f(tx)} ${f(ty)})">${k.label}</text></g>`;
      });
      ring++;
    }
    const ticks = Array.from({ length: 61 }, (_, i) => { const a = A1 + (A2 - A1) * i / 60, len = (i % 5 ? 6 : 13) * (ph ? 1.6 : 1), [x1, y1] = pt(RIM, a), [x2, y2] = pt(RIM + len, a);
      return `<line x1="${f(x1)}" y1="${f(y1)}" x2="${f(x2)}" y2="${f(y2)}"/>`; }).join("");
    const [ha, hb] = [pt(HUB, A1), pt(HUB, A2)], [oa, ob] = [pt(RIM, A1), pt(RIM, A2)];
    const fan = r => `M${f(pt(r, A1)[0])} ${f(pt(r, A1)[1])}A${r} ${r} 0 0 1 ${f(pt(r, A2)[0])} ${f(pt(r, A2)[1])}L${CX} ${CY}Z`;
    const deskHub = `<text class="akname" x="${CX}" y="${CY - 92}">VERONICA</text><text class="aksub" x="${CX}" y="${CY - 70}">ARC INPUT</text>
      <text class="akprev" x="${CX}" y="${CY - 40}"></text>
      <g class="ak fn" data-act="cast"><circle cx="${CX - 46}" cy="${CY - 10}" r="17"/><text x="${CX - 46}" y="${CY - 10}">📺</text></g>
      <g class="ak fn" data-act="close"><circle cx="${CX + 46}" cy="${CY - 10}" r="17"/><text x="${CX + 46}" y="${CY - 10}">✕</text></g>`;
    const phoneHub = `<text class="akname" x="34" y="72">VERONICA</text><text class="aksub" x="36" y="112">ARC INPUT</text>
      <text class="akprev" x="34" y="176" text-anchor="start"></text>
      <g class="ak fn" data-act="mic"><circle cx="${CX - 112}" cy="${CY - 112}" r="64"/><text x="${CX - 112}" y="${CY - 112}">MIC</text></g>
      <g class="ak fn" data-act="close"><circle cx="80" cy="250" r="46"/><text x="80" y="250">✕</text></g>
      <g class="ak fn" data-act="cast"><circle cx="196" cy="250" r="46"/><text x="196" y="250">📺</text></g>`;
    if (el) el.remove();
    el = document.createElement("div"); el.id = "arcKb"; el.className = mode; el.hidden = !on; el.setAttribute("aria-label", "Arc keyboard");
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="group" aria-label="Arc keyboard">
      <defs><filter id="akGlow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <radialGradient id="akHub" gradientUnits="userSpaceOnUse" cx="${CX}" cy="${CY}" r="${HUB}"><stop offset="0" stop-color="var(--akc)" stop-opacity=".28"/><stop offset="1" stop-color="var(--akc)" stop-opacity="0"/></radialGradient></defs>
      <path class="akunder" d="${fan(RIM)}"/>
      <path class="akrim" d="M${f(oa[0])} ${f(oa[1])}A${RIM} ${RIM} 0 0 1 ${f(ob[0])} ${f(ob[1])}"/>
      <g class="akticks">${ticks}</g>
      <g class="akscan"><path d="${sector(L.scan[0], L.scan[1], A1, A1 + 9)}"/></g>
      <g class="akkeys" filter="url(#akGlow)">${keys}</g>
      <path class="akbase" d="${fan(HUB)}"/>
      <path class="akhub" d="${fan(HUB)}"/>
      ${ph ? phoneHub : deskHub}
    </svg>`;
    el.style.setProperty("--akox", CX + "px"); el.style.setProperty("--akoy", CY + "px"); el.style.setProperty("--aksweep", (A2 - A1 - 9) + "deg");
    document.body.appendChild(el);
    el.addEventListener("pointerdown", down);
    ["pointerup", "pointerleave", "pointercancel"].forEach(t => el.addEventListener(t, () => clearInterval(repT)));
    el.addEventListener("contextmenu", e => e.preventDefault());
  }
  function click(hi){                                                         // tiny glass tick, follows the "screen sounds" switch
    try { if (store.get("rb_holo_sfx") === "0") return; const ctx = (click.c ||= new (window.AudioContext || window.webkitAudioContext)());
      const o = ctx.createOscillator(), g = ctx.createGain(), t = ctx.currentTime; o.type = "triangle";
      o.frequency.setValueAtTime(hi ? 1760 : 1320, t); o.frequency.exponentialRampToValueAtTime(hi ? 2640 : 880, t + .05);
      g.gain.setValueAtTime(.06, t); g.gain.exponentialRampToValueAtTime(.0001, t + .08); o.connect(g); g.connect(ctx.destination); o.start(t); o.stop(t + .09); } catch {}
  }
  function flash(g){ if (!g) return; g.classList.remove("hit"); void g.getBoundingClientRect(); g.classList.add("hit"); }
  function insert(s){
    const t = box(); if (!t) return; const a = t.selectionStart ?? t.value.length, b = t.selectionEnd ?? a;
    t.setRangeText(s, a, b, "end"); t.dispatchEvent(new Event("input", { bubbles: true })); preview();
  }
  function back(){
    const t = box(); if (!t) return; let a = t.selectionStart ?? t.value.length, b = t.selectionEnd ?? a;
    if (a === b) { if (!a) return; a = a - 1; } t.setRangeText("", a, b, "end"); t.dispatchEvent(new Event("input", { bubbles: true })); preview();
  }
  function setShift(v){ shift = v; el.classList.toggle("up", shift > 0); el.classList.toggle("lock", shift === 2);
    el.querySelectorAll('.ak:not(.fn) text').forEach(x => { x.textContent = shift ? x.textContent.toUpperCase() : x.textContent.toLowerCase(); }); }
  function sub(text, ms){ const x = el && el.querySelector(".aksub"); if (!x) return; clearTimeout(subT);
    x.textContent = text; if (ms) subT = setTimeout(() => { x.textContent = cast ? "📺 TYPING ON SCREEN" : "ARC INPUT"; }, ms); }
  function post(k){                                                          // phone -> server -> the user's open screens, in order
    sendQ = sendQ.then(() => fetch("/api/remote/key", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify({ k, src: ID }) }).then(r => r.json()).then(j => { const n = (j.screens || 0) - (listening ? 1 : 0);
        if (n < 1) sub("NO SCREEN OPEN", 2500); }).catch(() => sub("NOT SENT - CHECK NETWORK", 2500)));
  }
  function act(a, g, remote){
    flash(g); click(a === "send");
    if (a === "close") return toggle(false);
    if (a === "cast") { cast = !cast; el.classList.toggle("casting", cast); sub(cast ? "📺 TYPING ON SCREEN" : "ARC INPUT");
      const t = box(); if (cast && t) { t.value = ""; t.dispatchEvent(new Event("input", { bubbles: true })); } preview(); return; }
    if (cast && !remote && a !== "shift") {                                   // remote mode: send to the big screen, mirror here
      const k = shift && a.length === 1 ? a.toUpperCase() : a; post(k);
      if (a === "send") { const t = box(); if (t) { t.value = ""; t.dispatchEvent(new Event("input", { bubbles: true })); } preview(); return; }
      if (a === "mic") return;
      if (a === "back") return back();
      insert(k); if (shift === 1) setShift(0); return;
    }
    if (a === "shift") { const now = Date.now(); setShift(shift ? (now - lastShift < 350 && shift === 1 ? 2 : 0) : 1); lastShift = now; return; }
    if (a === "back") return back();
    if (a === "send") { const fm = document.getElementById("f"); if (fm && box().value.trim()) fm.requestSubmit(); setTimeout(preview, 50); return; }
    if (a === "mic") { document.getElementById("mic")?.click(); return; }
    insert(!remote && shift && a.length === 1 ? a.toUpperCase() : a);
    if (!remote && shift === 1) setShift(0);
  }
  function remoteKey(k){                                                     // a key from this user's phone
    if (!on) toggle(true);
    const g = el.querySelector(`[data-act="${CSS.escape(k.length === 1 ? k.toLowerCase() : k)}"]`);
    sub("📱 PHONE LINKED", 4000); act(k, g, true);
  }
  // ONE listening connection per browser, never one per tab: browsers allow only ~6 open connections to a server,
  // so a stream in every VERONICA tab starved the page of connections and it froze. One tab holds the stream
  // (Web Locks), relays phone keys to the other tabs (BroadcastChannel), and only the tab on screen types them.
  const bc = "BroadcastChannel" in window ? new BroadcastChannel("veronica-remote") : null;
  const take = ev => { if (ev && ev.src !== ID && ev.k && document.visibilityState === "visible") remoteKey(ev.k); };
  if (bc) bc.onmessage = m => take(m.data);
  let ctrl = null;
  const wait = ms => new Promise(r => setTimeout(r, ms));
  async function stream(){                                                   // one connection; returns when it ends
    const dec = new TextDecoder(); ctrl = new AbortController();
    try {
      const r = await fetch("/api/remote/stream", { headers: { Authorization: "Bearer " + token }, signal: ctrl.signal });
      if (!r.ok || !r.body) { await wait(r.status === 401 ? 8000 : 4000); return; }
      listening = true; const rd = r.body.getReader(); let buf = "";
      for (;;) { const { value, done } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true });
        let i; while ((i = buf.indexOf("\n\n")) >= 0) { const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
          const line = chunk.split("\n").find(l => l.startsWith("data: ")); if (!line) continue;
          try { const ev = JSON.parse(line.slice(6)); take(ev); bc && bc.postMessage(ev); } catch {} } }
    } catch {} finally { listening = false; ctrl = null; }
  }
  async function listen(){
    if (navigator.locks) {                                                   // https / localhost: one stream for all tabs
      navigator.locks.request("veronica-remote-stream", async () => {
        for (;;) { if (!token) { await wait(3000); continue; } await stream(); await wait(3000); }
      });
      return;
    }
    // plain http on the LAN (no Web Locks): only the tab on screen keeps a stream; hidden tabs close theirs
    document.addEventListener("visibilitychange", () => { if (document.visibilityState !== "visible" && ctrl) ctrl.abort(); });
    for (;;) {
      if (!token || document.visibilityState !== "visible") { await wait(1500); continue; }
      await stream(); await wait(2000);
    }
  }
  function down(e){
    const g = e.target.closest("[data-act]"); if (!g) return;
    e.preventDefault();                                                       // keep the caret in the chat box, no native keyboard
    act(g.dataset.act, g);
    if (g.dataset.act === "back") { clearInterval(repT); const t0 = Date.now(); repT = setInterval(() => { if (Date.now() - t0 > 420) act("back", g); }, 70); }
  }
  function preview(){ if (!el) return; const v = (box()?.value || "").replace(/\s+/g, " "); el.querySelector(".akprev").textContent = v.length > 26 ? "…" + v.slice(-25) : v || "type or tap…";
    if (mode === "phone") el.querySelector(".akprev").textContent = v.length > 20 ? "…" + v.slice(-19) : v || "type or tap…"; }
  function place(){ if (!el || el.hidden) return; const lg = document.getElementById("login");
    el.style.visibility = lg && getComputedStyle(lg).display !== "none" ? "hidden" : "";   // never over the sign-in screen
    const fm = document.getElementById("f"), r = fm && fm.getBoundingClientRect();
    const shown = r && r.height > 0 && r.top > innerHeight * .35;            // chat box on screen -> sit just above it
    el.style.bottom = (shown ? Math.max(6, innerHeight - r.top + 6) : 14) + "px";
    if (phoneNow() !== (mode === "phone")) { const keep = on; build(); el.hidden = !keep; el.classList.add("boot"); setShift(shift); preview(); } }
  function toggle(want){
    on = want ?? !on; if (!el) build(); store.set("rb_arckey", on ? "1" : "0");
    const t = box(); if (t) { if (on) t.setAttribute("inputmode", "none"); else t.removeAttribute("inputmode"); }
    el.hidden = !on; document.getElementById("kbdBtn")?.classList.toggle("on", on);
    if (on) { el.classList.remove("boot"); void el.offsetWidth; el.classList.add("boot"); place(); preview(); setShift(0); }
  }
  const KEYMAP = { " ": " ", Backspace: "back", Enter: "send", Shift: "shift", "/": "/" };
  addEventListener("keydown", e => {                                          // a real keyboard lights the arc too
    if (!on || !el || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = KEYMAP[e.key] ?? (e.key.length === 1 ? e.key.toLowerCase() : null); if (!k) return;
    const g = el.querySelector(`[data-act="${CSS.escape(k)}"]`); if (g) { flash(g); click(k === "send"); }
    if (document.activeElement !== box()) return;
    setTimeout(preview, 0);
  });
  addEventListener("resize", place);
  setInterval(() => { if (on) place(); }, 1500);
  const btn = () => document.getElementById("kbdBtn");
  const init = () => { btn()?.addEventListener("click", () => toggle()); box()?.addEventListener("input", preview);
    if (store.get("rb_arckey") === "1") toggle(true); listen(); };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", init); else init();
  return { toggle, get on(){ return on; } };
})();
