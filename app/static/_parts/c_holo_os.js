/* ================================================================ HOLO OS - JARVIS-style workspace (Holo + Nova themes)
   Screens open one after another around the core. Before each one opens, a light packet travels from the core
   (or from the screen opened just before it) to the new screen with a rising sweep, and the screen unfolds on a
   note of the theme's scale - so a full answer plays a short melody as it builds.
     you ask  -> QUERY + PROCESS + DATA LINK (+ LIVE FIGURES while numbers are read)
     answer   -> KPI tiles, CHART, COMPARE (vs previous), MIX (share of total), TABLE, INSIGHT, FILES, RESPONSE TIME
     upload   -> FILE SCAN (rows, columns, totals, a sparkline of the first numeric column)
     theme on -> boot: SYSTEM status + a greeting (no report data is ever pushed)
   Screens stay flat at rest (sharp text), tilt only while unfolding, keep clear of the floating chat window,
   come forward on hover, click a title to focus, × to close. Gauges along the bottom show real numbers. */
const HoloOS = (() => {
  const ws = $("#hws"), box = $("#hPanels"), links = $("#hLinks"), gauges = $("#hGauges");
  if (!ws) return { ask(){}, step(){}, figure(){}, reply(){}, scan(){}, boot(){}, idle(){}, closeAll(){}, spawn(){}, cycle(){} };
  const on = () => document.body.classList.contains("theme-holo") && !REDUCE;
  const NS = "http://www.w3.org/2000/svg";
  const pk = document.createElementNS(NS, "svg"); pk.setAttribute("class", "hpk"); ws.appendChild(pk);
  let panels = [], seq = 0, nQ = 0, lastSec = 0, steps = new Map(), figs = [], run = 0, lastOpened = null, chain = 0;
  const wait = ms => new Promise(r => setTimeout(r, ms));

  /* ---------------- geometry: 10 slots around the core, kept clear of the floating chat window */
  function area(){
    const r = ws.getBoundingClientRect(); let right = r.width;
    const dock = $("#dock");
    if (dock && !dock.hidden && document.body.classList.contains("view-dock")) {
      const d = dock.getBoundingClientRect();
      if (d.left > r.left + r.width * .45 && d.top < r.bottom) right = Math.min(right, d.left - r.left - 14);
    }
    return { W: r.width, H: r.height, right };
  }
  function slotBox(slot){
    const { W, H, right } = area(), cw = Math.max(230, Math.min(320, right * .21)), g = 12;
    const L = g, R = right - cw - g, iL = L + cw + 14, iR = R - cw - 14, rows = [10, H * .34, H * .64];
    const sw = Math.max(260, Math.min(440, right * .3));
    return [
      [L, rows[0], cw, "l"], [L, rows[1], cw, "l"], [L, rows[2], cw, "l"],
      [R, rows[0], cw, "r"], [R, rows[1], cw, "r"], [R, rows[2], cw, "r"],
      [(right - sw) / 2, 8, sw, "t"], [iL, H * .69, cw, "b"], [iR, H * .69, cw, "b"], [(right - sw) / 2, H * .72, sw, "b"],
    ][slot];
  }
  const colOf = slot => slot <= 2 ? "L" : slot <= 5 ? "R" : "S" + slot;
  function place(p){ relayout(); }
  function relayout(){
    const { H } = area(), bottom = {};
    for (const p of panels.filter(q => !q.closing).sort((a, b) => a.slot - b.slot)) {
      const [x, y0, w, side] = slotBox(p.slot), col = colOf(p.slot), hb = p.el.querySelector(".hb2");
      p.side = side; p.el.classList.remove("side-l", "side-r", "side-t", "side-b"); p.el.classList.add("side-" + side);
      p.el.classList.toggle("slim", p.slot >= 7);
      p.el.style.width = Math.round(p.wide ? w * 1.25 : w) + "px"; p.el.style.left = Math.round(x) + "px";
      p.el.classList.toggle("narrow", w < 280);
      let y = y0;
      if (col === "L" || col === "R") y = bottom[col] != null ? bottom[col] + 10 : 10;     // stack down the side
      const limit = p.slot >= 7 ? H * .3 : p.slot === 6 ? H * .3 : H - 14 - y - 36;
      if (hb) hb.style.maxHeight = Math.max(64, Math.min(p.el.classList.contains("focus") ? 9999 : limit, H * .42)) + "px";
      const h = p.el.offsetHeight;
      if (p.slot === 7 || p.slot === 8 || p.slot === 9) y = H - 84 - h;                    // sit just above the gauges
      p.el.style.top = Math.round(Math.max(6, y)) + "px";
      if (col === "L" || col === "R") bottom[col] = Math.max(6, y) + h;
    }
    // keep a clear gap: any screen that would touch an earlier one moves below it (or shrinks to fit)
    const GAP = 14, placed = [];
    for (const p of panels.filter(q => !q.closing && !q.el.classList.contains("focus")).sort((a, b) => a.slot - b.slot)) {
      let x = p.el.offsetLeft, y = p.el.offsetTop, w = p.el.offsetWidth, h = p.el.offsetHeight;
      for (let guard = 0; guard < 8; guard++) {
        const hit = placed.find(r => x < r.x + r.w + GAP && x + w + GAP > r.x && y < r.y + r.h + GAP && y + h + GAP > r.y);
        if (!hit) break;
        y = hit.y + hit.h + GAP;
      }
      const floor = p.slot >= 7 ? H - 84 : H - 8;                   // bottom screens stay above the gauges
      if (y + h > floor) {                                         // not enough room: shrink its body
        const hb = p.el.querySelector(".hb2"), need = y + h - floor;
        if (hb) { hb.style.maxHeight = Math.max(56, hb.offsetHeight - need) + "px"; h = p.el.offsetHeight; }
        if (y + h > floor) y = Math.max(6, floor - h);
      }
      p.el.style.top = Math.round(y) + "px";
      placed.push({ x, y, w, h });
    }
  }
  const used = () => new Set(panels.filter(p => !p.closing).map(p => p.slot));
  function freeSlot(pref){ const u = used(); for (const s of pref || [0, 3, 1, 4, 2, 5, 7, 8, 6, 9]) if (!u.has(s)) return s; return -1; }
  function core(){ const r = ws.getBoundingClientRect(); return [r.width / 2, r.height * .4]; }
  function anchor(p){
    const r = ws.getBoundingClientRect(), b = p.el.getBoundingClientRect();
    return [(p.side === "l" ? b.right : p.side === "r" ? b.left : b.left + b.width / 2) - r.left,
            (p.side === "t" ? b.bottom : p.side === "b" ? b.top : b.top + b.height / 2) - r.top];
  }
  const curve = ([ax, ay], [bx, by]) => { const mx = (ax + bx) / 2; return [[ax, ay], [mx, ay], [mx, by], [bx, by]]; };
  const bez = (c, t) => { const u = 1 - t; return [0, 1].map(k => u * u * u * c[0][k] + 3 * u * u * t * c[1][k] + 3 * u * t * t * c[2][k] + t * t * t * c[3][k]); };
  function drawLinks(){
    const r = ws.getBoundingClientRect(); links.setAttribute("viewBox", `0 0 ${r.width} ${r.height}`); pk.setAttribute("viewBox", `0 0 ${r.width} ${r.height}`);
    const c0 = core();
    links.innerHTML = panels.filter(p => !p.closing && p.shown).map(p => {
      const c = curve(c0, anchor(p));
      return `<path class="ln ${p.tone || ""}" d="M${c[0]} C${c[1]} ${c[2]} ${c[3]}"/><circle class="nd ${p.tone || ""}" r="2.6" cx="${c[3][0]}" cy="${c[3][1]}"/>`;
    }).join("");
  }
  setInterval(() => { if (on() && panels.length) drawLinks(); }, 150);
  addEventListener("resize", () => { relayout(); drawLinks(); });

  /* ---------------- the light packet: core or previous screen -> next screen */
  function travel(from, to, ms = 340){
    return new Promise(res => {
      if (REDUCE) return res();
      const c = curve(from, to), t0 = performance.now();
      const dot = document.createElementNS(NS, "circle"), tr = document.createElementNS(NS, "path");
      dot.setAttribute("class", "pk"); dot.setAttribute("r", "3.4"); tr.setAttribute("class", "tr"); pk.append(tr, dot);
      const frame = now => {
        const k = Math.min(1, (now - t0) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        const [x, y] = bez(c, e); dot.setAttribute("cx", x); dot.setAttribute("cy", y);
        const pts = []; for (let i = 0; i <= 8; i++) pts.push(bez(c, Math.max(0, e - .16 + i * .02)));
        tr.setAttribute("d", "M" + pts.map(p => p.join(",")).join(" L")); tr.style.opacity = String(1 - k * .6);
        if (k < 1) requestAnimationFrame(frame); else { dot.remove(); tr.remove(); res(); }
      };
      requestAnimationFrame(frame);
    });
  }

  /* ---------------- open / close screens */
  async function open(kind, title, html, o = {}){
    if (!on()) return null;
    const myRun = run;
    let slot = o.slot != null && !used().has(o.slot) ? o.slot : freeSlot(o.pref);
    if (slot < 0) { const old = panels.find(p => !p.closing && !p.keep); if (old) { close(old); slot = old.slot; } else return null; }
    const el = document.createElement("section");
    el.className = `hp ${kind} ${o.tone || ""}`;
    el.innerHTML = `<header><i></i><b>${esc(title)}</b><span class="id">${String(++seq).padStart(3, "0")}</span><button class="x" type="button" aria-label="Close">×</button></header><div class="hb2">${html}</div><span class="scan"></span>`;
    el.style.visibility = "hidden";
    const p = { el, kind, slot, tone: o.tone, keep: o.keep, wide: o.wide, shown: false };
    panels.push(p); box.appendChild(el); place(p);
    el.addEventListener("click", e => e.stopPropagation());          // clicks on screens never trigger "tap to talk"
    el.querySelector(".x").onclick = e => { e.stopPropagation(); close(p); };
    el.querySelector("header").onclick = () => { const f = el.classList.toggle("focus"); ws.classList.toggle("focusing", f); panels.forEach(q => q !== p && q.el.classList.remove("focus")); };
    const src = o.fromCore || !lastOpened || lastOpened.closing || !lastOpened.shown ? core() : anchor(lastOpened);
    const n = chain++;
    HoloAudio.transfer(n);
    await travel(src, anchor(p), o.fast ? 220 : 340);
    if (myRun !== run || p.closing) { el.remove(); panels = panels.filter(q => q !== p); return null; }
    relayout();
    if (o.extra && overlaps(p)) { el.remove(); panels = panels.filter(q => q !== p); relayout(); return null; }   // no room: skip extras
    el.style.visibility = ""; el.classList.add("arrive"); setTimeout(() => el.classList.remove("arrive"), 600);
    p.shown = true; lastOpened = p;
    HoloAudio.open(n, p.tone === "red");
    drawLinks();
    return p;
  }
  function overlaps(p){
    const a = p.el.getBoundingClientRect();
    return panels.some(q => q !== p && q.shown && !q.closing && (b => a.left < b.right + 8 && a.right + 8 > b.left && a.top < b.bottom + 8 && a.bottom + 8 > b.top)(q.el.getBoundingClientRect()));
  }
  function close(p){ if (!p || p.closing) return; p.closing = true; p.el.classList.add("out"); ws.classList.remove("focusing");
    setTimeout(() => { p.el.remove(); panels = panels.filter(q => q !== p); relayout(); drawLinks(); }, 400); }
  function closeAll(filter){ panels.filter(p => !filter || filter(p)).forEach(close); }
  const typeInto = (el, text, cps = 90) => new Promise(res => {
    if (!el) return res(); let i = 0; const s = String(text); el.textContent = "";
    const iv = setInterval(() => { i = Math.min(s.length, i + Math.max(1, Math.ceil(s.length / 60))); el.textContent = s.slice(0, i); HoloAudio.key(); if (i >= s.length) { clearInterval(iv); res(); } }, 1000 / cps * 2); });
  const num = v => typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : esc(v ?? "");
  const fmtV = k => k.format === "percent" ? (Math.round(k.value * 100) / 100).toLocaleString("en-IN") + "%" : (Math.round(k.value * 100) / 100).toLocaleString("en-IN");
  const INTENT = [[/scrap/i, "SCRAP"], [/reject/i, "REJECTION"], [/final|production|prod\b/i, "PRODUCTION"], [/sale|order|booking/i, "SALES ORDERS"],
    [/pending|overdue|late|delay/i, "DELIVERY"], [/grn|purchase|po\b/i, "PURCHASE"], [/ledger|account|voucher/i, "ACCOUNTS"], [/dashboard/i, "DASHBOARD"],
    [/excel|pdf/i, "EXPORT"], [/attached|file|sheet/i, "FILE"], [/\b(oct|nov|dec|jan|feb|mar|apr|may|jun|jul|aug|sep)\w*|month|mahine|today|aaj|kal|week/i, "PERIOD"]];

  /* ---------------- bottom gauges (real numbers) */
  function ring(v, label, val){ const c = 2 * Math.PI * 17, f = Math.max(0, Math.min(1, v));
    return `<div class="hg"><svg viewBox="0 0 44 44"><circle cx="22" cy="22" r="17" class="bgc"/><circle cx="22" cy="22" r="17" class="fgc" stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}"/></svg><b>${esc(val)}</b><span>${esc(label)}</span></div>`; }
  const syncMin = () => ME && ME.data_synced_at ? (Date.now() - new Date(String(ME.data_synced_at).replace(" ", "T"))) / 60000 : NaN;
  const ago = m => isNaN(m) ? "—" : m < 60 ? Math.round(m) + "m" : m < 2880 ? Math.round(m / 60) + "h" : Math.round(m / 1440) + "d";
  function gaugesDraw(){
    if (!on()) return;
    const sync = syncMin(), now = new Date();
    gauges.innerHTML = ring(isNaN(sync) ? 0 : 1 - Math.min(1, sync / 1440), "ERP SYNC", ago(sync))
      + ring(lastSec ? 1 - Math.min(1, lastSec / 30) : 0, "RESPONSE", lastSec ? lastSec + "s" : "—")
      + ring(Math.min(1, nQ / 20), "QUERIES", String(nQ))
      + ring(Math.min(1, VLVL), "VOICE", VLVL > .05 ? Math.round(VLVL * 100) + "%" : "idle")
      + ring((now.getHours() * 60 + now.getMinutes()) / 1440, "LOCAL TIME", now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }));
  }
  setInterval(gaugesDraw, 1000);
  gauges.addEventListener("click", e => e.stopPropagation());

  /* ---------------- boot + idle screens: status, greeting, clock, month, quick reports, session pulse
     They stay while nothing is running (switch off under ♪ › Idle screens) and come back after 3 min of quiet. */
  const IDLE = ["sys", "greet", "clock", "month", "pulse"];
  const nova = () => ["theme-nova", "theme-forge", "theme-titan"].some(k => document.body.classList.contains(k));
  const idleOn = () => nova() && store.get("rb_idle_screens") !== "0";        // Holo keeps its original start (status + greeting)
  let booted = false, bootT = 0, lastAct = Date.now(), answers = 0, secSum = 0, filesMade = 0;
  const isBoss = () => !!ME && !!ME.boss;
  function clockHtml(){
    const now = new Date(), f = (tz, o = {}) => now.toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", ...o });
    return `<div class="clk">${f("Asia/Kolkata")}<small>:${String(now.getSeconds()).padStart(2, "0")}</small></div>
      <div class="dt">${now.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" }).toUpperCase()} · IST</div>
      <div class="zones"><div>DUBAI<b>${f("Asia/Dubai")}</b></div><div>LONDON<b>${f("Europe/London")}</b></div><div>NEW YORK<b>${f("America/New_York")}</b></div></div>`; }
  function monthHtml(){
    const n = new Date(), days = new Date(n.getFullYear(), n.getMonth() + 1, 0).getDate(), d = n.getDate(), C = 2 * Math.PI * 30;
    let left = 0; for (let k = d + 1; k <= days; k++) if (new Date(n.getFullYear(), n.getMonth(), k).getDay() !== 0) left++;
    return `<div class="mon"><svg viewBox="0 0 78 78"><circle cx="39" cy="39" r="30" class="bgc" fill="none"/><circle cx="39" cy="39" r="30" class="fgc" stroke-dasharray="${(C * d / days).toFixed(1)} ${C.toFixed(1)}"/></svg>
      <div><div class="big2">${Math.round(d / days * 100)}%</div><p>DAY ${d} OF ${days} · ${n.toLocaleString("en-IN", { month: "long" }).toUpperCase()}</p><p>${left} WORKING DAYS LEFT</p><p>MTD FIGURES = 1–${d} ${n.toLocaleString("en-IN", { month: "short" }).toUpperCase()}</p></div></div>`; }
  const capsHtml = () => [["🛡", "High Strength"], ["⚙", "Precision Engineering"], ["✓", "Safety & Reliability"], ["🌐", "Global Reach"]]
    .map(([i, l]) => `<div class="kv"><span>${i}&nbsp; ${l.toUpperCase()}</span><b class="ok">●</b></div>`).join("");
  const jetsHtml = () => `<canvas class="jetcv" style="display:block;width:100%;height:170px" aria-label="Fighter jet hologram"></canvas>`;
  const pulseHtml = () => `<div class="pulse2"><div><span>QUESTIONS</span><b>${nQ}</b></div><div><span>LAST ANSWER</span><b>${lastSec ? lastSec + "s" : "—"}</b></div>
      <div><span>AVG ANSWER</span><b>${answers ? (secSum / answers).toFixed(1) + "s" : "—"}</b></div><div><span>FILES MADE</span><b>${filesMade}</b></div></div>
      <div class="bars2">${Array.from({ length: 24 }, (_, i) => `<i style="animation-delay:${(i * 97 % 1100)}ms;height:${30 + (i * 37 % 70)}%"></i>`).join("")}</div>`;
  setInterval(() => { panels.forEach(p => { if (p.shown && p.kind.startsWith("clock")) p.el.querySelector(".hb2").innerHTML = clockHtml(); }); }, 1000);
  async function idleScreens(first){
    if (!on() || !ME || document.body.classList.contains("busy")) return;
    const myRun = ++run; chain = 0; lastOpened = null;
    if (first) HoloAudio.boot();
    const h = new Date().getHours(), part = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
    const first_ = String(ME.name || "").split(" ")[0];
    const msg = isBoss() ? "Hello Boss. How are you? Is everything good? How can I help you today?" : `${part}${first_ ? ", " + first_ : ""}. All systems online – what shall we look at?`;
    const ch = ME.channels || {}, yes = b => b ? `<b class="ok">ONLINE</b>` : `<b class="off">NOT SET</b>`;
    await wait(first ? 500 : 150); if (myRun !== run) return;
    const g = await open("greet", "VERONICA // ONLINE", `<div class="greet"><span class="gt"></span><small>ASK · SPEAK · OR DROP A FILE</small></div>`, { slot: 6, fromCore: true });
    if (g) typeInto(g.el.querySelector(".gt"), msg, 110);
    if (!idleOn()) {                                      // Holo (or idle screens off): status + greeting, gone after 12 s
      if (!nova() && myRun === run) await open("sys", "SYSTEM // STATUS", `<div class="kv"><span>USER</span><b>${esc(ME.name || "")}</b></div>
        <div class="kv"><span>CLEARANCE</span><b>${esc(String(ME.role || "").toUpperCase())}</b></div>
        <div class="kv"><span>ERP REPLICA</span><b class="${syncMin() < 1440 ? "ok" : ""}">${isNaN(syncMin()) ? "READ-ONLY" : "SYNCED " + esc(ago(syncMin())) + " AGO"}</b></div>
        <div class="kv"><span>REPORTS ARMED</span><b>${(ME.skills || []).length}</b></div>
        <div class="kv"><span>WEB</span><b class="ok">ONLINE</b></div>
        <div class="kv"><span>WHATSAPP</span>${yes(ch.whatsapp)}</div><div class="kv"><span>E-MAIL</span>${yes(ch.mail)}</div>`, { slot: 0 });
      clearTimeout(bootT); bootT = setTimeout(() => { if (myRun === run) closeAll(p => IDLE.includes(p.kind)); }, 12000); return; }
    const seqs = [
      ["sys", "SYSTEM // STATUS", () => `<div class="kv"><span>USER</span><b>${esc(ME.name || "")}</b></div>
        <div class="kv"><span>CLEARANCE</span><b>${esc(String(ME.role || "").toUpperCase())}</b></div>
        <div class="kv"><span>ERP REPLICA</span><b class="${syncMin() < 1440 ? "ok" : ""}">${isNaN(syncMin()) ? "READ-ONLY" : "SYNCED " + esc(ago(syncMin())) + " AGO"}</b></div>
        <div class="kv"><span>WEB</span><b class="ok">ONLINE</b></div>
        <div class="kv"><span>WHATSAPP</span>${yes(ch.whatsapp)}</div><div class="kv"><span>E-MAIL</span>${yes(ch.mail)}</div>`, 0],
      ["clock", "TIME // IST", clockHtml, 3],
      ["month", "MONTH // PROGRESS", monthHtml, 1],
      ["pulse", "SESSION // PULSE", pulseHtml, 2],
    ];
    if (document.body.classList.contains("theme-titan")) seqs.push(["jets", "AIR // SQUADRON", jetsHtml, 4]);
    if (document.body.classList.contains("theme-atlas") && typeof Atlas !== "undefined") {      // Atlas: fewer screens, room for the hologram
      for (let i = seqs.length - 1; i >= 0; i--) if (!["sys", "clock"].includes(seqs[i][0])) seqs.splice(i, 1);
      seqs.push(["asm", "ASSEMBLY // EXPLODED VIEW", Atlas.panelHtml, 2]);
    }
    for (const [kind, title, html, slot] of seqs) { if (myRun !== run) return; await open(kind, title, html(), { slot }); }
  }
  async function boot(){
    if (booted) return; booted = true;
    for (let i = 0; i < 40 && !ME; i++) await wait(250);                  // wait for sign-in
    if (!on() || !ME || panels.length) return;
    idleScreens(true);
  }
  setInterval(() => {                                                       // quiet for 3 min -> answer screens fold, idle screens return
    if (!on() || !ME || !idleOn() || document.body.classList.contains("busy") || Date.now() - lastAct < 180000) return;
    if (panels.some(p => !p.closing && IDLE.includes(p.kind) && p.kind !== "greet")) return;
    lastAct = Date.now(); closeAll(); setTimeout(() => idleScreens(false), 450);
  }, 10000);
  /* admin hand gesture ✌ : add one more hologram screen (cycles through these, several can be open at once) */
  let spawnI = 0;
  function spawn(){
    if (!on() || !ME) return null;
    const ch = ME.channels || {}, yes = b => b ? `<b class="ok">ONLINE</b>` : `<b class="off">NOT SET</b>`;
    const kinds = [
      ["clock", "TIME // IST", clockHtml],
      ["month", "MONTH // PROGRESS", monthHtml],
      ["pulse", "SESSION // PULSE", pulseHtml],
      ["sys", "SYSTEM // STATUS", () => `<div class="kv"><span>USER</span><b>${esc(ME.name || "")}</b></div>
        <div class="kv"><span>CLEARANCE</span><b>${esc(String(ME.role || "").toUpperCase())}</b></div>
        <div class="kv"><span>ERP REPLICA</span><b class="${syncMin() < 1440 ? "ok" : ""}">${isNaN(syncMin()) ? "READ-ONLY" : "SYNCED " + esc(ago(syncMin())) + " AGO"}</b></div>
        <div class="kv"><span>WHATSAPP</span>${yes(ch.whatsapp)}</div><div class="kv"><span>E-MAIL</span>${yes(ch.mail)}</div>`],
    ];
    if (document.body.classList.contains("theme-titan")) kinds.unshift(["jets", "AIR // SQUADRON", jetsHtml]);
    if (document.body.classList.contains("theme-atlas") && typeof Atlas !== "undefined") kinds.unshift(["asm", "ASSEMBLY // EXPLODED VIEW", Atlas.panelHtml]);
    const [kind, title, html] = kinds[spawnI++ % kinds.length];
    lastAct = Date.now(); clearTimeout(bootT);
    return (async () => {
      let q = await open(kind + " hand", title, html(), { extra: true });
      if (!q) {                                              // no clear space: fold the oldest screen and use its place
        const old = panels.find(x => !x.closing && x.shown && x.kind !== "greet") || panels.find(x => !x.closing && x.shown);
        if (!old) return null;
        close(old); await wait(450);
        q = await open(kind + " hand", title, html(), { extra: true, slot: old.slot });
      }
      return q;
    })();
  }
  /* admin hand wave: swap the whole set of hologram screens (page 1 ↔ 2 ↔ 3) */
  let pageI = 0, cycling = false;
  const calHtml = () => { const n = new Date(), y = n.getFullYear(), m = n.getMonth(), first = (new Date(y, m, 1).getDay() + 6) % 7, days = new Date(y, m + 1, 0).getDate();
    let h = `<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:3px;text-align:center;font:600 10px var(--mono,monospace)">` + "MTWTFSS".split("").map(c => `<span style="opacity:.55">${c}</span>`).join("");
    for (let i = 0; i < first; i++) h += "<span></span>";
    for (let d = 1; d <= days; d++) { const sun = new Date(y, m, d).getDay() === 0, today = d === n.getDate();
      h += `<span style="padding:3px 0;border-radius:4px;${today ? "background:rgba(var(--hc,120,230,255),.35);color:#fff;box-shadow:0 0 8px rgba(var(--hc,120,230,255),.6)" : sun ? "opacity:.4" : ""}">${d}</span>`; }
    return h + `</div><p style="margin:6px 0 0;opacity:.7;font-size:10px;letter-spacing:.1em">${n.toLocaleString("en-IN", { month: "long", year: "numeric" }).toUpperCase()} · SUNDAYS OFF</p>`; };
  const reportsHtml = () => { const s = (ME && ME.skills) || []; return s.length ? s.slice(0, 7).map((k, i) => `<div class="kv"><span>${String(i + 1).padStart(2, "0")} ${esc(k.title)}</span><b class="ok">ARMED</b></div>`).join("")
      + (s.length > 7 ? `<div class="kv"><span>+ ${s.length - 7} MORE</span><b></b></div>` : "") : `<div class="kv"><span>NO REPORTS YET</span><b></b></div>`; };
  const linksHtml = () => { const ch = (ME && ME.channels) || {}, bar = (on, w) => `<i style="display:block;height:4px;margin:3px 0 7px;border-radius:2px;width:${on ? w : 12}%;background:${on ? "rgba(var(--hg,120,255,200),.85)" : "rgba(255,90,110,.6)"};box-shadow:0 0 6px currentColor"></i>`;
    return [["ERP REPLICA", true, 96], ["WEB CONSOLE", true, 100], ["WHATSAPP", ch.whatsapp, 82], ["E-MAIL", ch.mail, 74]].map(([n, on, w]) => `<div class="kv"><span>${n}</span><b class="${on ? "ok" : "off"}">${on ? "LINKED" : "OFFLINE"}</b></div>${bar(on, w)}`).join(""); };
  const sysHtml2 = () => { const ch = (ME && ME.channels) || {}, yes = b => b ? `<b class="ok">ONLINE</b>` : `<b class="off">NOT SET</b>`;
    return `<div class="kv"><span>USER</span><b>${esc(ME.name || "")}</b></div><div class="kv"><span>CLEARANCE</span><b>${esc(String(ME.role || "").toUpperCase())}</b></div>
      <div class="kv"><span>ERP REPLICA</span><b class="${syncMin() < 1440 ? "ok" : ""}">${isNaN(syncMin()) ? "READ-ONLY" : "SYNCED " + esc(ago(syncMin())) + " AGO"}</b></div>
      <div class="kv"><span>WHATSAPP</span>${yes(ch.whatsapp)}</div><div class="kv"><span>E-MAIL</span>${yes(ch.mail)}</div>`; };
  const PAGES = [
    [["sys", "SYSTEM // STATUS", sysHtml2, 0], ["clock", "TIME // IST", clockHtml, 3], ["month", "MONTH // PROGRESS", monthHtml, 1], ["pulse", "SESSION // PULSE", pulseHtml, 2]],
    [["reports", "REPORTS // ARMED", reportsHtml, 0], ["cal", "CALENDAR // " + new Date().toLocaleString("en-IN", { month: "short" }).toUpperCase(), calHtml, 3], ["links", "NETWORK // LINKS", linksHtml, 1], ["clock", "TIME // IST", clockHtml, 2]],
    [["pulse", "SESSION // PULSE", pulseHtml, 0], ["month", "MONTH // PROGRESS", monthHtml, 3], ["links", "NETWORK // LINKS", linksHtml, 1], ["reports", "REPORTS // ARMED", reportsHtml, 2]],
  ];
  const TITAN_PAGE = [["jets", "AIR // SQUADRON", jetsHtml, 0], ["cal", "CALENDAR // " + new Date().toLocaleString("en-IN", { month: "short" }).toUpperCase(), calHtml, 3], ["links", "NETWORK // LINKS", linksHtml, 1], ["pulse", "SESSION // PULSE", pulseHtml, 2]];
  async function cycle(dir = 1){
    if (!on() || !ME || cycling) return;
    cycling = true;
    try {
      const ATLAS_PAGE = [["asm", "ASSEMBLY // EXPLODED VIEW", () => Atlas.panelHtml(), 0], ["caps", "CAPABILITIES", capsHtml, 3], ["jets", "AIR // SQUADRON", jetsHtml, 1], ["links", "NETWORK // LINKS", linksHtml, 2]];
      const pages = document.body.classList.contains("theme-atlas") && typeof Atlas !== "undefined" ? [ATLAS_PAGE, ...PAGES, TITAN_PAGE]
        : document.body.classList.contains("theme-titan") ? [...PAGES, TITAN_PAGE] : PAGES;
      pageI = (pageI + (dir < 0 ? -1 : 1) + pages.length) % pages.length;
      HoloAudio.whoosh(); lastAct = Date.now(); clearTimeout(bootT);
      const myRun = ++run; chain = 0; lastOpened = null;
      closeAll(p => p.kind !== "greet"); await wait(430);
      for (const [kind, title, html, slot] of pages[pageI]) { if (myRun !== run) break; await open(kind + " hand", title, html(), { slot, fast: true, extra: true }); }
    } finally { cycling = false; }
  }
  function idle(onNow){
    if (onNow) { if (!document.body.classList.contains("busy") && !panels.some(p => !p.closing && !IDLE.includes(p.kind))) { closeAll(); setTimeout(() => idleScreens(false), 450); } }
    else closeAll(p => IDLE.includes(p.kind));
  }

  /* ---------------- the question */
  let proc = null, link = null, live = null;
  async function ask(text){
    if (!on()) return; nQ++; lastAct = Date.now(); steps = new Map(); figs = []; const myRun = ++run; chain = 0; lastOpened = null; clearTimeout(bootT);
    closeAll(); proc = link = live = null; tStart = performance.now();
    await wait(240); if (myRun !== run) return;
    const tags = INTENT.filter(([re]) => re.test(text)).map(([, t]) => t);
    const q = await open("q", "QUERY // INPUT", `<div class="qt"></div><div class="tags">${(tags.length ? tags : ["GENERAL"]).map(t => `<em>${t}</em>`).join("")}</div>
      <div class="kv"><span>CHANNEL</span><b>WEB · ${esc(($("#lang").value || "en-IN").toUpperCase())}</b></div>`, { slot: 6, fromCore: true, fast: true });
    if (q) typeInto(q.el.querySelector(".qt"), "“" + text + "”", 120);
    if (myRun !== run || !document.body.classList.contains("busy")) return;
    proc = await open("proc", "PROCESS // ENGINE", `<div class="ring"><svg viewBox="0 0 60 60"><circle cx="30" cy="30" r="24" class="bgc"/><circle cx="30" cy="30" r="24" class="spin"/></svg><b>0</b></div><ol class="steps"></ol>`, { slot: 0, fast: true });
    for (const ev of pendingSteps.splice(0)) step(ev);
    if (myRun !== run || !document.body.classList.contains("busy")) return;
    link = await open("link", "DATA LINK // ERP REPLICA", `<div class="kv"><span>MODE</span><b>READ-ONLY · ROLE CHECKED</b></div><pre class="code"></pre>`, { slot: 3, fast: true });
    codeStream();
  }
  let codeIv = 0, tStart = 0; const pendingSteps = [];
  function codeStream(){
    clearInterval(codeIv);
    const L = ["> handshake replica ......... OK", "> role guard ................ OK", "> resolve view & columns", "> SELECT … WHERE date BETWEEN …", "> aggregate · verify totals", "> build KPI set", "> render dashboard"];
    let i = 0; codeIv = setInterval(() => { const pre = link && link.el.querySelector(".code"); if (!pre || !document.body.classList.contains("busy")) { clearInterval(codeIv); return; }
      pre.textContent = (pre.textContent + "\n" + L[i % L.length] + (i >= L.length ? " ·" + (Math.random() * 999 | 0) : "")).split("\n").slice(-9).join("\n"); i++; }, 420);
  }
  const timeline = [];
  function step(ev){
    if (!on()) return;
    if (ev.status === "done" || ev.status === "error") { const t = timeline.find(x => x.id === ev.id); if (t) t.ms = ev.ms || 0; else timeline.push({ id: ev.id, label: ev.label || ev.name || "step", ms: ev.ms || 0 }); }
    else if (ev.label && !timeline.find(x => x.id === ev.id)) timeline.push({ id: ev.id, label: ev.label, ms: null });
    if (!proc) { pendingSteps.push(ev); return; }
    const ol = proc.el.querySelector(".steps"); let li = steps.get(ev.id);
    if (!li) { li = document.createElement("li"); ol.appendChild(li); steps.set(ev.id, li); li.innerHTML = "<span></span><em>…</em>"; }
    if (ev.label) li.querySelector("span").textContent = ev.label;
    if (ev.status === "done" || ev.status === "error") { li.className = ev.status; li.querySelector("em").textContent = ((ev.ms || 0) / 1000).toFixed(1) + "s"; }
    proc.el.querySelector(".ring b").textContent = [...steps.values()].filter(x => x.className === "done").length;
    if (ev.detail && link) { const pre = link.el.querySelector(".code"); pre.textContent = (pre.textContent + "\n> " + ev.detail).split("\n").slice(-9).join("\n"); }
    while (ol.children.length > 6) ol.firstChild.remove();
    relayout();
  }
  let liveOpening = false;
  async function figure(f){
    if (!on() || typeof f.value !== "number") return;
    figs.push(f);
    if (!live && !liveOpening) { liveOpening = true; live = await open("live", "LIVE FIGURES", `<div class="lf"></div>`, { slot: 1, fast: true }); liveOpening = false; }
    if (live) live.el.querySelector(".lf").innerHTML = figs.slice(-4).map(x => `<div><span>${esc(x.label)}</span><b>${kfmt(x)}</b></div>`).join("");
  }

  /* ---------------- answer screens */
  const gauge = (pct, tone) => { const c = 2 * Math.PI * 15, f = Math.max(0, Math.min(1, pct / 100));
    return `<svg class="kg ${tone}" viewBox="0 0 36 36"><circle cx="18" cy="18" r="15" class="bgc"/><circle cx="18" cy="18" r="15" class="fgc" stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}"/></svg>`; };
  function kpiHtml(ks){
    return `<div class="kt">${ks.map(k => { const { txt, st } = kDelta(k);
      return `<div class="k"><div class="kl">${esc(k.label)}</div><div class="kv2"><b data-v="${k.value}" data-f="${esc(k.format || "")}">0</b>${k.unit ? `<small>${esc(k.unit)}</small>` : ""}</div>
        ${k.format === "percent" ? gauge(k.value, st) : ""}${txt ? `<div class="kd ${st}">${esc(txt)}</div>` : ""}</div>`; }).join("")}</div>`; }
  function chartHtml(labels, vals){
    const mx = Math.max(...vals.map(v => Math.abs(v)), 1e-9), n = labels.length, w = 300, h = 130, bw = w / n * .62;
    return `<svg class="ch" viewBox="0 0 ${w} ${h + 28}">${labels.map((l, i) => { const bh = Math.abs(vals[i]) / mx * h, x = i * w / n + (w / n - bw) / 2;
      return `<rect class="bar" x="${x.toFixed(1)}" y="${(h - bh).toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" style="--i:${i}"/>
        <text x="${(x + bw / 2).toFixed(1)}" y="${(h - bh - 4).toFixed(1)}" class="tv">${esc(vals[i].toLocaleString("en-IN", { maximumFractionDigits: 1 }))}</text>
        <text x="${(x + bw / 2).toFixed(1)}" y="${h + 18}" class="tl">${esc(String(l).replace(/^SMLS\s*/i, "").replace(/^[↳\s]+/, "").slice(0, Math.max(4, Math.floor(46 / n))))}</text>`; }).join("")}<line x1="0" x2="${w}" y1="${h}" y2="${h}" class="ax"/></svg>`; }
  function compareHtml(ks){
    return `<div class="cmp">${ks.map((k, i) => { const mx = Math.max(Math.abs(k.value), Math.abs(k.previous), 1e-9), { txt, st } = kDelta(k);
      return `<div class="r"><span>${esc(k.label)}${k.group ? ` · ${esc(k.group.replace(/\s*\(.+\)/, ""))}` : ""}</span><em class="${st}">${esc(txt.split(" ").slice(0, 2).join(" "))}</em>
        <div class="bars"><i style="width:${(Math.abs(k.value) / mx * 100).toFixed(1)}%;animation-delay:${i * 70}ms"></i><i class="p" style="width:${(Math.abs(k.previous) / mx * 100).toFixed(1)}%;animation-delay:${i * 70 + 40}ms"></i></div></div>`; }).join("")}
      <div class="kv" style="margin-top:2px"><span>■ NOW</span><b class="off">■ ${esc(ks[0].previous_label || "PREVIOUS")}</b></div></div>`; }
  function mixHtml(ks){
    const tot = ks.reduce((a, k) => a + Math.abs(k.value), 0) || 1, R = 38, C = 2 * Math.PI * R; let off = 0;
    const pal = ["rgb(var(--hc))", "rgb(var(--ho))", "rgb(var(--hg))", "rgba(var(--hc),.45)", "rgba(var(--ho),.45)", "rgba(230,251,255,.5)"];
    const segs = ks.map((k, i) => { const f = Math.abs(k.value) / tot, s = `<circle class="seg" cx="48" cy="48" r="${R}" stroke="${pal[i % 6]}" stroke-dasharray="${(f * C).toFixed(1)} ${C.toFixed(1)}" stroke-dashoffset="${(-off * C).toFixed(1)}" style="animation-delay:${i * 90}ms"/>`; off += f; return s; }).join("");
    return `<div class="mix"><svg viewBox="0 0 96 96"><circle cx="48" cy="48" r="${R}" fill="none" stroke="rgba(var(--hc),.12)" stroke-width="12"/>${segs}</svg>
      <ul>${ks.map((k, i) => `<li><i style="background:${pal[i % 6]}"></i><span>${esc(k.label)}</span><b>${(Math.abs(k.value) / tot * 100).toFixed(1)}%</b></li>`).join("")}</ul></div>`; }
  function timelineHtml(sec){
    const done = timeline.filter(t => t.ms != null), mx = Math.max(...done.map(t => t.ms), 1);
    return `<div class="tl2">${done.slice(-6).map((t, i) => `<div class="r"><span>${esc(t.label)}</span><em>${(t.ms / 1000).toFixed(1)}s</em><i style="width:${Math.max(3, t.ms / mx * 100).toFixed(1)}%;animation-delay:${i * 80}ms"></i></div>`).join("")}
      <div class="tot"><span>ANSWERED IN</span><span>${sec ? sec + " s" : "—"}${done.some(t => /fast path/i.test(t.label)) ? " · FAST PATH" : ""}</span></div></div>`; }
  function countAll(el){ el.querySelectorAll("b[data-v]").forEach(b => { const v = +b.dataset.v, pct = b.dataset.f === "percent";
    countUp(b, v, x => (pct ? (Math.round(x * 100) / 100).toLocaleString("en-IN") + "%" : (Math.round(x * 100) / 100).toLocaleString("en-IN")), 1100); }); }
  async function reply(r){
    if (!on() || !r) return;
    const myRun = ++run; chain = 0;
    clearInterval(codeIv); lastSec = r.seconds || lastSec; gaugesDraw(); lastAct = Date.now();
    if (r.seconds) { answers++; secSum += r.seconds; } filesMade += (r.files || []).filter(f => f.format !== "chart").length;
    closeAll(p => ["proc", "link", "live", "q"].includes(p.kind) || IDLE.includes(p.kind));
    proc = link = live = null; lastOpened = null; pendingSteps.length = 0;
    await wait(420); if (myRun !== run) return;
    const go = async (...a) => myRun === run ? open(...a) : null;
    const txt = r.text || "", kpis = (r.kpis || []).filter(k => typeof k.value === "number");
    if (/🔒|not in your access/i.test(txt)) { await go("alert", "ACCESS // RESTRICTED", `<div class="big">🔒</div><p>${md(txt)}</p>`, { tone: "red", slot: 6, fromCore: true }); timeline.length = 0; return; }
    if (/⚠️/.test(txt) && !kpis.length) await go("alert", "ATTENTION", `<p>${md(txt.split("\n").find(l => l.includes("⚠️")) || txt)}</p>`, { tone: "red", slot: 6, fromCore: true });
    const groups = []; for (const k of kpis) { let g = groups.find(x => x.g === (k.group || "")); if (!g) groups.push(g = { g: k.group || "", ks: [] }); g.ks.push(k); }
    const seqSlots = groups.length > 1 ? [0, 3, 1, 4, 2, 5] : [0, 1, 3, 4, 2, 5]; let si = 0;
    const next = () => { const u = used(); while (si < seqSlots.length && u.has(seqSlots[si])) si++; return si < seqSlots.length ? seqSlots[si++] : freeSlot(); };
    for (const g of groups.slice(0, 2)) {
      const p = await go("kpi", (g.g || "KEY FIGURES").toUpperCase(), kpiHtml(g.ks.slice(0, 4)), { slot: next() });
      if (p) countAll(p.el);
    }
    const pv = (r.preview || [])[0];
    let chart = null;
    if (pv) { const ni = pv.columns.findIndex((c, i) => i > 0 && pv.rows.some(row => typeof row[i] === "number"));
      const rows = pv.rows.filter(row => typeof row[ni] === "number" && !/total|subtotal|inspection|tnature prod/i.test(String(row[0])) && !/^\s*↳/.test(String(row[0]))).slice(0, 6);
      if (ni > 0 && rows.length > 1) chart = [rows.map(x => x[0]), rows.map(x => x[ni]), pv.columns[ni]]; }
    if (!chart && kpis.length > 1) { const ks = kpis.filter(k => k.format !== "percent").slice(0, 5); if (ks.length > 1) chart = [ks.map(k => k.label), ks.map(k => k.value), "KEY FIGURES"]; }
    if (chart) await go("chart", "CHART // " + String(chart[2]).toUpperCase().slice(0, 30), chartHtml(chart[0], chart[1]), { slot: next() });
    if (pv) {
      const cols = pv.columns.slice(0, 5);
      await go("tbl", "TABLE // " + String(pv.title || "RESULT").toUpperCase().slice(0, 34), `<table><thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${
        pv.rows.slice(0, 7).map((row, i) => `<tr style="--i:${i}">${row.slice(0, 5).map(v => `<td>${num(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>
        <div class="more">${pv.rows.length > 7 ? `+${pv.rows.length - 7} more rows in chat` : ""}</div>`, { slot: next() });
    }
    if (txt && !/🔒/.test(txt) && !(/⚠️/.test(txt) && !kpis.length)) {
      const p = await go("ins", "INSIGHT // VERONICA", `<p class="it"></p>`, { slot: 6 });
      if (p) typeInto(p.el.querySelector(".it"), txt.replace(/\*\*/g, "").split("\n").filter(l => l.trim() && !/^ℹ️/.test(l)).slice(0, 5).map(l => l.length > 150 ? l.slice(0, 148) + "…" : l).join("\n"), 140);
    }
    const files = (r.files || []).filter(f => f.format !== "chart");
    if (files.length) await go("files", "OUTPUT // FILES", `<div class="fl">${files.map(f => fileLink(f, (f.format || "file").toUpperCase() + " · " + (f.filename || ""))).join("")}</div>`, { slot: 7, extra: true });
    const cmp = kpis.filter(k => typeof k.previous === "number" && k.format !== "percent" && (k.value || k.previous)).slice(0, 5);
    if (cmp.length >= 2 && nova()) await go("cmp", "COMPARE // VS " + String(cmp[0].previous_label || "PREVIOUS").replace(/^vs\s*/i, "").toUpperCase().slice(0, 22), compareHtml(cmp), { slot: next(), extra: true });
    const mixK = (groups[0] ? groups[0].ks : []).filter(k => k.format !== "percent" && !/total|subtotal|inspection/i.test(k.label) && k.value > 0).slice(0, 6);
    if (mixK.length >= 2 && nova()) await go("mix", "MIX // SHARE OF TOTAL", mixHtml(mixK), { slot: next(), extra: true });
    if (nova() && timeline.some(t => t.ms != null)) await go("time", "RESPONSE // TIMELINE", timelineHtml(r.seconds), { slot: 8, extra: true });
    timeline.length = 0;
  }

  /* ---------------- a file was attached: scan it on screen */
  function spark(vals){
    if (vals.length < 2) return "";
    const mn = Math.min(...vals), mx = Math.max(...vals), w = 260, h = 40, sx = i => i / (vals.length - 1) * w, sy = v => h - 3 - (v - mn) / ((mx - mn) || 1) * (h - 6);
    const d = vals.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join(" ");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="a" d="${d} L${w},${h} L0,${h}Z"/><path d="${d}"/></svg>`; }
  async function scan(f){
    if (!on() || !f) return;
    clearTimeout(bootT); lastAct = Date.now(); if (document.body.classList.contains("busy")) return;
    run++; closeAll(); await wait(panels.length ? 430 : 0);
    const myRun = run; chain = 0; lastOpened = null;
    HoloAudio.scan();
    let body = `<div class="fi"><div class="nm">${esc(f.name)}</div>`;
    if (f.kind === "table") {
      const s = (f.sheets || []).slice().sort((a, b) => b.rows - a.rows)[0] || { rows: 0, cols: 0, columns: [], preview: [], totals: {} };
      const nIdx = s.columns.findIndex(c => s.totals && s.totals[c]);
      const vals = nIdx >= 0 ? s.preview.map(r => Number(r[nIdx])).filter(v => !isNaN(v)) : [];
      body += `<div class="kv"><span>SHEETS</span><b>${(f.sheets || []).length}</b></div><div class="kv"><span>ROWS × COLUMNS</span><b>${s.rows.toLocaleString("en-IN")} × ${s.cols}</b></div>
        <div class="chips">${s.columns.slice(0, 10).map(c => `<em>${esc(c)}</em>`).join("")}${s.columns.length > 10 ? `<em>+${s.columns.length - 10}</em>` : ""}</div>
        ${Object.entries(s.totals || {}).slice(0, 3).map(([c, t]) => `<div class="kv"><span>Σ ${esc(c)}</span><b>${num(t.sum)}</b></div>`).join("")}${spark(vals)}`;
    } else if (f.kind === "pdf") body += `<div class="kv"><span>TYPE</span><b>PDF DOCUMENT</b></div><div class="kv"><span>PAGES</span><b>${f.pages ?? "—"}</b></div>${f.excerpt ? `<p style="opacity:.8">${esc(f.excerpt.slice(0, 160))}…</p>` : ""}`;
    else body += `<div class="kv"><span>TYPE</span><b>${esc(String(f.kind || "file").toUpperCase())}</b></div><div class="kv"><span>SIZE</span><b>${Math.max(1, Math.round((f.size || 0) / 1024))} KB</b></div>`;
    body += `<div class="kv"><span>STATUS</span><b class="ok">READY · ASK ANYTHING ABOUT IT</b></div></div><span class="beam"></span>`;
    if (myRun === run) await open("scan", "SCAN // " + String(f.kind === "table" ? "DATASET" : f.kind || "FILE").toUpperCase(), body, { slot: 6, fromCore: true });
  }

  addEventListener("pointerdown", () => { lastAct = Date.now(); }, true); addEventListener("keydown", () => { lastAct = Date.now(); }, true);
  return { ask, step, figure, reply, closeAll, scan, idle, spawn, cycle, boot: () => { booted = false; boot(); } };
})();

/* hooks into the normal chat flow (all other themes unaffected) */
{
  const _send = send;
  send = async function(text, opts){ if ((text && text.trim()) || document.querySelector("#atts .att:not(.err)")) HoloOS.ask((text || "").trim() || "Analyse the attached file"); return _send(text, opts); };
  const _step = Activity.step.bind(Activity);
  Activity.step = ev => { _step(ev); HoloOS.step(ev); };
  const _add = Analysis.add.bind(Analysis);
  Analysis.add = f => { _add(f); if (document.body.classList.contains("busy")) HoloOS.figure(f); };
  const _rr = renderReply;
  renderReply = function(r, el){ const out = _rr(r, el); HoloOS.reply(r); return out; };
}
