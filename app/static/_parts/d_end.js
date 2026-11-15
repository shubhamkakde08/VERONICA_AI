<script>
if ("serviceWorker" in navigator && !EMBED_SW()) navigator.serviceWorker.register("/sw.js").catch(() => {});
function EMBED_SW(){ return new URLSearchParams(location.search).get("embed") === "1"; }
/* ---------------- views:  full (layout) | max (chat fills the screen) | dock (floating window) | home (minimised: core only)
   URL: ?view=dock|max|home  ·  /chat = max  ·  ?embed=1 = inside another web page (widget.js) */
const QS = new URLSearchParams(location.search), EMBED = QS.get("embed") === "1";
if (EMBED) document.body.classList.add("embed");
const autosize = () => { const t = $("#t"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 140) + "px"; };
const fitPlaceholder = () => { $("#t").placeholder = (innerWidth < 520 || View.mode === "dock") ? "Ask anything…" : "Ask VERONICA anything – or type / for reports"; };
const View = {
  mode: "full",
  set(m, opts = {}){
    const chat = $("#chat"), bar = $("#inputbar");
    this.mode = m;
    document.body.classList.remove("view-home", "view-dock", "view-full", "view-max"); document.body.classList.add("view-" + m);
    if (m === "dock") { $("#dockBody").append(chat, bar); $("#dock").hidden = false; }
    else { $("#center").append(chat, bar); $("#dock").hidden = true; }
    if (!opts.keepUrl && !EMBED) { const u = new URL(location.href); if (m === "full") u.searchParams.delete("view"); else u.searchParams.set("view", m);
      history.replaceState(null, "", u.pathname.replace(/\/chat\/?$/, "/") + u.search + u.hash); }
    if (m !== "home") {
      if (opts.greet !== false) Greeter.greet(false, !!opts.voice);
      if (!matchMedia("(pointer:coarse)").matches) setTimeout(() => $("#t").focus({ preventScroll: true }), 60);
      $("#log").scrollTop = $("#log").scrollHeight;
    }
    fitPlaceholder();
    if (EMBED) try { parent.postMessage({ veronica: m === "max" ? "full" : m === "full" ? "full" : m }, "*"); } catch {}
  }
};
addEventListener("resize", fitPlaceholder);
$("#fabTip").onclick = () => View.set("dock", { voice: true });
$("#fab").onclick = () => View.set(View.mode === "dock" ? "home" : "dock", { voice: true });
$("#dockMax").onclick = () => View.set("full");
$("#maxBtn").onclick = () => View.set("max");
$("#restoreBtn").onclick = () => View.set("full");
$("#popBtn").onclick = () => View.set("dock");
$("#homeBtn").onclick = () => View.set("home");

/* ---------------- greeting: hello + a polite question (voice only after a tap - browsers block sound before that) */
const Greeter = {
  done: false,
  boss: () => !!ME && !!ME.boss,
  spoken: false,
  texts(lang, name){
    const h = new Date().getHours(), part = h < 12 ? 0 : h < 17 ? 1 : 2;
    if (this.boss()) return ({
      "hi-IN": ["Hello Boss 👋 Kaise hain aap?", "Aaj main aapki kya madad kar sakti hoon?"],
      "mr-IN": ["Hello Boss 👋 Kase aahat?", "Aaj mi tumhala kashi madat karu?"],
      "gu-IN": ["Hello Boss 👋 Kem cho?", "Aaje hu tamari shu madad kari shaku?"],
      "raj-IN": ["Hello Boss 👋 Kai haal hai sa?", "Aaj mhain aapri kai madad kar sakoon?"],
      "or-IN": ["Hello Boss 👋 Kemiti achhanti?", "Aaji mu apananka kana sahajya kariparibi?"],
    })[lang] || ["Hello Boss 👋 How are you? Is everything good?", "How can I help you today? (I promise not to judge the scrap % 😄)"];
    const T = {
      "en-IN": [`${["Good morning", "Good afternoon", "Good evening"][part]}, ${name} 🙏 I'm VERONICA, your AI assistant.`, "How may I help you today?"],
      "hi-IN": [`${["Suprabhat", "Namaste", "Shubh sandhya"][part]} ${name} ji 🙏 Main VERONICA hoon, aapki AI assistant.`, "Aaj main aapki kya madad kar sakti hoon?"],
      "mr-IN": [`Namaskar ${name} ji 🙏 Mi VERONICA, tumchi AI sahayika.`, "Aaj mi tumhala kashi madat karu?"],
      "gu-IN": [`Namaste ${name} ji 🙏 Hu VERONICA chhu, tamari AI assistant.`, "Aaje hu tamari shu madad kari shaku?"],
      "raj-IN": [`Khamma ghani ${name} sa 🙏 Mhain VERONICA hoon, aapri AI sahayak.`, "Aaj mhain aapri kai madad kar sakoon?"],
      "or-IN": [`Namaskar ${name} 🙏 Mu VERONICA, apananka AI sahayika.`, "Aaji mu apananka kana sahajya kariparibi?"],
    };
    return T[lang] || T["en-IN"];
  },
  welcomeVoice(){                       // "Hello Boss…" out loud once per sign-in, even with the chat minimised
    if (this.spoken || store.get("rb_greetvoice") === "0") return;
    const [hello, ask] = this.texts($("#lang").value, (ME.name || "").split(" ")[0]);
    const line = (hello + " " + ask).replace(/\p{Extended_Pictographic}|\uFE0F/gu, "").trim();
    const go = () => { if (this.spoken) return; this.spoken = true; this.boss() ? this.intro(line) : Voice.say(line, { quiet: true }); };
    if (navigator.userActivation && navigator.userActivation.hasBeenActive) return void setTimeout(go, 400);
    const once = () => { removeEventListener("pointerdown", once, true); removeEventListener("keydown", once, true); if (!document.body.classList.contains("busy")) go(); };
    addEventListener("pointerdown", once, true); addEventListener("keydown", once, true);
  },
  async intro(line){                    // admin login: ONE track = music + VERONICA's own Sulafat voice (English or Hindi)
    const H = typeof HoloAudio !== "undefined" ? HoloAudio : null;
    if (H) H.hold(true);                                                             // Iron-Man BGM waits until the intro is over
    const lang = $("#lang").value || "en-IN", hi = lang !== "en-IN";              // Hindi track for Hindi (and other Indian languages)
    const done = () => { if (H) H.hold(false); };
    let music = null;
    try { music = new Audio("/intro.mp3?lang=" + (hi ? "hi" : "en")); music.volume = 1; await music.play(); } catch { music = null; }
    if (!music) {                                                                    // browser blocked the sound: say hello with her voice instead
      try { await Voice.say(hi ? line : "Hello Boss! How are you? Is everything good? How can I help you today?", { quiet: true }); } catch {}
      return done();
    }
    setState("speaking");
    await new Promise(res => { music.onended = res; music.onerror = res; setTimeout(res, 20000); });
    if (document.body.classList.contains("speaking")) setState("ready");
    done();
  },
  _loud(blob){                          // play a voice clip boosted x2.2 through Web Audio (louder than the plain <audio> volume)
    return new Promise(res => {
      try {
        const url = URL.createObjectURL(blob), a = new Audio(url), ctx = Voice.audioCtx();
        if (ctx) { const src = ctx.createMediaElementSource(a), g = ctx.createGain(), comp = ctx.createDynamicsCompressor();
          g.gain.value = 2.2; comp.threshold.value = -10; comp.ratio.value = 4; src.connect(g); g.connect(comp); comp.connect(ctx.destination);
          const an = ctx.createAnalyser(); an.fftSize = 256; comp.connect(an); const buf = new Uint8Array(an.frequencyBinCount); let raf = 0;
          const loop = () => { an.getByteFrequencyData(buf); setLvl(1 + buf.reduce((x, y) => x + y, 0) / buf.length / 255 * .9); raf = requestAnimationFrame(loop); }; loop();
          a.addEventListener("ended", () => cancelAnimationFrame(raf)); }
        setState("speaking");
        const fin = ok => { URL.revokeObjectURL(url); setLvl(1); if (document.body.classList.contains("speaking")) setState("ready"); res(ok); };
        a.onended = () => fin(true); a.onerror = () => fin(false);
        a.play().catch(() => fin(false));
      } catch { res(false); }
    });
  },
  async greet(force, voice){
    if (!ME || (this.done && !force)) return;
    this.done = true;
    if ($("#log").children.length && !force) return;
    const first = (ME.name || "").split(" ")[0] || ME.name;
    const [hello, ask] = this.texts($("#lang").value, first);
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const a = add("bot", '<div class="bt"><span class="tdots"><i></i><i></i><i></i></span></div>');
    const speak = () => { if (this.spoken || store.get("rb_greetvoice") === "0") return;
      this.spoken = true; const ln = (hello + " " + ask).replace(/\p{Extended_Pictographic}|\uFE0F/gu, "").trim();
      this.boss() ? this.intro(ln) : Voice.say(ln, { quiet: true }); };
    if (voice || (navigator.userActivation && navigator.userActivation.hasBeenActive)) speak();
    else {               // browsers allow sound only after the first tap/key - greet then
      const once = e => { if (e.target.closest && e.target.closest("#f, #mic, #stage, #talkBtn, #talkBtn2")) return;
        removeEventListener("pointerdown", once, true); removeEventListener("keydown", once, true); if (!document.body.classList.contains("busy")) speak(); };
      addEventListener("pointerdown", once, true); addEventListener("keydown", once, true);
    }
    await sleep(550); a.innerHTML = `<div class="bt">${md(hello)}</div>`;
    const b = add("bot", '<div class="bt"><span class="tdots"><i></i><i></i><i></i></span></div>');
    await sleep(750); b.innerHTML = `<div class="bt">${md(ask)}</div>`;
    $("#log").scrollTop = $("#log").scrollHeight;
  }
};
$("#log").addEventListener("click", e => { const c = e.target.closest(".qchip"); if (!c) return; if (c.dataset.dash) openDashboards(); else send(c.dataset.q); });

/* ---------------- Stop her while she speaks (button or Esc) */
function stopSpeaking(){ Voice.stop(); if (typeof Live !== "undefined" && Live.on) { Live.flush(); setState("listening"); } else setState(Voice.talk ? "listening" : "ready"); setLvl(1); }
$("#stopBtn").onclick = stopSpeaking;
addEventListener("keydown", e => { if (e.key === "Escape" && document.body.classList.contains("speaking")) { e.preventDefault(); stopSpeaking(); } });

/* ---------------- neural console: live code motion, shows the real steps while she works */
const codeFx = (() => {
  const pre = $("#codeFx"); if (!pre) return { push(){} };
  const LIB = ["-- VERONICA · read-only session · role checked", "SELECT plant_code, SUM(prod_wt_mt) AS mt", "  FROM VIEW_REJECTION_PBI WHERE tnature IN ('PROD','REJP')",
    "  GROUP BY plant_code;", "yield = prod / (prod + rejp)   # 92.94", "for jc in job_cards: jc.bucket = classify(jc.scrap_pct)",
    "delta = this_month - last_month  # explain drivers", "forecast = mtd / days_elapsed * days_in_month", "checks: U1 + U2 == company ✓",
    "▸ guard: SELECT-only ✓  private views locked ✓", "insight.rank(by='impact').top(3)", "draft.mail(to='HOD', tone='professional')"];
  const RX = /('[^']*'|"[^"]*")|(--.*$|#.*$)|(▸.*$)|\b(SELECT|FROM|WHERE|GROUP BY|AS|IN|SUM|MAX|for|if|def|return)\b|\b(\d+(?:\.\d+)?)\b/g;
  const hl = t => { let out = "", last = 0;
    t.replace(RX, (m, s1, c1, a1, k1, n1, off) => { out += esc(t.slice(last, off)); out += `<span class="${s1 ? "s" : c1 ? "c" : a1 ? "a" : k1 ? "k" : "n"}">${esc(m)}</span>`; last = off + m.length; return m; });
    return out + esc(t.slice(last)); };
  let lines = [], queue = [], target = LIB[0], i = 0, li = 1;
  const next = () => queue.shift() || LIB[li++ % LIB.length];
  (function tick(){
    const busy = document.body.classList.contains("busy");
    if (!document.hidden && pre.offsetParent !== null) {
      i = REDUCE ? target.length : i + (busy ? 3 : 1);
      if (i >= target.length) { lines.push(target); if (lines.length > 9) lines.shift(); target = next(); i = 0; }
      pre.innerHTML = lines.map(hl).join("\n") + (lines.length ? "\n" : "") + hl(target.slice(0, i)) + '<span class="cur"></span>';
    }
    setTimeout(tick, i === 0 ? (busy ? 120 : 800) : (busy ? 12 : 40));
  })();
  return { push(t){ queue.push(String(t)); if (queue.length > 12) queue.shift(); } };
})();

/* ---------------- access denied: red alert look + alert music for a few seconds, and a polite banner on the answer */
const Denied = (() => {
  let tm = 0, out = 0, nodes = [];
  function sound(){
    let snd = true; try { snd = store.get("rb_holo_sfx") !== "0" || (store.get("rb_holo_music") || "on") !== "off"; } catch {}
    if (!snd || typeof Voice === "undefined") return;
    const ctx = Voice.audioCtx(); if (!ctx) return;
    try { HoloAudio.hold(true); } catch {}                                         // the normal BGM steps aside
    const t0 = ctx.currentTime, master = ctx.createGain(); master.gain.setValueAtTime(0, t0);
    master.gain.linearRampToValueAtTime(.16, t0 + .4); master.gain.setValueAtTime(.16, t0 + 6.2); master.gain.linearRampToValueAtTime(0, t0 + 8);
    master.connect(ctx.destination);
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 520; lp.connect(master);
    for (const f of [55, 55 * 1.006, 65.4]) {                                        // dark minor drone (A + C) - "red alert" music
      const o = ctx.createOscillator(); o.type = "sawtooth"; o.frequency.value = f; o.connect(lp); o.start(t0); o.stop(t0 + 8.1); nodes.push(o); }
    for (let i = 0; i < 4; i++) {                                                    // soft two-tone alarm, four times
      for (const [f, d] of [[880, 0], [660, .22]]) {
        const o = ctx.createOscillator(), g = ctx.createGain(), s = t0 + .2 + i * 1.5 + d;
        o.type = "square"; o.frequency.value = f; g.gain.setValueAtTime(0, s); g.gain.linearRampToValueAtTime(.05, s + .02); g.gain.exponentialRampToValueAtTime(.0005, s + .2);
        o.connect(g); g.connect(master); o.start(s); o.stop(s + .22); nodes.push(o); } }
    setTimeout(() => { try { HoloAudio.hold(false); } catch {} }, 8200);
  }
  function fire(el){
    clearTimeout(tm); clearTimeout(out); document.body.classList.remove("denyOut"); document.body.classList.add("denied");
    nodes.forEach(o => { try { o.stop(); } catch {} }); nodes = [];
    if (el && !el.querySelector(".deny")) el.insertAdjacentHTML("afterbegin",
      `<div class="deny"><i>🔒</i><div><b>Access restricted</b>This information is not in your access. Please contact your admin if you need it.</div></div>`);
    sound();
    tm = setTimeout(() => { document.body.classList.add("denyOut"); out = setTimeout(() => document.body.classList.remove("denied", "denyOut"), 1200); }, 8000);
  }
  return { fire };
})();
{
  const _rr = renderReply;
  renderReply = function(r, el){
    const out = _rr(r, el);
    if (r && (r.denied || /not in your access/i.test(r.text || ""))) Denied.fire(out || el);
    return out;
  };
}

/* ---------------- wide tables: a ⤢ button opens them full screen (nothing is cut off in a narrow chat) */
function tblDecorate(root){
  (root || document).querySelectorAll("#log .tbl:not([data-fx])").forEach(t => {
    t.dataset.fx = "1"; const b = document.createElement("button"); b.type = "button"; b.className = "tfx"; b.textContent = "⤢ Full view";
    b.title = "Open this table full screen"; b.onclick = () => { $("#tfTitle").textContent = t.querySelector("b")?.textContent || "Table";
      const tb = t.querySelector("table"); $("#tfBody").innerHTML = ""; if (tb) $("#tfBody").appendChild(tb.cloneNode(true)); tblFull.showModal(); };
    t.prepend(b);
    const tb = t.querySelector("table"), geo = tb && typeof WorldMap !== "undefined" ? WorldMap.fromTable(tb) : null;
    if (geo && geo.rows.length) { const m = document.createElement("button"); m.type = "button"; m.className = "tfx"; m.textContent = "🌍 Map";
      m.title = "Show this on the world map - click a country or region to zoom in";
      m.onclick = () => WorldMap.open({ title: (t.querySelector("b")?.textContent || "Country-wise") + " · " + geo.measure, measure: geo.measure, rows: geo.rows });
      b.after(m); }
  });
}
new MutationObserver(() => tblDecorate()).observe(document.getElementById("log"), { childList: true, subtree: true });

/* ---------------- dashboards (personal live links) */
async function openDashboards(name){
  // noopener = the dashboard gets its own browser process; a heavy dashboard or PDF export never freezes VERONICA
  window.open("/?go=dash" + (name ? "&name=" + encodeURIComponent(name) : ""), "_blank", "noopener");
}
$("#dashBtn").onclick = () => openDashboards();

/* ---------------- events */
$("#skills").addEventListener("click", e => { const b = e.target.closest(".chip"); if (!b) return; repDlg.close();
  const q = b.dataset.q; if (q === "/teach") send(q); else { chatMode(true); $("#t").value = q + " "; $("#t").focus(); } });
$("#navReports").onclick = () => { loadDashboard(); repDlg.showModal(); };
$("#navAssist").onclick = () => View.set(View.mode === "home" ? "full" : View.mode);
$("#f").addEventListener("submit", e => { e.preventDefault(); const v = $("#t").value; $("#t").value = ""; autosize(); send(v); });
$("#t").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer:coarse)").matches) { e.preventDefault(); $("#f").requestSubmit(); } });
$("#t").addEventListener("input", autosize);
$("#newBtn").onclick = async () => { try { await api("/api/chat/reset", { method: "POST" }); } catch {} $("#log").innerHTML = ""; Greeter.done = false; Greeter.greet(); };
$("#panelsBtn").onclick = () => document.body.classList.toggle("drawer");
$("#histBtn").onclick = async () => {
  const rows = await api("/api/history?limit=30");
  $("#histBody").innerHTML = rows.map(r => `<div class="hrow"><b>#${r.id} ${esc(r.title)}</b><div class="muted">${esc(when(r.created_at))} · ${r.row_count} rows${r.skill_name ? " · /" + esc(r.skill_name) : ""}</div>
    <div class="files">${(r.files || []).map(f => fileLink(f, f.format)).join("")}</div></div>`).join("") || "<p class='muted'>No reports yet.</p>";
  $("#hist").showModal();
};
const startTalk = () => (ME?.live && window.AudioWorkletNode && window.WebSocket) ? Live.start() : Voice.talkLoop();
$("#talkBtn").onclick = e => { e.stopPropagation(); startTalk(); };
$("#talkBtn2").onclick = startTalk;
$("#stage").onclick = startTalk;
$("#endTalk").onclick = () => { if (Live.on) Live.stop(); else Voice.endTalk(); };

/* ---------------- boot */
async function boot(){
  try {
    ME = await api("/api/me");
    store.set("rb_session", token); $("#login").style.display = "none";
    try { await api("/api/session-cookie", { method: "POST" }); } catch {}     // dashboard / file links need this signed-in browser
    const nxt = QS.get("next") || "";
    if (/^\/(dash|files)\b/.test(nxt) && !nxt.startsWith("//")) { location.replace(nxt); return; }   // came from a protected link
    if (!$("#log").children.length) { try { await api("/api/chat/reset", { method: "POST" }); } catch {} }   // screen is empty -> no old context
    const nm = ME.assistant || "VERONICA";
    document.querySelectorAll(".aiNm").forEach(e => e.textContent = nm);
    document.title = `${nm} AI`;
    $("#acctName").textContent = ME.name; if (typeof Rail !== "undefined") Rail.who(ME); $("#who").textContent = `${ME.name} · ${ME.role}`;
    applyThemes();
    $("#menuBtn").textContent = (ME.name || "?").split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
    if (ME.data_synced_at) { const d = new Date(String(ME.data_synced_at).replace(" ", "T"));
      if (!isNaN(d)) $("#syncPill").textContent = "Live · ERP synced " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }); }
    const chips = [];
    if (ME.can_teach) chips.push(`<button class="chip teach" type="button" data-q="/teach">＋ Teach a report</button>`);
    for (const s of ME.skills) chips.push(`<button class="chip" type="button" data-q="/${esc(s.name)}" title="${esc(s.title)}">${esc(s.title)}</button>`);
    $("#skills").innerHTML = chips.join("") || `<div class="empty">No reports taught yet.</div>`;
    Analysis.render(false);
    loadDashboard(); Voice.prefetchAcks();
    const want = EMBED ? "dock" : (QS.get("view") || (location.pathname.replace(/\/+$/, "") === "/chat" ? "max" : "home"));
    View.set(["dock", "max", "home", "full"].includes(want) ? want : "home", { keepUrl: true });
    Greeter.welcomeVoice();                              // spoken hello at start ("Hello Boss…" for admins)
    try { Gesture.init(); } catch {}                     // ✋ hand-gesture control: only on this laptop (localhost) for admins
  } catch (e) { if (e.message !== "login") add("bot", `<div class="bt">⚠️ ${esc(e.message)}</div>`); }
}

/* ---------------- login / account */
$("#loginForm").addEventListener("submit", async e => {
  e.preventDefault(); $("#loginErr").textContent = "";
  if (!passwordMode) { token = $("#tok").value.trim(); return boot(); }
  $("#loginBtn").disabled = true;
  try {
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: $("#user").value, password: $("#pass").value }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { $("#loginErr").textContent = d.detail || "Sign-in failed"; return; }
    token = d.token; $("#pass").value = ""; $("#log").innerHTML = ""; Greeter.done = false; boot();
  } catch { $("#loginErr").textContent = "Cannot reach the server. Check your internet connection."; }
  finally { $("#loginBtn").disabled = false; }
});
$("#menuBtn").onclick = () => { $("#pwErr").textContent = ""; $("#acct").showModal(); };

/* ---------------- looks per user: hide the ones the admin has not given this user; admin edits them here */
function applyThemes(){
  const ok = ME && ME.themes && ME.themes.length ? ME.themes : null;
  document.querySelectorAll(".seg button[data-theme]").forEach(b => { b.hidden = !!ok && !ok.includes(b.dataset.theme); });
  const cur = (document.body.className.match(/theme-(aurora|arc|nova|forge|titan)/) || [])[1] || (document.body.classList.contains("theme-holo") ? "holo" : "aurora");
  if (ok && !ok.includes(cur)) setTheme(cur);                                      // setTheme moves them to an allowed look
  const adm = $("#themeAdminRow"); if (adm) adm.hidden = !(ME && ME.is_admin);
  const ab = $("#admBtn"); if (ab) ab.hidden = !(ME && ME.is_admin);
}
const THEME_NAMES = { aurora: "Aurora", arc: "Arc", holo: "Holo", forge: "Forge", titan: "Titan", atlas: "Atlas" };
/* ================= Admin console (admin role only) - one place for users, data limits, looks, roles, report access, security log */
const SEC_KIND = { report_blocked: "Report", dashboard_blocked: "Dashboard", table_blocked: "View / table", free_sql_blocked: "Free question (locked)",
  data_outside_access: "Data outside access", send_blocked: "Send to wrong person", teach_blocked: "Teach report", schedule_blocked: "Schedule",
  admin_blocked: "Admin action", login_locked: "Login locked", rbac_change: "Rights change (by admin)",
  link_not_yours: "Opened someone else's link", link_without_login: "Link opened without sign-in" };
const ADM = { page: "overview", rb: null, ta: null, sec: [], days: 30, q: "", plants: null };
const ADM_PAGES = {
  overview: ["Overview", "Who can see what, at a glance. Click any number to open it."],
  users: ["Users", "Add people, set their role, e-mail and login, and choose who gets security alert mails (e.g. the director). Every change saves at once and is written to the Security log."],
  scope: ["Division & plants", "Limit the data a person sees: U1 Welded or U2 Seamless, and which plants in Scrap MIS and the Issue dashboard."],
  looks: ["Looks", "Which screen themes each person may use. Hand gestures stay with admin and manager roles."],
  roles: ["Roles & data views", "A role is a set of rights. Tick the ERP views each role may read, then Save."],
  reports: ["Report access", "Which roles may run each report and open its dashboard. Nothing ticked = everyone whose views cover it. Admins always can."],
  security: ["Security log", "Every request refused for lack of rights, and every rights change made here. Newest first."],
};
const ini = n => String(n || "?").trim().split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
const admPost = (p, body, method) => api(p, { method: method || "POST", body: body ? JSON.stringify(body) : undefined });
function admMsg(t, bad){
  const m = $("#admMsg"); m.textContent = t || ""; m.className = t ? (bad ? "bad" : "ok") : "";
  clearTimeout(admMsg.tm); if (t && !bad) admMsg.tm = setTimeout(() => admMsg(""), 4500);
}
function admSheet(html){ const s = $("#admSheet"); if (!html) { s.hidden = true; s.innerHTML = ""; return; } s.innerHTML = html; s.hidden = false; const f = s.querySelector("input,select,button.p"); if (f) setTimeout(() => f.focus(), 30); }
try { if (store.get("rb_adm_light") === "1") $("#admCon").classList.add("light"); } catch {}
async function openAdmin(page){
  if (!(ME && ME.is_admin)) return;
  if ($("#acct").open) $("#acct").close();
  if (!$("#admCon").open) $("#admCon").showModal();
  $("#admWho").textContent = "Signed in as " + (ME.name || "admin");
  $("#admMode").textContent = $("#admCon").classList.contains("light") ? "☾" : "☀";
  await admGo(page || ADM.page);
}
async function admGo(page, keepMsg){
  ADM.page = page; admSheet("");
  document.querySelectorAll("#admNav [data-p]").forEach(b => b.classList.toggle("on", b.dataset.p === page));
  const [t, s] = ADM_PAGES[page]; $("#admTitle").textContent = t; $("#admSub").textContent = s; $("#admTools").innerHTML = "";
  if (!keepMsg) admMsg("");
  if (!keepMsg) $("#admBody").innerHTML = `<div class="admLoad">Loading…</div>`;
  try {
    const need = { overview: "rts", users: "r", scope: "t", looks: "t", roles: "r", reports: "r", security: "s" }[page];
    const [rb, ta, sec] = await Promise.all([need.includes("r") ? api("/api/admin/rbac") : null, need.includes("t") ? api("/api/admin/themes") : null,
      need.includes("s") ? api("/api/admin/security?days=" + (page === "overview" ? 7 : ADM.days)) : null]);
    if (rb) ADM.rb = rb; if (ta) ADM.ta = ta; if (sec) ADM.sec = sec.events || [];
  } catch (e) { $("#admBody").innerHTML = `<div class="admEmpty">⚠️ ${esc(e.message)}</div>`; return; }
  ({ overview: admOverview, users: admUsers, scope: admScope, looks: admLooks, roles: admRoles, reports: admReports, security: admSecurity })[page]();
  if (ADM.rb) $("#admNU").textContent = ADM.rb.users.filter(u => u.active).length;
}
function admOverview(){
  const rb = ADM.rb, act = rb.users.filter(u => u.active), den = ADM.sec.filter(r => r.kind !== "rbac_change");
  const lim = ADM.ta.users.filter(u => u.active && (u.division !== "ALL" || u.scrap_lines.length || (u.issue_plants || []).length)).length;
  const noMail = rb.users.filter(u => u.active && u.alerts && !u.email).length, alertN = rb.users.filter(u => u.active && u.alerts).length;
  const st = (n, l, p, tone) => `<button type="button" class="admStat ${tone || ""}" data-go="${p}"><b>${n}</b><span>${l}</span></button>`;
  $("#admBody").innerHTML = `<div class="admStats">${st(act.length, "active users", "users")}${st(rb.users.length - act.length, "disabled users", "users")}`
    + `${st(rb.roles.length, "roles", "roles")}${st(rb.skills.length, "reports & dashboards", "reports")}${st(lim, "users with data limits", "scope")}`
    + `${st(den.length, "access denied · 7 days", "security", den.length ? "warn" : "good")}${st(alertN, "people get security alerts", "users")}${noMail ? st(noMail, "alert receivers without e-mail", "users", "warn") : ""}</div>
    <div class="admGrid2"><section class="admCard"><h4>Roles</h4>${rb.roles.map(r => `<div class="admRow"><span class="admTag ${r.is_admin ? "a" : ""}">${esc(r.name)}</span><span class="muted">${esc(r.description || (r.is_admin ? "Everything" : ""))}</span><b title="users">${r.users}</b></div>`).join("")}</section>
    <section class="admCard"><h4>Latest security events</h4>${ADM.sec.slice(0, 8).map(r => `<div class="admRow"><span class="admDot ${r.kind === "rbac_change" ? "" : "w"}"></span><span><b>${esc(r.user_name || "—")}</b> · ${esc(SEC_KIND[r.kind] || r.kind)}<br><small class="muted">${esc((r.detail || "").slice(0, 120))}</small></span><small class="muted" style="white-space:nowrap">${esc(r.at || "")}</small></div>`).join("") || `<p class="muted">✅ Nothing in the last 7 days.</p>`}</section></div>`;
  $("#admNS").textContent = den.length || "";
}
function admUsers(){
  const rb = ADM.rb, isAdm = n => (rb.roles.find(r => r.name === n) || {}).is_admin;
  $("#admTools").innerHTML = `<input class="admSearch" id="admQ" type="search" placeholder="Search name, login, role…" value="${esc(ADM.q)}"><button class="admBtn p" type="button" data-act="newUser">＋ New user</button>`;
  const roleOpts = sel => rb.roles.map(r => `<option ${r.name === sel ? "selected" : ""}>${esc(r.name)}</option>`).join("");
  $("#admBody").innerHTML = `<div class="admTbl"><table><thead><tr><th>User</th><th>Role</th><th>E-mail <small>(alerts &amp; scheduled reports)</small></th><th>Data</th><th class="c" title="Security alert mails: someone asked outside their access, opened another person's link, etc.">Alerts</th><th class="c">Active</th><th></th></tr></thead><tbody>`
    + rb.users.map(u => `<tr data-u="${u.id}" data-q="${esc([u.name, u.username, u.role, u.email].join(" ").toLowerCase())}" class="${u.active ? "" : "off"}">
      <td><div class="admUser"><i>${esc(ini(u.name))}</i><div><input class="admIn" data-f="name" value="${esc(u.name)}" aria-label="Name" title="Click to rename"><small>${u.username ? "login " + esc(u.username) : "no login yet"} · #${u.id}${u.id === rb.me ? " · you" : ""}</small></div></div></td>
      <td><select class="admIn" data-f="role" aria-label="Role" ${u.id === rb.me ? 'disabled title="You cannot change your own role"' : ""}>${roleOpts(u.role)}</select></td>
      <td><input class="admIn ${!u.email && u.alerts ? "need" : ""}" data-f="email" type="email" value="${esc(u.email || "")}" placeholder="${u.alerts ? "needed for alerts" : "add e-mail"}" aria-label="E-mail" style="width:185px"></td>
      <td><button class="admChip ${u.division !== "ALL" ? "lim" : ""}" type="button" data-go="scope">${u.division === "ALL" ? "All divisions" : esc(u.division) + " only"}</button></td>
      <td class="c"><label class="admSw" title="${u.alerts ? "Gets security alert mails" : "No security alert mails"}${u.email ? "" : " – add an e-mail first"}"><input type="checkbox" data-f="alerts" ${u.alerts ? "checked" : ""}><span></span></label>${u.alerts && !u.email ? '<br><small style="color:var(--warn)">no e-mail</small>' : ""}</td>
      <td class="c"><label class="admSw" title="${u.active ? "Active – untick to block sign-in" : "Disabled"}"><input type="checkbox" data-f="active" ${u.active ? "checked" : ""} ${u.id === rb.me ? "disabled" : ""}><span></span></label></td>
      <td class="admAct"><button class="admBtn s" type="button" data-act="pw" data-id="${u.id}">🔑 ${u.username ? "Password" : "Set login"}</button>${u.id === rb.me ? "" : `<button class="admBtn s d" type="button" data-act="del" data-id="${u.id}" title="Delete user" aria-label="Delete user">🗑</button>`}</td></tr>`).join("")
    + `</tbody></table></div><p class="muted" style="margin-top:10px">A role change or disabling signs that person out at once.</p>`;
  admFilter();
}
function admFilter(){ const q = ADM.q.toLowerCase(); document.querySelectorAll("#admBody tr[data-q]").forEach(tr => { tr.hidden = !!q && !tr.dataset.q.includes(q); }); }
function admScope(){
  const d = ADM.ta;
  $("#admBody").innerHTML = `<div class="admTbl"><table><thead><tr><th>User</th><th>Division</th><th>Scrap MIS plants</th><th>Issue dashboard plants</th></tr></thead><tbody>`
    + d.users.map(u => `<tr data-u="${u.id}" class="${u.active ? "" : "off"}"><td><div class="admUser"><i>${esc(ini(u.name))}</i><div><b style="padding-left:6px">${esc(u.name)}</b><small>${esc(u.role)}${u.username ? " · " + esc(u.username) : ""}</small></div></div></td>
      <td><select class="admIn" data-div aria-label="Division">${[["ALL", "All (U1 + U2)"], ["U1", "U1 · Welded only"], ["U2", "U2 · Seamless only"]].map(([v, l]) => `<option value="${v}" ${u.division === v ? "selected" : ""}>${l}</option>`).join("")}</select></td>
      <td><button class="admChip ${u.scrap_lines.length ? "lim" : ""}" type="button" data-act="lines" data-id="${u.id}">${u.scrap_lines.length ? u.scrap_lines.length + " plants" : "All plants"} ✎</button></td>
      <td><button class="admChip ${(u.issue_plants || []).length ? "lim" : ""}" type="button" data-act="iplants" data-id="${u.id}">${(u.issue_plants || []).length ? u.issue_plants.length + " plants" : "All plants"} ✎</button></td></tr>`).join("")
    + `</tbody></table></div><p class="muted" style="margin-top:10px">Applies from that person's next report or dashboard. Amber = limited.</p>`;
}
function admLooks(){
  const d = ADM.ta;
  $("#admBody").innerHTML = `<div class="admTbl"><table><thead><tr><th>User</th>${d.themes.map(t => `<th class="c">${THEME_NAMES[t] || t}</th>`).join("")}</tr></thead><tbody>`
    + d.users.map(u => `<tr data-u="${u.id}" class="${u.active ? "" : "off"}"><td><b>${esc(u.name)}</b> <small class="muted">${esc(u.role)}</small></td>`
      + d.themes.map(t => `<td class="c"><input type="checkbox" data-t="${t}" ${u.themes.includes(t) ? "checked" : ""} aria-label="${esc(u.name)} – ${THEME_NAMES[t] || t}"></td>`).join("") + `</tr>`).join("")
    + `</tbody></table></div><p class="muted" style="margin-top:10px">Saves at once; applies the next time they open VERONICA. Each person needs at least one look.</p>`;
}
function admRoles(){
  const rb = ADM.rb, views = rb.views.slice().sort(), priv = new Set(rb.private.map(v => v.toLowerCase()));
  $("#admTools").innerHTML = `<input class="admIn" id="admNewRole" placeholder="New role, e.g. purchase" style="width:200px"><button class="admBtn p" type="button" data-act="addRole">＋ Create role</button>`;
  $("#admBody").innerHTML = rb.roles.map(r => { const t = new Set(r.allowed_tables || []), all = t.has("*"), n = [...t].filter(x => !/[*!]/.test(x)).length;
    const extra = [...t].filter(x => /[*!]/.test(x) && x !== "*");
    return `<section class="admRole" data-r="${esc(r.name)}"><div class="rh"><span class="admTag ${r.is_admin ? "a" : ""}" style="font-size:13px">${esc(r.name)}</span><span class="muted">${r.users} user${r.users === 1 ? "" : "s"}</span>
        <input class="admIn" data-k="description" value="${esc(r.description || "")}" placeholder="What this role is for">
        <button class="admBtn p s" type="button" data-act="saveRole">Save</button>${r.name !== "admin" && !r.users ? `<button class="admBtn s d" type="button" data-act="delRole">Delete</button>` : ""}</div>
      <div class="admPerm"><label><input type="checkbox" data-k="free_query" ${r.free_query ? "checked" : ""}> Free data questions</label>
        <label><input type="checkbox" data-k="can_teach" ${r.can_teach ? "checked" : ""}> Teach / change reports</label>
        <label><input type="checkbox" data-k="can_schedule" ${r.can_schedule ? "checked" : ""}> Schedule reports</label>
        <label title="Admins see and change everything, including this console"><input type="checkbox" data-k="is_admin" ${r.is_admin ? "checked" : ""}> <b>Admin</b></label></div>
      <details ${r.is_admin ? "" : "open"}><summary>ERP views: ${all ? "all" : n} ${all ? "" : "of " + views.length}</summary>
        <label style="display:flex;gap:6px;align-items:center;margin:8px 0 0;font-size:12.5px"><input type="checkbox" data-all ${all ? "checked" : ""}> <b>All views</b> <span class="muted">(private views stay hidden unless ticked)</span></label>
        <div class="admViews">${views.map(v => `<label title="${esc(v)}"><input type="checkbox" data-v="${esc(v)}" ${[...t].some(x => x.toLowerCase() === v.toLowerCase()) ? "checked" : ""}> ${esc(v)}${priv.has(v.toLowerCase()) ? ' <span style="color:var(--warn)">🔒</span>' : ""}</label>`).join("")}</div>
        ${extra.length ? `<p class="muted" style="margin:6px 0 0">Also kept: ${extra.map(esc).join(", ")}</p>` : ""}</details></section>`; }).join("");
}
function admReports(){
  const rb = ADM.rb, roles = rb.roles.filter(r => !r.is_admin);
  $("#admBody").innerHTML = `<div class="admTbl"><table><thead><tr><th>Report / dashboard</th><th>Roles allowed</th></tr></thead><tbody>`
    + rb.skills.map(s => `<tr data-s="${esc(s.name)}"><td><b>${esc(s.title)}</b><br><small class="muted">/${esc(s.name)} · ${esc((s.views || []).join(", ") || "—")}</small></td>
      <td>${roles.map(r => `<label class="admPill"><input type="checkbox" data-sr="${esc(r.name)}" ${s.allowed_roles.includes(r.name) ? "checked" : ""}>${esc(r.name)}</label>`).join("")}
      <div class="muted" style="font-size:11.5px;margin-top:3px">${s.allowed_roles.length ? "Only these roles (+ admins)" : "Open to every role whose views cover it"}</div></td></tr>`).join("") + `</tbody></table></div>`;
}
function admSecurity(){
  $("#admTools").innerHTML = `<select class="admIn" id="admDays" style="width:auto">${[7, 30, 90].map(d => `<option value="${d}" ${ADM.days === d ? "selected" : ""}>Last ${d} days</option>`).join("")}</select><button class="admBtn" type="button" data-act="secXls">⬇ Excel</button>`;
  const R = ADM.sec;
  $("#admNS").textContent = R.filter(r => r.kind !== "rbac_change").length || "";
  $("#admBody").innerHTML = R.length ? `<div class="admTbl"><table><thead><tr>${["When", "User", "Role", "What", "Detail", "Asked", "Channel"].map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>`
    + R.map(r => `<tr><td style="white-space:nowrap">${esc(r.at || "")}</td><td><b>${esc(r.user_name || "")}</b></td><td>${esc(r.role || "")}</td>
      <td><span class="admTag ${r.kind === "rbac_change" ? "" : "a"}">${esc(SEC_KIND[r.kind] || r.kind)}</span></td><td>${esc(r.detail || "")}</td>
      <td class="muted">${esc((r.request_text || "").slice(0, 160))}</td><td class="muted">${esc(r.channel || "")}</td></tr>`).join("") + `</tbody></table></div>`
    : `<div class="admEmpty">✅ No events in this period.</div>`;
}
function admPlants(title, who, groups, onSet, key){
  admSheet(`<div data-pick="${key}" data-id="${who.id}"><h3>${esc(title)}</h3><p>${esc(who.name)} — tick the plants this person may see. None ticked = all plants of their division.</p>
    <div class="admPick">${Object.keys(groups).map(g => `<b>${esc(g)}</b>` + groups[g].map(p => `<label><input type="checkbox" data-pk="${esc(p.k)}" ${onSet.has(p.k) ? "checked" : ""}> ${esc(p.label)}${p.n ? `<small>${p.n.toLocaleString("en-IN")} lines</small>` : ""}</label>`).join("")).join("") || "<p>No plants found.</p>"}</div>
    <div class="row"><button class="admBtn p" type="button" data-act="savePick">Save plants</button><button class="admBtn" type="button" data-act="sheetClose">Cancel</button></div></div>`);
}
$("#admCon").addEventListener("click", async e => {
  const t = e.target.closest("button,a"); if (!t) { if (e.target.id === "admSheet") admSheet(""); return; }
  const act = t.dataset.act, id = +t.dataset.id;
  if (t.id === "admClose") return $("#admCon").close();
  if (t.id === "admMode") { const l = $("#admCon").classList.toggle("light"); t.textContent = l ? "☾" : "☀"; try { store.set("rb_adm_light", l ? "1" : ""); } catch {} return; }
  if (t.dataset.p) return admGo(t.dataset.p);
  if (t.dataset.go) return admGo(t.dataset.go);
  if (!act) return;
  try {
    if (act === "sheetClose") return admSheet("");
    if (act === "newUser") return admSheet(`<form id="admNewUser"><h3>New user</h3><p>They sign in with this login and password. You can change everything later.</p>
      <label class="f">Full name</label><input class="admIn" name="name" required>
      <label class="f">Login</label><input class="admIn" name="username" required placeholder="e.g. RAVICHO" autocomplete="off">
      <label class="f">Password <small class="muted">(8+ characters)</small></label><input class="admIn" name="password" type="password" required minlength="8" autocomplete="new-password">
      <label class="f">Role</label><select class="admIn" name="role">${ADM.rb.roles.map(r => `<option ${r.name === "viewer" ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select>
      <label class="f">E-mail <small class="muted">(optional)</small></label><input class="admIn" name="email" type="email">
      <div class="row"><button class="admBtn p">Create user</button><button class="admBtn" type="button" data-act="sheetClose">Cancel</button></div></form>`);
    if (act === "pw") { const u = ADM.rb.users.find(x => x.id === id);
      return admSheet(`<form id="admPw" data-id="${u.id}"><h3>${u.username ? "Reset password" : "Set login"}</h3><p>${esc(u.name)} will be signed out everywhere and must use the new password.</p>
        <label class="f">Login</label><input class="admIn" name="username" required value="${esc(u.username || "")}" autocomplete="off">
        <label class="f">New password <small class="muted">(8+ characters)</small></label><input class="admIn" name="password" type="password" required minlength="8" autocomplete="new-password">
        <label class="f">Repeat password</label><input class="admIn" name="password2" type="password" required minlength="8" autocomplete="new-password">
        <div class="row"><button class="admBtn p">Save</button><button class="admBtn" type="button" data-act="sheetClose">Cancel</button></div></form>`); }
    if (act === "del") { const u = ADM.rb.users.find(x => x.id === id);
      return admSheet(`<div><h3>Delete ${esc(u.name)}?</h3><p>Their chat history and schedules are removed. Saved reports stay for audit. To only block sign-in, switch them off instead.</p>
        <div class="row"><button class="admBtn d" type="button" data-act="delYes" data-id="${u.id}">Delete for good</button><button class="admBtn" type="button" data-act="sheetClose">Cancel</button></div></div>`); }
    if (act === "delYes") { const u = ADM.rb.users.find(x => x.id === id); await admPost(`/api/admin/rbac/users/${id}`, null, "DELETE"); admMsg(`🗑 ${u.name} deleted.`); return admGo("users", true); }
    if (act === "lines") { const u = ADM.ta.users.find(x => x.id === id), g = { "U1 · Welded": [], "U2 · Seamless": [] };
      ADM.ta.scrap_lines.forEach(l => (/^S_/.test(l.k) ? g["U2 · Seamless"] : g["U1 · Welded"]).push({ k: l.k, label: l.label }));
      return admPlants("Scrap MIS plants", u, g, new Set(u.scrap_lines), "lines"); }
    if (act === "iplants") { const u = ADM.ta.users.find(x => x.id === id);
      admSheet(`<div><h3>Issue dashboard plants</h3><p>Loading plants…</p></div>`);
      ADM.plants = ADM.plants || (await api("/api/admin/issue-plants")).plants;
      const g = {}; ADM.plants.forEach(p => { const k = p.div === "U1" ? "U1 · Welded" : p.div === "U2" ? "U2 · Seamless" : (p.div || "Other"); (g[k] = g[k] || []).push({ k: p.plant, label: p.plant, n: p.lines }); });
      (u.issue_plants || []).forEach(p => { if (!ADM.plants.some(x => x.plant === p)) (g["Saved earlier"] = g["Saved earlier"] || []).push({ k: p, label: p }); });
      return admPlants("Issue dashboard plants", u, g, new Set(u.issue_plants || []), "iplants"); }
    if (act === "savePick") { const box = t.closest("[data-pick]"), uid = +box.dataset.id, picked = [...box.querySelectorAll("[data-pk]:checked")].map(x => x.dataset.pk);
      const u = ADM.ta.users.find(x => x.id === uid);
      if (box.dataset.pick === "lines") await admPost("/api/admin/scrap-lines", { user_id: uid, lines: picked });
      else await admPost("/api/admin/issue-plants", { user_id: uid, plants: picked });
      admMsg(`✅ Plants saved for ${u.name}.`); return admGo("scope", true); }
    if (act === "addRole") { const n = $("#admNewRole").value.trim().toLowerCase(); if (!n) return $("#admNewRole").focus();
      await admPost("/api/admin/rbac/roles", { name: n, description: "", allowed_tables: [], free_query: false }); admMsg(`✅ Role ${n} created – tick its views and Save.`); return admGo("roles", true); }
    const card = t.closest(".admRole");
    if (card && act === "saveRole") {
      const k = q => card.querySelector(`[data-k="${q}"]`), keep = (ADM.rb.roles.find(r => r.name === card.dataset.r).allowed_tables || []).filter(x => /[!]/.test(x) || (/\*/.test(x) && x !== "*"));
      const tabs = card.querySelector("[data-all]").checked ? ["*"] : []; card.querySelectorAll("[data-v]:checked").forEach(c => tabs.push(c.dataset.v));
      await admPost("/api/admin/rbac/roles", { name: card.dataset.r, description: k("description").value, allowed_tables: tabs.concat(keep),
        free_query: k("free_query").checked, can_teach: k("can_teach").checked, can_schedule: k("can_schedule").checked, is_admin: k("is_admin").checked });
      admMsg(`✅ Role ${card.dataset.r} saved.`); return admGo("roles", true); }
    if (card && act === "delRole") return admSheet(`<div><h3>Delete role ${esc(card.dataset.r)}?</h3><p>Nobody has this role now. This cannot be undone.</p>
      <div class="row"><button class="admBtn d" type="button" data-act="delRoleYes" data-r="${esc(card.dataset.r)}">Delete role</button><button class="admBtn" type="button" data-act="sheetClose">Cancel</button></div></div>`);
    if (act === "delRoleYes") { await admPost(`/api/admin/rbac/roles/${encodeURIComponent(t.dataset.r)}`, null, "DELETE"); admMsg(`🗑 Role ${t.dataset.r} deleted.`); return admGo("roles", true); }
    if (act === "secXls") {
      const head = ["When", "User", "Role", "Channel", "What", "Detail", "Asked", "IP"], q = v => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
      const csv = "﻿" + [head.join(",")].concat(ADM.sec.map(r => [r.at, r.user_name, r.role, r.channel, SEC_KIND[r.kind] || r.kind, r.detail, r.request_text, r.ip].map(q).join(","))).join("\r\n");
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "VERONICA_security_log.csv"; a.click(); return; }
  } catch (err) { admSheet(""); admMsg("⚠️ " + err.message, true); }
});
$("#admCon").addEventListener("change", async e => {
  const t = e.target, tr = t.closest("tr");
  try {
    if (t.id === "admDays") { ADM.days = +t.value; return admGo("security"); }
    if (ADM.page === "users" && tr && t.dataset.f) { const body = {}; body[t.dataset.f] = t.type === "checkbox" ? t.checked : t.value.trim();
      await admPost(`/api/admin/rbac/users/${tr.dataset.u}`, body);
      admMsg(t.dataset.f === "alerts" ? (t.checked ? "✅ Security alert mails ON for this person." : "✅ Security alert mails OFF for this person.") : "✅ Saved.");
      if (["role", "active", "alerts"].includes(t.dataset.f)) admGo("users", true); return; }
    if (ADM.page === "scope" && t.dataset.div !== undefined) {
      await admPost("/api/admin/division", { user_id: +tr.dataset.u, division: t.value }); admMsg("✅ Division saved – applies from their next report."); return admGo("scope", true); }
    if (ADM.page === "looks" && t.dataset.t) { const picked = [...tr.querySelectorAll("input[data-t]:checked")].map(x => x.dataset.t);
      if (!picked.length) { t.checked = true; return admMsg("Each person needs at least one look.", true); }
      const r = await admPost("/api/admin/themes", { user_id: +tr.dataset.u, themes: picked }); admMsg("✅ Looks saved.");
      if (+tr.dataset.u === ME.id) { ME.themes = r.themes; applyThemes(); } return; }
    if (ADM.page === "reports" && t.dataset.sr) { const roles = [...tr.querySelectorAll("[data-sr]:checked")].map(c => c.dataset.sr);
      await admPost(`/api/admin/rbac/skills/${encodeURIComponent(tr.dataset.s)}`, { roles }); admMsg("✅ Report access saved."); return admGo("reports", true); }
  } catch (err) { admMsg("⚠️ " + err.message, true); admGo(ADM.page, true); }
});
$("#admCon").addEventListener("input", e => { if (e.target.id === "admQ") { ADM.q = e.target.value; admFilter(); } });
$("#admCon").addEventListener("submit", async e => {
  e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
  try {
    if (e.target.id === "admNewUser") { await admPost("/api/admin/rbac/users", f); admMsg(`✅ ${f.name} created – login ${f.username.toUpperCase()}.`); return admGo("users", true); }
    if (e.target.id === "admPw") { if (f.password !== f.password2) return admMsg("The two passwords are not the same.", true);
      const u = ADM.rb.users.find(x => x.id === +e.target.dataset.id);
      await admPost(`/api/admin/rbac/users/${u.id}/login`, { username: f.username, password: f.password }); admMsg(`✅ Login saved for ${u.name}.`); return admGo("users", true); }
  } catch (err) { admMsg("⚠️ " + err.message, true); }
});
$("#admBtn").onclick = () => openAdmin();
$("#admOpen2").onclick = () => openAdmin();
$("#logoutBtn").onclick = async () => {
  try { await api("/api/logout", { method: "POST" }); } catch {}
  token = ""; store.set("rb_session", ""); $("#acct").close(); $("#log").innerHTML = ""; $("#skills").innerHTML = ""; showLogin();
};
$("#pwForm").addEventListener("submit", async e => {
  e.preventDefault(); $("#pwErr").textContent = "";
  try {
    await api("/api/change-password", { method: "POST", body: JSON.stringify({ old_password: $("#oldpw").value, new_password: $("#newpw").value }) });
    $("#oldpw").value = $("#newpw").value = ""; $("#acct").close();
    token = ""; store.set("rb_session", ""); $("#log").innerHTML = "";
    $("#loginHint").textContent = "Password changed. Sign in with your new password."; showLogin();
  } catch (err) { if (err.message !== "login") $("#pwErr").textContent = err.message; }
});
setTheme(QS.get("theme") || store.get("rb_theme") || "aurora");
(async () => {
  try { passwordMode = (await (await fetch("/api/auth-mode")).json()).password_required; } catch {}
  if (!passwordMode) {
    $("#pwFields").hidden = true; $("#tokFields").hidden = false; $("#user").required = $("#pass").required = false;
    $("#loginHint").textContent = "Enter the access token your admin gave you (or open your personal link).";
    if (urlToken) token = urlToken;
  }
  const GO_DASH = new URLSearchParams(location.search).get("go") === "dash";
async function goDash(){                // this tab was opened by the Dashboards button: fetch the signed link, then go
  document.body.innerHTML = '<div style="display:grid;place-items:center;height:100vh;font:600 15px Segoe UI,system-ui,sans-serif;color:#9fe3ff;background:#050b16">Opening dashboards…</div>';
  try { try { await api("/api/session-cookie", { method: "POST" }); } catch {}
    const r = await api("/api/dash-link", { method: "POST" }), n = new URLSearchParams(location.search).get("name") || "";
    let u = r.url.replace(/^https?:\/\/[^/]+/, ""); if (/^[a-z0-9-]+$/.test(n)) u = u.replace("/dash?", `/dash/${n}?`);
    location.replace(u);
  } catch (e) { document.body.firstChild.textContent = "⚠ " + (e.message === "login" ? "Please sign in to VERONICA first." : e.message); }
}
GO_DASH && token ? goDash() : token ? boot() : showLogin();
})();
</script>
</body>
</html>
