<script>
const $ = s => document.querySelector(s);
const store = { get(k){ try { return localStorage.getItem(k) } catch { return null } },
                set(k,v){ try { localStorage.setItem(k,v) } catch {} } };
let token = store.get("rb_session") || "";
let passwordMode = true, ME = null;
const urlToken = new URLSearchParams(location.search).get("token");
if (location.search.includes("token=")) history.replaceState(null, "", location.pathname);
const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------------- theme: Aurora (premium) | Arc (Iron-Man HUD) */
function setTheme(t){
  if (t === "nova") t = "holo";                                              // Nova look retired -> Holo
  t = ["arc", "holo", "forge", "titan", "atlas"].includes(t) ? t : "aurora";
  const allowed = typeof ME !== "undefined" && ME && Array.isArray(ME.themes) && ME.themes.length ? ME.themes.map(x => x === "nova" ? "holo" : x) : null;
  if (allowed && !allowed.includes(t)) t = allowed.includes("titan") ? "titan" : allowed[0];        // admin decides each user's looks
  document.body.classList.remove("theme-aurora", "theme-arc", "theme-holo", "theme-nova", "theme-forge", "theme-titan", "theme-atlas"); document.body.classList.add("theme-" + t);
  if (t === "nova" || t === "forge" || t === "titan" || t === "atlas") document.body.classList.add("theme-holo");
  if (t === "atlas") document.body.classList.add("theme-titan");               // Atlas builds on Titan's blue blueprint look   // Nova / Forge = the hologram workspace in their own colours
  document.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.theme === t));
  store.set("rb_theme", t); if (typeof Core !== "undefined") Core.theme(t);
  if (typeof Holo !== "undefined") Holo.theme(t);
  if (typeof HoloOS !== "undefined" && (t === "holo" || t === "nova" || t === "forge" || t === "titan" || t === "atlas")) HoloOS.boot();
}
document.querySelectorAll(".seg button").forEach(b => b.onclick = () => setTheme(b.dataset.theme));

/* ---------------- voice level -> animation (0..1) */
let VLVL = 0;
function setLvl(v){ VLVL = Math.max(0, Math.min(1.2, Number(v) - 1)); document.documentElement.style.setProperty("--lvl", VLVL.toFixed(3)); }

/* ================================================================ the living core (Aurora theme)
   ~1100 light particles in 3D. Shape + motion follow VERONICA's state:
   ready: breathing neural sphere with synapses · listening: sphere ripples with your voice (green)
   thinking: collapses into a fast data vortex (torus) with light trails · speaking: gold/cyan sound wave that pulses with her voice */
const Core = (() => {
  const cv = $("#core3d"), x = cv.getContext("2d");
  const N = innerWidth < 700 ? 620 : 1100;
  let W = 0, H = 0, dpr = 1, mode = "ready", t = 0, last = performance.now(), rotY = 0, theme = "aurora";
  const P = Array.from({ length: N }, (_, i) => ({ x: (Math.random() - .5) * 3, y: (Math.random() - .5) * 3, z: (Math.random() - .5) * 3,
                                                     gold: Math.random() < .07, s: Math.random() }));
  const G = Math.PI * (3 - Math.sqrt(5));
  const sphere = i => { const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = G * i; return [Math.cos(th) * r, y, Math.sin(th) * r]; };
  const BASE = P.map((_, i) => sphere(i));
  const PAIRS = []; for (let i = 0; i < N - 21; i += 5) PAIRS.push([i, i + 21], [i, i + 34]);
  const fit = () => { dpr = Math.min(devicePixelRatio || 1, 2); W = cv.clientWidth; H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr; };
  new ResizeObserver(fit).observe(cv); fit();
  function target(i, out){
    const b = BASE[i], p = P[i];
    if (mode === "thinking") {                       // torus vortex
      const u = (i / N) * Math.PI * 2 * 7 + t * 2.4, v = (i * G) % (Math.PI * 2);
      const R = .78, r = .26 + Math.sin(t * 3 + i) * .02;
      out[0] = (R + r * Math.cos(v)) * Math.cos(u); out[1] = r * Math.sin(v) * 1.1; out[2] = (R + r * Math.cos(v)) * Math.sin(u);
    } else if (mode === "speaking") {                // radial sound wave disc
      const a = (i / N) * Math.PI * 2 * 13, rr = Math.sqrt((i % 97) / 97) * 1.05 + .05;
      const amp = .08 + VLVL * .55;
      out[0] = Math.cos(a) * rr; out[2] = Math.sin(a) * rr;
      out[1] = Math.sin(rr * 9 - t * 7) * amp * (1.1 - rr * .6);
    } else {                                         // breathing sphere (listening reacts to the mic)
      const k = mode === "listening" ? 1 + VLVL * .35 + Math.sin(t * 9 + i * .3) * .03 * (1 + VLVL * 4)
                                     : 1 + Math.sin(t * 1.4) * .025 + Math.sin(t * 2.3 + p.s * 6) * .012;
      out[0] = b[0] * k; out[1] = b[1] * k; out[2] = b[2] * k;
    }
  }
  const tmp = [0, 0, 0], proj = new Float32Array(N * 3);
  const ARC = ["g1", "g2", "g3", "g4"].map(c => document.querySelector(".arc ." + c)), ARCV = [6, -13, 24, -3], arcA = [0, 0, 0, 0];
  const arcGlow = document.querySelector(".arc .coreglow");
  function arcFrame(dt){                                  // Arc theme: spin the reactor rings, faster while thinking
    const k = mode === "thinking" ? 5 : mode === "speaking" ? 1.6 : 1;
    ARC.forEach((g, i) => { if (!g) return; arcA[i] = (arcA[i] + ARCV[i] * k * dt) % 360; g.setAttribute("transform", `rotate(${arcA[i].toFixed(2)})`); });
    if (arcGlow) arcGlow.setAttribute("transform", `scale(${(1 + VLVL * .4 + (mode === "thinking" ? Math.sin(t * 12) * .05 : Math.sin(t * 2) * .03)).toFixed(3)})`);
  }
  function frame(now){
    const dt = Math.min(.05, (now - last) / 1000); last = now;
    if (!document.hidden && theme === "arc") { t += dt; arcFrame(dt); }
    if (!document.hidden && W > 0 && theme === "aurora" && cv.offsetParent !== null) {
      t += dt;
      const busy = mode === "thinking";
      rotY += dt * (busy ? 1.3 : mode === "speaking" ? .35 : .22);
      const tilt = mode === "speaking" ? .95 : .32 + Math.sin(t * .3) * .08;
      const cy = Math.cos(rotY), sy = Math.sin(rotY), cx = Math.cos(tilt), sx = Math.sin(tilt);
      const R = Math.min(W, H) * (mode === "speaking" ? .4 : .34), ox = W / 2, oy = H / 2 - 10;
      x.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (busy) { x.globalCompositeOperation = "destination-out"; x.fillStyle = "rgba(0,0,0,.28)"; x.fillRect(0, 0, W, H); }
      else x.clearRect(0, 0, W, H);
      x.globalCompositeOperation = "lighter";
      // core glow
      const glow = x.createRadialGradient(ox, oy, 0, ox, oy, R * 1.25);
      const red = document.body.classList.contains("denied");                   // access denied: the core turns red
      const gc = red ? "255,70,90" : mode === "listening" ? "69,209,155" : mode === "speaking" ? "215,179,106" : "98,200,255";
      glow.addColorStop(0, `rgba(${gc},${.18 + VLVL * .25})`); glow.addColorStop(.5, `rgba(${gc},.05)`); glow.addColorStop(1, "rgba(0,0,0,0)");
      x.fillStyle = glow; x.beginPath(); x.arc(ox, oy, R * 1.25, 0, 7); x.fill();
      const ease = busy ? .09 : .055;
      for (let i = 0; i < N; i++) {
        const p = P[i]; target(i, tmp);
        p.x += (tmp[0] - p.x) * ease; p.y += (tmp[1] - p.y) * ease; p.z += (tmp[2] - p.z) * ease;
        const X1 = p.x * cy - p.z * sy, Z1 = p.x * sy + p.z * cy;
        const Y2 = p.y * cx - Z1 * sx, Z2 = p.y * sx + Z1 * cx;
        const f = 1 / (1.9 - Z2 * .55);
        proj[i * 3] = ox + X1 * R * f * 1.6; proj[i * 3 + 1] = oy + Y2 * R * f * 1.6; proj[i * 3 + 2] = Z2;
      }
      // synapses (only when calm - looks like a neural mesh)
      if (mode === "ready" || mode === "listening") {
        x.lineWidth = .6;
        for (const [a, b] of PAIRS) {
          const za = proj[a * 3 + 2], zb = proj[b * 3 + 2]; if (za < 0 || zb < 0) continue;
          const dx = proj[a * 3] - proj[b * 3], dy = proj[a * 3 + 1] - proj[b * 3 + 1]; if (dx * dx + dy * dy > R * R * .06) continue;
          x.strokeStyle = red ? `rgba(255,90,110,${.08 + za * .1})` : `rgba(120,200,255,${.08 + za * .1})`; x.beginPath(); x.moveTo(proj[a * 3], proj[a * 3 + 1]); x.lineTo(proj[b * 3], proj[b * 3 + 1]); x.stroke();
        }
      }
      for (let i = 0; i < N; i++) {
        const z = proj[i * 3 + 2], a = .25 + (z + 1) * .32, sz = (.7 + (z + 1) * .75) * (P[i].gold ? 1.25 : 1);
        x.fillStyle = red ? (P[i].gold ? `rgba(255,190,120,${a})` : `rgba(255,95,115,${a})`) : P[i].gold ? `rgba(240,211,148,${a})` : mode === "listening" ? `rgba(120,240,200,${a})` : `rgba(140,215,255,${a})`;
        x.fillRect(proj[i * 3] - sz / 2, proj[i * 3 + 1] - sz / 2, sz, sz);
      }
      // orbit rings with travelling sparks
      for (let k = 0; k < 2; k++) {
        const rr = R * (1.32 + k * .16), sq = .28 + k * .08, ph = t * (k ? -.6 : .45) + k;
        x.strokeStyle = k ? "rgba(215,179,106,.22)" : "rgba(98,200,255,.22)"; x.lineWidth = 1;
        x.beginPath(); x.ellipse(ox, oy, rr, rr * sq, k ? -.35 : .25, 0, Math.PI * 2); x.stroke();
        const ex = ox + Math.cos(ph) * rr, ey = oy + Math.sin(ph) * rr * sq;
        const rot = k ? -.35 : .25, px = ox + (ex - ox) * Math.cos(rot) - (ey - oy) * Math.sin(rot), py = oy + (ex - ox) * Math.sin(rot) + (ey - oy) * Math.cos(rot);
        x.fillStyle = k ? "rgba(240,211,148,.95)" : "rgba(200,240,255,.95)"; x.beginPath(); x.arc(px, py, 2.2, 0, 7); x.fill();
      }
      x.globalCompositeOperation = "source-over";
    }
    if (!REDUCE) requestAnimationFrame(frame); else setTimeout(() => requestAnimationFrame(frame), 33);   // calm motion (e.g. Remote Desktop): slow, never blank
  }
  requestAnimationFrame(frame);
  return { set(m){ mode = m; }, theme(th){ theme = th; if (th === "aurora") fit(); } };
})();

/* ---------------- clock */
const tickClock = () => { $("#clock").textContent = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }); };
tickClock(); setInterval(tickClock, 15000);

/* ---------------- helpers */
async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", Authorization: "Bearer " + token, ...(opts.headers || {}) } });
  if (r.status === 401 && !path.startsWith("/api/login")) { token = ""; store.set("rb_session", ""); showLogin(); throw new Error("login"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function showLogin(){ $("#login").style.display = "grid"; setTimeout(() => (passwordMode ? $("#user") : $("#tok")).focus(), 50); }
function esc(s){ return String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function md(s){ return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>"); }
const inr = v => typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : esc(v);
const kfmt = k => k.format === "percent" ? inr(k.value) + "%" : k.format === "currency" ? "₹" + inr(k.value) : inr(k.value);
const fileUrl = u => { const m = String(u || "").match(/\/files\/[A-Za-z0-9]+\/[^#]+/); return m ? m[0] : u; };   // keep ?e=&s= (signed link)
const icon = { excel: "📊", pdf: "📄", html: "🌐", chart: "📈", dashboard: "🖥️", data: "🗂️" };
const fileLink = (f, label) => { const dl = ["excel", "data", "pdf"].includes(f.format);
  return `<a class="file" href="${esc(fileUrl(f.url))}" ${dl ? `download="${esc(f.filename || "")}"` : 'target="_blank" rel="noopener"'}>${icon[f.format] || "📎"} ${esc(label || f.filename)}</a>`; };
const when = s => { const d = new Date(String(s).replace(" ", "T")); return isNaN(d) ? s : d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); };
const STATES = { ready: "Ready", listening: "Listening", thinking: "Thinking", speaking: "Speaking" };
function setState(st){
  for (const k of ["listening", "speaking", "busy"]) document.body.classList.remove(k);
  if (st === "thinking") document.body.classList.add("busy"); else if (st !== "ready") document.body.classList.add(st);
  $("#aiState").textContent = STATES[st] || "Ready";
  $("#talkState").textContent = { listening: "Listening…", thinking: "Thinking…", speaking: "Speaking…" }[st] || "Ready";
  const ds = $("#dockState"); if (ds) ds.textContent = { listening: "Listening…", thinking: "Analysing…", speaking: "Speaking · Esc to stop" }[st] || "Online";
  const ct = $("#codeTag"); if (ct) ct.textContent = st === "thinking" ? "processing" : st === "ready" ? "idle" : st;
  Core.set(st === "busy" ? "thinking" : st);
}
const setBusy = b => setState(b ? "thinking" : "ready");
function chatMode(on){ if (on) { if (View.mode === "home") View.set("full", { greet: false }); } else View.set("home"); }
function add(cls, html){ const d = document.createElement("div"); d.className = "msg " + cls; d.innerHTML = html;
  $("#log").appendChild(d); $("#log").scrollTop = $("#log").scrollHeight; return d; }
const countUp = (el, to, fmt, ms = 900) => { if (REDUCE || typeof to !== "number") { el.textContent = fmt(to); return; }
  const t0 = performance.now(); const step = now => { const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(to * e); if (k < 1) requestAnimationFrame(step); else el.textContent = fmt(to); }; requestAnimationFrame(step); };

/* ---------------- KPI cards */
const KI = {
  scrap: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 1 21h22zm0 5 7.5 12h-15zM11 10v4h2v-4zm0 5v2h2v-2z"/></svg>',
  prod: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M2 21V10l6 3V10l6 3V4h3v4h2V4h3v17z"/></svg>',
  qty: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 3 7v10l9 5 9-5V7zm0 2.3L18.6 8 12 11.7 5.4 8zM5 9.7l6 3.4v6.6l-6-3.4zm8 10V13l6-3.4v6.7z"/></svg>',
  count: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 4h16v4H4zm0 6h16v4H4zm0 6h10v4H4z"/></svg>',
  money: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 3h12v2h-4.3c.6.6 1 1.3 1.2 2H18v2h-3.1c-.5 2.2-2.4 3.8-4.9 4l5.6 6h-2.8l-5.6-6H6v-2h3.3c1.5 0 2.7-.8 3.2-2H6V7h6.5c-.5-1.2-1.7-2-3.2-2H6z"/></svg>',
  pct: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7.5 11a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7zm9 9a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7zM5.4 20 17 4h1.6L7 20z"/></svg>',
};
function kIcon(k){ const l = (k.label || "").toLowerCase();
  if (/scrap|reject|loss|rejection|rejp/.test(l)) return KI.scrap;
  if (k.format === "currency" || /₹|amount|value|sales|rs\b/.test(l)) return KI.money;
  if (k.format === "percent" || /%/.test(l)) return KI.pct;
  if (/prod|output|dispatch|inspection|mt\b/.test(l)) return KI.prod;
  if (/count|cards|orders|jobs|no\./.test(l)) return KI.count;
  return KI.qty; }
function kDelta(k){
  if (typeof k.previous !== "number" || typeof k.value !== "number") return { txt: "", st: k.status || "" };
  const d = k.value - k.previous, arrow = d > 0 ? "▲" : d < 0 ? "▼" : "■";
  const txt = (k.format === "percent" ? `${arrow} ${Math.abs(d).toFixed(2)} pts` : k.previous ? `${arrow} ${(Math.abs(d) / Math.abs(k.previous) * 100).toFixed(1)}%` : "new")
              + " " + (k.previous_label || "vs previous");
  const st = k.status || (!k.better || d === 0 ? "" : ((d > 0) === (k.better === "up") ? "good" : "bad"));
  return { txt, st };
}
function kpiCard(k){
  const v = kfmt(k), L = v.length > 13 ? " xlong" : v.length > 10 ? " long" : "";
  const { txt, st } = kDelta(k);
  let bar = "";
  if (typeof k.target === "number" && k.target) { const pct = Math.max(0, Math.min(100, k.value / k.target * 100));
    bar = `<div class="bar"><i style="width:${pct.toFixed(0)}%"></i></div><div class="tg">Target ${esc(kfmt({ ...k, value: k.target }))}${k.unit ? " " + esc(k.unit) : ""}</div>`; }
  return `<div class="kc ${st}"><div class="kt"><span class="ic">${kIcon(k)}</span><span>${esc(k.label)}</span></div>
    <div class="val${L}">${v}${k.unit ? `<small>${esc(k.unit)}</small>` : ""}</div>
    ${txt ? `<span class="chg ${st}">${esc(txt)}</span>` : ""}${bar}${k.note ? `<div class="note">${esc(k.note)}</div>` : ""}</div>`;
}
function kpiGrid(kpis){ let h = "", g = null;
  for (const k of kpis) { if (k.group && k.group !== g) { g = k.group; h += `<div class="kgroup">${esc(g)}</div>`; } h += kpiCard(k); }
  return `<div class="kpis">${h}</div>`; }

function renderReply(r, el){
  let h = "";
  if ((r.kpis || []).length) h += kpiGrid(r.kpis);
  h += `<div class="bt">${md(r.text || "")}</div>`;
  for (const p of r.preview || []) {
    const numeric = p.columns.map((_, i) => i > 0 && p.rows.length && p.rows.every(row => row[i] == null || row[i] === "" || typeof row[i] === "number"));
    h += `<div class="tbl"><b>${esc(p.title)}</b><table><thead><tr>${p.columns.map((c, i) => `<th${numeric[i] ? ' style="text-align:right"' : ""}>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
      p.rows.map(row => { const grp = row.length > 1 && row.slice(1).every(v => v === null);
        if (grp) return `<tr class="grp"><td colspan="${row.length}">${esc(row[0])}</td></tr>`;
        const tot = String(row[0]).trim().startsWith("Total") || String(row[0]).trim() === "TOTAL";
        return `<tr${tot ? ' class="tot"' : ""}>${row.map((v, i) => `<td class="${numeric[i] ? "n" : ""}" style="white-space:pre">${inr(v)}</td>`).join("")}</tr>`; }).join("") + "</tbody></table></div>";
  }
  for (const f of (r.files || []).filter(f => f.format === "chart")) h += `<img class="chart" src="${esc(fileUrl(f.url))}" alt="Chart">`;
  const files = (r.files || []).filter(f => f.format !== "chart");
  if (files.length) h += `<div class="files">${files.map(f => fileLink(f)).join("")}</div>`;
  if ((r.suggestions || []).length) h += `<div class="qchips">${r.suggestions.map(q => `<button class="qchip" type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>`;
  h += `<div class="meta">${r.seconds ? `<span>⚡ answered in ${r.seconds} s</span>` : ""}${r.text ? '<button class="say" type="button">🔊 Listen</button>' : ""}</div>`;
  if (el) { el.className = "msg bot"; el.innerHTML = h; } else el = add("bot", h);
  const b = el.querySelector(".say"); if (b) b.onclick = () => Voice.say(r.text);
  $("#log").scrollTop = $("#log").scrollHeight;
  return el;
}

/* ---------------- Activity: every step of the current answer, live */
const Activity = {
  t0: 0,
  begin(q){ this.t0 = performance.now(); $("#trace").innerHTML = ""; $("#actMeta").textContent = "working…"; },
  step(ev){
    const box = $("#trace"); box.querySelector(".empty")?.remove();
    let row = box.querySelector(`.st[data-id="${CSS.escape(ev.id)}"]`);
    if (!row) { row = document.createElement("div"); row.className = "st"; row.dataset.id = ev.id;
      row.innerHTML = `<span class="d"></span><div><b></b><small></small></div><em>…</em>`; box.appendChild(row); }
    if (ev.label) row.querySelector("b").textContent = ev.label;
    if (ev.detail) row.querySelector("small").textContent = ev.detail;
    if (ev.status === "done" || ev.status === "error") { row.classList.add(ev.status); row.querySelector("em").textContent = ((ev.ms || 0) / 1000).toFixed(1) + " s"; }
    box.scrollTop = box.scrollHeight;
    codeFx.push(ev.status === "running" ? `▸ ${ev.name || ev.id}()` : `  ✓ ${(ev.name || ev.id)} ${((ev.ms || 0) / 1000).toFixed(1)}s ${ev.detail || ""}`);
  },
  note(txt){ if (!txt) return; this.step({ id: "n" + Math.random(), label: txt.split("\n")[0].slice(0, 70), status: "done", ms: 0 }); },
  end(sec){ $("#actMeta").textContent = sec ? `${sec} s total` : "done"; },
};
/* old Live-voice tool messages use trace() */
function trace(m){ Activity.step({ id: "live-" + m.name, name: m.name, label: ({ get_company_data: "Data lookup", latest_numbers: "Latest numbers", list_reports: "Report list" })[m.name] || m.name,
  status: m.status === "running" ? "running" : m.status, ms: m.ms, detail: m.args && m.args.question ? m.args.question.slice(0, 60) : "" }); }

/* ---------------- Latest analysis: figures appear the moment they are read, tagged with their source report */
const Analysis = {
  items: (() => { try { return JSON.parse(store.get("rb_analysis") || "[]"); } catch { return []; } })(),
  add(f){
    if (typeof f.value !== "number") return;
    this.items = [{ ...f, at: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) }, ...this.items.filter(x => !(x.label === f.label && x.group === f.group && x.source === f.source))].slice(0, 7);
    store.set("rb_analysis", JSON.stringify(this.items)); this.render(true);
  },
  render(anim){
    const box = $("#analysis"); if (!this.items.length) return;
    box.innerHTML = this.items.map((f, i) => { const { txt, st } = kDelta(f);
      return `<div class="an"><div class="l">${esc(f.label)}${f.group && f.group !== "Overall" ? ` · <span class="muted">${esc(f.group)}</span>` : ""}</div>
        <div class="v ${st}"><span class="vv">${kfmt(f)}</span>${f.unit ? ` <small class="muted">${esc(f.unit)}</small>` : ""}</div>
        ${txt ? `<div class="c"><span class="chg ${st}">${esc(txt)}</span></div>` : ""}<div class="s">from ${esc(f.source || "live query")} · ${esc(f.at || "")}</div></div>`; }).join("");
    const f = this.items[0], el = box.querySelector(".vv");
    if (anim && el && typeof f.value === "number") countUp(el, f.value, v => kfmt({ ...f, value: Math.round(v * 100) / 100 }));
  },
};

/* ---------------- send: streams steps, figures and the answer text as it is written */
async function send(text, opts = {}){
  if (typeof Attach !== "undefined") { for (let i = 0; Attach.pending && i < 120; i++) await new Promise(r => setTimeout(r, 250)); }
  const files = typeof Attach !== "undefined" ? Attach.take() : [];
  if (!text.trim() && !files.length) return;
  if (!text.trim()) text = files.length > 1 ? "Please analyse the attached files" : "Please analyse the attached file";
  chatMode(true);
  add("me", (opts.spoken ? "🎙️ " : "") + esc(text) + (files.length ? `<div class="attsent">${files.map(f => `<span>${Attach.icon(f.kind)} ${esc(f.name)}</span>`).join("")}</div>` : ""));
  const attIds = files.map(f => f.id);
  codeFx.push(`▸ ask(${JSON.stringify(text.slice(0, 46))})`);
  Activity.begin(text);
  const live = add("bot typing", `<div class="thinking"><span class="sp1"></span><span id="thinkTxt">Understanding your request…</span></div>`);
  setBusy(true);
  const ackTimer = opts.spoken ? setTimeout(() => Voice.ack(text), 1400) : 0;
  let r = null, buf = "", gotFigure = false;
  const paint = () => { live.innerHTML = `<div class="bt">${md(buf)}<span class="cursor"></span></div>`; $("#log").scrollTop = $("#log").scrollHeight; };
  try {
    const res = await fetch("/api/chat/stream", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
                                                 body: JSON.stringify({ message: text, voice: !!opts.spoken, attachments: attIds }) });
    if (res.status === 401) { token = ""; store.set("rb_session", ""); showLogin(); throw new Error("login"); }
    if (!res.ok || !res.body) throw new Error("nostream");
    const rd = res.body.getReader(), dec = new TextDecoder(); let pend = "";
    for (;;) {
      const { value, done } = await rd.read(); if (done) break;
      pend += dec.decode(value, { stream: true });
      let i;
      while ((i = pend.indexOf("\n\n")) >= 0) {
        const chunk = pend.slice(0, i); pend = pend.slice(i + 2);
        const line = chunk.split("\n").find(l => l.startsWith("data: ")); if (!line) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "text") { buf += ev.delta; paint(); }
        else if (ev.type === "text_reset") { Activity.note(ev.note); buf = ""; live.innerHTML = `<div class="thinking"><span class="sp1"></span><span>Working on it…</span></div>`; }
        else if (ev.type === "step") { Activity.step(ev); if (ev.status === "running" && !buf) { const tt = live.querySelector(".thinking span:last-child"); if (tt) tt.textContent = (ev.label || "Working") + "…"; } }
        else if (ev.type === "figure") { gotFigure = true; Analysis.add(ev); }
        else if (ev.type === "reply") r = ev;
        else if (ev.type === "error") throw new Error(ev.message);
      }
    }
    if (!r) throw new Error("nostream");
  } catch (e) {
    if (e.message === "login") { live.remove(); clearTimeout(ackTimer); setBusy(false); return; }
    if (e.message === "nostream" && !r) {                // older server or a proxy that blocks streaming: normal request
      try { r = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text, voice: !!opts.spoken, attachments: attIds }) }); }
      catch (e2) { r = null; live.className = "msg bot"; live.innerHTML = `<div class="bt">⚠️ ${esc(e2.message)}</div>`; }
    } else if (!r) { live.className = "msg bot"; live.innerHTML = `<div class="bt">⚠️ ${esc(e.message)}</div>`; }
  } finally { clearTimeout(ackTimer); setBusy(false); }
  if (r) {
    renderReply(r, live); Activity.end(r.seconds);
    if (!gotFigure) for (const k of (r.kpis || []).slice(0, 4)) Analysis.add({ ...k, source: "this answer" });
    loadDashboard();
    if (r.text && (opts.spoken || Voice.speakAll)) await Voice.say(r.text);
  }
}

/* ---------------- attach files: 📎 button, drag & drop anywhere, or paste - uploaded at once, sent with the next question */
const Attach = (() => {
  let list = [];
  const box = $("#atts"), inp = $("#fileIn");
  const ICON = { table: "📊", pdf: "📄", image: "🖼️", text: "📝" };
  const kb = n => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
  const info = f => f.kind === "table" ? (f.sheets || []).reduce((a, s) => a + s.rows, 0).toLocaleString("en-IN") + " rows · " + kb(f.size)
    : f.kind === "pdf" ? (f.pages ? f.pages + " pages · " : "") + kb(f.size) : kb(f.size);
  function draw(){
    if (!box) return; box.hidden = !list.length;
    box.innerHTML = list.map((f, i) => `<span class="att ${f.state || ""}" data-i="${i}"><i>${ICON[f.kind] || "📎"}</i><b>${esc(f.name)}</b>
      <em>${f.state === "up" ? "uploading…" : f.state === "err" ? esc(f.err) : esc(info(f))}</em><button type="button" class="ax" aria-label="Remove ${esc(f.name)}">✕</button></span>`).join("");
  }
  async function addFiles(files){
    chatMode(true);
    for (const file of [...files].slice(0, 5)) {
      const f = { name: file.name, size: file.size, state: "up" }; list.push(f); draw();
      try {
        const fd = new FormData(); fd.append("file", file);
        const r = await fetch("/api/upload", { method: "POST", headers: { Authorization: "Bearer " + token }, body: fd });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || "Upload failed");
        Object.assign(f, j, { state: "" });
        if (typeof HoloOS !== "undefined") HoloOS.scan(f);
      } catch (e) { f.state = "err"; f.err = e.message; }
      draw();
    }
    $("#t").focus();
  }
  if (box) box.onclick = e => { const b = e.target.closest(".ax"); if (b) { list.splice(+b.closest(".att").dataset.i, 1); draw(); } };
  $("#clip") && ($("#clip").onclick = () => inp.click());
  if (inp) inp.onchange = () => { addFiles(inp.files); inp.value = ""; };
  let depth = 0; const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
  addEventListener("dragenter", e => { if (hasFiles(e)) { depth++; document.body.classList.add("dropping"); } });
  addEventListener("dragleave", e => { if (hasFiles(e) && --depth <= 0) { depth = 0; document.body.classList.remove("dropping"); } });
  addEventListener("dragover", e => { if (hasFiles(e)) e.preventDefault(); });
  addEventListener("drop", e => { if (!e.dataTransfer?.files?.length) return; e.preventDefault(); depth = 0; document.body.classList.remove("dropping"); addFiles(e.dataTransfer.files); });
  $("#t").addEventListener("paste", e => { const fs = [...(e.clipboardData?.files || [])]; if (fs.length) { e.preventDefault(); addFiles(fs); } });
  return { take(){ const ok = list.filter(f => f.id && !f.state); list = []; draw(); return ok; },
           get pending(){ return list.some(f => f.state === "up"); }, icon: k => ICON[k] || "📎", add: addFiles };
})();

/* ---------------- recent reports (Reports dialog) */
async function loadDashboard(){
  let d; try { d = await api("/api/dashboard"); } catch { return; }
  $("#recent").innerHTML = d.recent.map(r => `<button class="rep" type="button" data-id="${r.id}"><b>${esc(r.title)}</b><span>${esc(when(r.created_at))}${r.skill ? " · /" + esc(r.skill) : ""}</span></button>`).join("") || `<div class="empty">No reports yet.</div>`;
  $("#recent").onclick = e => { const b = e.target.closest(".rep"); if (b) { repDlg.close(); send(`Show report #${b.dataset.id} again (same format)`); } };
}

/* ---------------- left panel: pure JARVIS motion graphics (no text) - radar · holo globe · voice scope
   They react to VERONICA: faster while thinking, gold while speaking, green while listening. */
const HudFx = (() => {
  const C = id => { const c = document.getElementById(id); return c ? { c, x: c.getContext("2d"), w: 0, h: 0 } : null; };
  const R = C("hudRadar"), Gb = C("hudGlobe"), Wv = C("hudWave"), Nt = C("hudNet"), all = [R, Gb, Wv, Nt].filter(Boolean);
  let dpr = 1, t = 0, last = performance.now(), col = {};
  const fit = () => { dpr = Math.min(devicePixelRatio || 1, 2); for (const k of all) { k.w = k.c.clientWidth; k.h = k.c.clientHeight; k.c.width = k.w * dpr; k.c.height = k.h * dpr; } };
  const ro = new ResizeObserver(fit); all.forEach(k => ro.observe(k.c)); fit();
  const readCol = () => { const cs = getComputedStyle(document.body); col = { ac: cs.getPropertyValue("--ac").trim() || "#62c8ff", gold: cs.getPropertyValue("--gold").trim() || "#d7b36a",
    good: cs.getPropertyValue("--good").trim() || "#45d19b" }; };
  readCol(); new MutationObserver(readCol).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  const rgba = (hex, a) => { const h = hex.replace("#", ""), n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };
  const mode = () => document.body.classList.contains("busy") ? "busy" : document.body.classList.contains("speaking") ? "speak" : document.body.classList.contains("listening") ? "listen" : "idle";
  const main = () => { const m = mode(); return m === "speak" ? col.gold : m === "listen" ? col.good : col.ac; };
  const blips = [];
  function radar(k, sp){
    const { x, w, h } = k, cx = w / 2, cy = h / 2, r = Math.min(w, h) * .42, c = main();
    x.lineWidth = 1;
    for (let i = 1; i <= 4; i++) { x.strokeStyle = rgba(c, .1 + i * .03); x.beginPath(); x.arc(cx, cy, r * i / 4, 0, 7); x.stroke(); }
    x.strokeStyle = rgba(c, .12); x.beginPath(); x.moveTo(cx - r, cy); x.lineTo(cx + r, cy); x.moveTo(cx, cy - r); x.lineTo(cx, cy + r); x.stroke();
    for (let i = 0; i < 72; i++) { const a = i / 72 * Math.PI * 2 + t * .05, l = i % 6 ? 4 : 9;
      x.strokeStyle = rgba(c, i % 6 ? .25 : .55); x.beginPath(); x.moveTo(cx + Math.cos(a) * (r + 6), cy + Math.sin(a) * (r + 6)); x.lineTo(cx + Math.cos(a) * (r + 6 + l), cy + Math.sin(a) * (r + 6 + l)); x.stroke(); }
    const sa = t * 1.4 * sp;
    const g = x.createConicGradient ? x.createConicGradient(sa - 1.1, cx, cy) : null;
    if (g) { g.addColorStop(0, rgba(c, 0)); g.addColorStop(.17, rgba(c, .32)); g.addColorStop(.175, rgba(c, 0)); x.fillStyle = g; x.beginPath(); x.arc(cx, cy, r, 0, 7); x.fill(); }
    x.strokeStyle = rgba(c, .9); x.lineWidth = 1.5; x.beginPath(); x.moveTo(cx, cy); x.lineTo(cx + Math.cos(sa) * r, cy + Math.sin(sa) * r); x.stroke();
    if (Math.random() < .04 * sp) { const a = sa - .05, d = r * (.2 + Math.random() * .75); blips.push({ x: cx + Math.cos(a) * d, y: cy + Math.sin(a) * d, life: 1 }); }
    for (let i = blips.length - 1; i >= 0; i--) { const b = blips[i]; b.life -= .006 * sp; if (b.life <= 0) { blips.splice(i, 1); continue; }
      x.fillStyle = rgba(c, b.life); x.beginPath(); x.arc(b.x, b.y, 2.2, 0, 7); x.fill();
      x.strokeStyle = rgba(c, b.life * .5); x.beginPath(); x.arc(b.x, b.y, 2 + (1 - b.life) * 10, 0, 7); x.stroke(); }
    x.strokeStyle = rgba(col.gold, .7); x.lineWidth = 2.5;
    x.beginPath(); x.arc(cx, cy, r * .78, -t * .6 * sp, -t * .6 * sp + .9); x.stroke();
    x.beginPath(); x.arc(cx, cy, r * .55, t * .9 * sp, t * .9 * sp + .5); x.stroke();
    x.fillStyle = rgba(c, .9); x.beginPath(); x.arc(cx, cy, 2.5, 0, 7); x.fill();
  }
  const links = Array.from({ length: 7 }, () => ({ a: [Math.random() * 6.28, Math.random() * 2.4 - 1.2], b: [Math.random() * 6.28, Math.random() * 2.4 - 1.2], p: Math.random() }));
  function globe(k, sp){
    const { x, w, h } = k, cx = w / 2, cy = h / 2, r = Math.min(w, h) * .36, c = main(), rot = t * .35 * sp, tilt = .38;
    const P = (lon, lat) => { const X = Math.cos(lat) * Math.cos(lon + rot), Y = Math.sin(lat), Z = Math.cos(lat) * Math.sin(lon + rot);
      const y2 = Y * Math.cos(tilt) - Z * Math.sin(tilt), z2 = Y * Math.sin(tilt) + Z * Math.cos(tilt); return [cx + X * r, cy - y2 * r, z2]; };
    const glow = x.createRadialGradient(cx, cy, r * .2, cx, cy, r * 1.3); glow.addColorStop(0, rgba(c, .14)); glow.addColorStop(1, rgba(c, 0));
    x.fillStyle = glow; x.beginPath(); x.arc(cx, cy, r * 1.3, 0, 7); x.fill();
    x.lineWidth = .8;
    for (let la = -60; la <= 60; la += 30) { x.beginPath(); for (let lo = 0; lo <= 360; lo += 8) { const [px, py, pz] = P(lo * Math.PI / 180, la * Math.PI / 180);
        x.strokeStyle = rgba(c, .22); lo ? x.lineTo(px, py) : x.moveTo(px, py); } x.stroke(); }
    for (let lo = 0; lo < 360; lo += 30) { for (let la = -90; la < 90; la += 6) { const [ax, ay, az] = P(lo * Math.PI / 180, la * Math.PI / 180), [bx, by] = P(lo * Math.PI / 180, (la + 6) * Math.PI / 180);
        x.strokeStyle = rgba(c, az > 0 ? .32 : .08); x.beginPath(); x.moveTo(ax, ay); x.lineTo(bx, by); x.stroke(); } }
    for (const L of links) { L.p += .004 * sp; if (L.p > 1.4) { L.p = 0; L.a = [Math.random() * 6.28, Math.random() * 2.4 - 1.2]; L.b = [Math.random() * 6.28, Math.random() * 2.4 - 1.2]; }
      const n = 24, upto = Math.min(1, L.p) * n; x.strokeStyle = rgba(col.gold, .75); x.lineWidth = 1.3; x.beginPath();
      for (let i = 0; i <= upto; i++) { const f = i / n, lon = L.a[0] + (L.b[0] - L.a[0]) * f, lat = L.a[1] + (L.b[1] - L.a[1]) * f;
        const [px, py, pz] = P(lon, lat), lift = 1 + Math.sin(f * Math.PI) * .25; const qx = cx + (px - cx) * lift, qy = cy + (py - cy) * lift;
        if (pz < -.2) { x.moveTo(qx, qy); continue; } i ? x.lineTo(qx, qy) : x.moveTo(qx, qy); }
      x.stroke();
      const [ex, ey, ez] = P(L.b[0], L.b[1]); if (L.p >= 1 && ez > 0) { x.strokeStyle = rgba(col.gold, 1.4 - L.p); x.beginPath(); x.arc(ex, ey, 3 + (L.p - 1) * 30, 0, 7); x.stroke(); } }
    x.strokeStyle = rgba(c, .35); x.lineWidth = 1; x.beginPath(); x.ellipse(cx, cy, r * 1.45, r * .42, -.3, 0, 7); x.stroke();
    const sa = t * .8 * sp, sx = cx + Math.cos(sa) * r * 1.45, sy = cy + Math.sin(sa) * r * .42, rx = cx + (sx - cx) * Math.cos(-.3) - (sy - cy) * Math.sin(-.3), ry = cy + (sx - cx) * Math.sin(-.3) + (sy - cy) * Math.cos(-.3);
    x.fillStyle = rgba(c, 1); x.beginPath(); x.arc(rx, ry, 2.6, 0, 7); x.fill();
  }
  /* left panel, third screen: a 4D hyper-cube (tesseract) turning inside a particle vortex.
     Its edges glow, the inner cube breathes with her voice, sparks race along the edges while she thinks;
     a ring of spectrum bars at the base reacts to voice. Gold while speaking, green while listening. */
  const V4 = []; for (let i = 0; i < 16; i++) V4.push([i & 1 ? 1 : -1, i & 2 ? 1 : -1, i & 4 ? 1 : -1, i & 8 ? 1 : -1]);
  const E4 = []; for (let i = 0; i < 16; i++) for (let j = i + 1; j < 16; j++) { const d = i ^ j; if (d && !(d & (d - 1))) E4.push([i, j]); }
  const motes = Array.from({ length: 90 }, () => ({ a: Math.random() * 6.28, r: .3 + Math.random() * .7, z: Math.random() * 2 - 1, s: .4 + Math.random() * .8 }));
  const sparks = [];
  const hist = new Array(64).fill(0);
  function voiceWave(k, sp){                       // Aurora / Arc: the original voice scope
    const { x, w, h } = k, m = mode(), c = main(), mid = h / 2;
    x.strokeStyle = rgba(c, .07); x.lineWidth = 1;
    const off = (t * 30 * sp) % 20; for (let gx = -off; gx < w; gx += 20) { x.beginPath(); x.moveTo(gx, 0); x.lineTo(gx, h); x.stroke(); }
    for (let gy = mid % 20; gy < h; gy += 20) { x.beginPath(); x.moveTo(0, gy); x.lineTo(w, gy); x.stroke(); }
    const amp = (m === "speak" || m === "listen" ? .25 + VLVL * .9 : m === "busy" ? .35 : .12) * h * .4;
    for (let L = 0; L < 3; L++) { x.strokeStyle = rgba(L === 1 ? col.gold : c, L === 0 ? .9 : .45); x.lineWidth = L === 0 ? 1.6 : 1; x.beginPath();
      for (let px = 0; px <= w; px += 3) { const f = px / w, env = Math.sin(f * Math.PI);
        const y = mid + Math.sin(f * (10 + L * 4) + t * (3 + L) * sp) * amp * env * (1 - L * .25) + Math.sin(f * 37 - t * 7) * amp * .15 * env;
        px ? x.lineTo(px, y) : x.moveTo(px, y); } x.stroke(); }
    hist.push(amp / (h * .4) * (.6 + Math.random() * .6)); hist.shift();
    const bw = w / hist.length; for (let i = 0; i < hist.length; i++) { const bh = Math.max(2, hist[i] * h * .22);
      x.fillStyle = rgba(c, .14 + hist[i] * .3); x.fillRect(i * bw + 1, h - 8 - bh, bw - 2, bh); x.fillRect(i * bw + 1, 8, bw - 2, bh * .6); }
  }
  const wave = (k, sp) => document.body.classList.contains("theme-holo") ? tess(k, sp) : voiceWave(k, sp);
  function tess(k, sp){
    const { x, w, h } = k, c = main(), m = mode(), cx = w / 2, cy = h * .46, S = Math.min(w, h) * .2;
    const a1 = t * .45 * sp, a2 = t * .31 * sp, a3 = t * .22 * sp, breathe = 1 + VLVL * .35 + Math.sin(t * 2) * .03;
    // vortex of motes spiralling round the cube
    for (const p of motes) { p.a += .006 * p.s * sp * (m === "busy" ? 2 : 1);
      const rr = p.r * S * 2.4, px = cx + Math.cos(p.a) * rr, py = cy + Math.sin(p.a) * rr * .34 + p.z * S * .6, near = Math.sin(p.a) > 0;
      x.fillStyle = rgba(near ? c : col.gold, near ? .55 : .2); x.beginPath(); x.arc(px, py, near ? 1.5 : 1, 0, 7); x.fill(); }
    // rotate in 4D (XW, YW planes) then 3D (XZ), project 4D->3D->2D
    const P = V4.map(([X, Y, Z, W]) => {
      let x1 = X * Math.cos(a1) - W * Math.sin(a1), w1 = X * Math.sin(a1) + W * Math.cos(a1);
      let y1 = Y * Math.cos(a2) - w1 * Math.sin(a2), w2 = Y * Math.sin(a2) + w1 * Math.cos(a2);
      let x2 = x1 * Math.cos(a3) - Z * Math.sin(a3), z2 = x1 * Math.sin(a3) + Z * Math.cos(a3);
      const k4 = 2.2 / (3 - w2) * (w2 > 0 ? breathe : 1), X3 = x2 * k4, Y3 = y1 * k4, Z3 = z2 * k4, k3 = 3 / (4 - Z3);
      return [cx + X3 * k3 * S, cy + Y3 * k3 * S, Z3, w2]; });
    // glow behind
    const g = x.createRadialGradient(cx, cy, 0, cx, cy, S * 2.2); g.addColorStop(0, rgba(c, .16 + VLVL * .2)); g.addColorStop(1, rgba(c, 0));
    x.fillStyle = g; x.beginPath(); x.arc(cx, cy, S * 2.2, 0, 7); x.fill();
    // edges: inner cube (w>0) brighter
    for (const [i, j] of E4) { const A = P[i], B = P[j], inner = A[3] > 0 && B[3] > 0, depth = (A[2] + B[2]) / 2;
      x.strokeStyle = rgba(inner ? col.gold : c, inner ? .85 : .35 + Math.max(0, depth) * .35); x.lineWidth = inner ? 1.6 : 1.1;
      x.beginPath(); x.moveTo(A[0], A[1]); x.lineTo(B[0], B[1]); x.stroke(); }
    for (const p of P) { const big = p[3] > 0; x.fillStyle = rgba(big ? col.gold : c, .95); x.beginPath(); x.arc(p[0], p[1], big ? 2.6 : 1.8, 0, 7); x.fill();
      if (big) { x.strokeStyle = rgba(col.gold, .3); x.beginPath(); x.arc(p[0], p[1], 6, 0, 7); x.stroke(); } }
    // sparks race along the edges (more while thinking)
    if (Math.random() < (m === "busy" ? .5 : .08)) sparks.push({ e: E4[Math.random() * E4.length | 0], f: 0, v: .02 + Math.random() * .03 });
    for (let i = sparks.length - 1; i >= 0; i--) { const s2 = sparks[i]; s2.f += s2.v * sp; if (s2.f >= 1) { sparks.splice(i, 1); continue; }
      const A = P[s2.e[0]], B = P[s2.e[1]], px = A[0] + (B[0] - A[0]) * s2.f, py = A[1] + (B[1] - A[1]) * s2.f;
      x.fillStyle = "rgba(255,255,255,.95)"; x.beginPath(); x.arc(px, py, 1.8, 0, 7); x.fill();
      x.fillStyle = rgba(c, .35); x.beginPath(); x.arc(px, py, 5, 0, 7); x.fill(); }
    // base: projector ellipse + ring of spectrum bars
    const by = h * .86, br = S * 1.9;
    x.strokeStyle = rgba(c, .5); x.lineWidth = 1; x.beginPath(); x.ellipse(cx, by, br, br * .16, 0, 0, 7); x.stroke();
    x.strokeStyle = rgba(c, .18); x.beginPath(); x.ellipse(cx, by, br * 1.25, br * .2, 0, 0, 7); x.stroke();
    const n = 48, live = m === "speak" || m === "listen";
    for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2 + t * .3, px = cx + Math.cos(a) * br, py = by + Math.sin(a) * br * .16;
      const v = (Math.sin(i * 1.7 + t * (live ? 9 : 2.5)) * .5 + .5) * (live ? .3 + VLVL * 1.2 : m === "busy" ? .6 : .25);
      x.strokeStyle = rgba(i % 4 ? c : col.gold, Math.sin(a) > 0 ? .8 : .3); x.lineWidth = 2;
      x.beginPath(); x.moveTo(px, py); x.lineTo(px, py - 4 - v * S * .7); x.stroke(); }
    // light beam from base to cube
    const bg = x.createLinearGradient(0, by, 0, cy); bg.addColorStop(0, rgba(c, .18)); bg.addColorStop(1, rgba(c, 0));
    x.fillStyle = bg; x.beginPath(); x.moveTo(cx - br * .35, by); x.lineTo(cx - S * 1.1, cy); x.lineTo(cx + S * 1.1, cy); x.lineTo(cx + br * .35, by); x.fill();
  }
  /* right panel: neural network + DNA helix of data + rotating hex reticle */
  const nodes = Array.from({ length: 26 }, () => ({ x: Math.random(), y: Math.random(), vx: (Math.random() - .5) * .02, vy: (Math.random() - .5) * .02, p: Math.random() * 6.28 }));
  const pulses = [];
  function net(k, sp){
    const { x, w, h } = k, c = main();
    // drifting nodes + links
    for (const n of nodes) { n.x += n.vx * .016 * sp; n.y += n.vy * .016 * sp; if (n.x < .04 || n.x > .96) n.vx *= -1; if (n.y < .06 || n.y > .94) n.vy *= -1; }
    const pts = nodes.map(n => [n.x * w, n.y * h]), md = Math.min(w, h) * .32;
    x.lineWidth = .8;
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]); if (d > md) continue;
      x.strokeStyle = rgba(c, (1 - d / md) * .28); x.beginPath(); x.moveTo(pts[i][0], pts[i][1]); x.lineTo(pts[j][0], pts[j][1]); x.stroke();
      if (Math.random() < .0016 * sp) pulses.push({ a: i, b: j, f: 0 }); }
    for (let i = pulses.length - 1; i >= 0; i--) { const P = pulses[i]; P.f += .02 * sp; if (P.f >= 1) { pulses.splice(i, 1); continue; }
      const A = pts[P.a], B = pts[P.b], px = A[0] + (B[0] - A[0]) * P.f, py = A[1] + (B[1] - A[1]) * P.f;
      x.fillStyle = rgba(col.gold, 1 - P.f * .5); x.beginPath(); x.arc(px, py, 2, 0, 7); x.fill(); }
    nodes.forEach((n, i) => { const g = .5 + .5 * Math.sin(t * 2 * sp + n.p); x.fillStyle = rgba(c, .35 + g * .5); x.beginPath(); x.arc(pts[i][0], pts[i][1], 1.6 + g * 1.4, 0, 7); x.fill(); });
    // DNA helix of data in the middle
    const cx = w / 2, amp = w * .16, n = 34, top = h * .08, step = (h * .84) / n;
    for (let i = 0; i < n; i++) { const y = top + i * step, ph = i * .42 + t * 1.6 * sp, s1 = Math.sin(ph), z = Math.cos(ph);
      const x1 = cx + s1 * amp, x2 = cx - s1 * amp;
      x.strokeStyle = rgba(c, .12 + Math.abs(z) * .18); x.lineWidth = 1; x.beginPath(); x.moveTo(x1, y); x.lineTo(x2, y); x.stroke();
      x.fillStyle = rgba(z > 0 ? c : col.gold, .45 + .5 * Math.abs(z)); x.beginPath(); x.arc(x1, y, 1.8 + (z > 0 ? 1.2 : 0), 0, 7); x.fill();
      x.fillStyle = rgba(z > 0 ? col.gold : c, .45 + .5 * Math.abs(z)); x.beginPath(); x.arc(x2, y, 1.8 + (z < 0 ? 1.2 : 0), 0, 7); x.fill(); }
    // hex reticle
    const R0 = Math.min(w, h) * .2, a0 = t * .4 * sp;
    for (let ring = 0; ring < 2; ring++) { const rr = R0 * (1 + ring * .32), a = ring ? -a0 * 1.3 : a0;
      x.strokeStyle = rgba(ring ? col.gold : c, ring ? .45 : .6); x.lineWidth = ring ? 1 : 1.4; x.beginPath();
      for (let i = 0; i <= 6; i++) { const q = a + i * Math.PI / 3, px = cx + Math.cos(q) * rr, py = h / 2 + Math.sin(q) * rr; i ? x.lineTo(px, py) : x.moveTo(px, py); }
      x.stroke();
      for (let i = 0; i < 6; i++) { const q = a + i * Math.PI / 3; x.fillStyle = rgba(ring ? col.gold : c, .9); x.beginPath(); x.arc(cx + Math.cos(q) * rr, h / 2 + Math.sin(q) * rr, 2, 0, 7); x.fill(); } }
    // scan line
    const sy = (t * 40 * sp) % (h + 40) - 20, sg = x.createLinearGradient(0, sy - 18, 0, sy + 2);
    sg.addColorStop(0, rgba(c, 0)); sg.addColorStop(1, rgba(c, .16)); x.fillStyle = sg; x.fillRect(0, sy - 18, w, 20);
  }
  /* ---------- TITAN side screens: UT wall-thickness scan · rotating tube with eddy-current coil ·
                nuclear fuel-tube bundle · aerospace turbine fan */
  const isTitan = () => document.body.classList.contains("theme-titan");
  const lab = (x, s, px, py, c, a = .75, size = 9, al = "left") => { x.font = `600 ${size}px "JetBrains Mono",monospace`; x.textAlign = al; x.fillStyle = rgba(c, a); x.fillText(s, px, py); };
  const wt = new Array(90).fill(0).map(() => .7 + Math.random() * .06);
  function utScan(k, sp){
    const { x, w, h } = k, cx = w / 2, cy = h / 2 + 6, R = Math.min(w, h) * .34, r = R * .74, c = main(), sa = t * 1.1 * sp;
    for (let i = 1; i <= 3; i++) { x.strokeStyle = rgba(c, .08); x.beginPath(); x.arc(cx, cy, R * (1 + i * .12), 0, 7); x.stroke(); }
    x.fillStyle = rgba(c, .08); x.beginPath(); x.arc(cx, cy, R, 0, 7); x.arc(cx, cy, r, 0, 7, true); x.fill();     // tube wall
    x.strokeStyle = rgba(c, .9); x.lineWidth = 1.6; x.beginPath(); x.arc(cx, cy, R, 0, 7); x.stroke();
    x.strokeStyle = rgba(c, .6); x.lineWidth = 1.2; x.beginPath(); x.arc(cx, cy, r, 0, 7); x.stroke();
    x.save(); x.beginPath(); x.arc(cx, cy, R, 0, 7); x.arc(cx, cy, r, 0, 7, true); x.clip();                       // hatch the wall
    x.strokeStyle = rgba(c, .18); x.lineWidth = 1; for (let d = -R * 2; d < R * 2; d += 6) { x.beginPath(); x.moveTo(cx + d, cy - R); x.lineTo(cx + d + R * 2, cy + R); x.stroke(); } x.restore();
    const i0 = Math.floor(((sa % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2) / (Math.PI * 2) * wt.length);
    wt[i0] = .68 + Math.random() * .1;
    for (let i = 0; i < wt.length; i++) { const a = i / wt.length * Math.PI * 2, v = (wt[i] - .6) * R * 1.6, r1 = R * 1.08;
      x.strokeStyle = rgba(i === i0 ? col.gold : c, i === i0 ? 1 : .45); x.lineWidth = 2;
      x.beginPath(); x.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); x.lineTo(cx + Math.cos(a) * (r1 + v), cy + Math.sin(a) * (r1 + v)); x.stroke(); }
    const px = cx + Math.cos(sa) * R * 1.02, py = cy + Math.sin(sa) * R * 1.02;                                       // probe + beam
    x.strokeStyle = rgba(col.gold, .9); x.lineWidth = 1.4; x.beginPath(); x.moveTo(px, py); x.lineTo(cx + Math.cos(sa) * r, cy + Math.sin(sa) * r); x.stroke();
    x.fillStyle = rgba(col.gold, 1); x.fillRect(px - 3, py - 3, 6, 6);
    x.strokeStyle = rgba(c, .25); x.beginPath(); x.moveTo(cx - R * 1.3, cy); x.lineTo(cx + R * 1.3, cy); x.moveTo(cx, cy - R * 1.3); x.lineTo(cx, cy + R * 1.3); x.stroke();
    lab(x, "UT WALL SCAN", 10, 16, c, .8); lab(x, `WT ${(7.11 + (wt[i0] - .73) * 2).toFixed(2)} mm`, w - 10, 16, col.gold, .9, 9, "right");
    lab(x, "OD 168.3 · ID 154.1", 10, h - 10, c, .55);
  }
  function tube3d(k, sp){
    const { x, w, h } = k, c = main(), cy = h / 2, L = w * .8, x0 = (w - L) / 2, rr = Math.min(h * .2, 34), rot = t * 1.4 * sp;
    const ex = (px) => rr * .34;                                                                                       // ellipse x-radius (perspective)
    x.lineWidth = 1;
    for (let j = 0; j < 10; j++) { const a = rot + j / 10 * Math.PI * 2, yy = cy + Math.sin(a) * rr, front = Math.cos(a) > 0;
      x.strokeStyle = rgba(c, front ? .55 : .15); x.beginPath(); x.moveTo(x0, yy); x.lineTo(x0 + L, yy); x.stroke(); }
    for (let i = 0; i <= 12; i++) { const px = x0 + i / 12 * L; x.strokeStyle = rgba(c, .28); x.beginPath(); x.ellipse(px, cy, ex(px), rr, 0, 0, 7); x.stroke(); }
    x.strokeStyle = rgba(c, .9); x.lineWidth = 1.5; x.beginPath(); x.ellipse(x0 + L, cy, ex(), rr, 0, 0, 7); x.stroke();
    x.beginPath(); x.ellipse(x0 + L, cy, ex() * .8, rr * .8, 0, 0, 7); x.stroke();
    const cxp = x0 + ((t * .18 * sp) % 1) * L;                                                                        // eddy-current coil sliding along
    for (let q = 0; q < 3; q++) { x.strokeStyle = rgba(col.gold, .9 - q * .25); x.lineWidth = 2; x.beginPath(); x.ellipse(cxp + q * 4, cy, ex() * 1.25, rr * 1.3, 0, 0, 7); x.stroke(); }
    const sg = x.createLinearGradient(cxp - 50, 0, cxp, 0); sg.addColorStop(0, rgba(col.gold, 0)); sg.addColorStop(1, rgba(col.gold, .18));
    x.fillStyle = sg; x.fillRect(Math.max(x0, cxp - 50), cy - rr, Math.min(50, cxp - x0), rr * 2);
    for (let i = 0; i < 40; i++) { const px = x0 + i / 40 * L, v = Math.sin(i * 1.9 + t * 3) * .5 + .5;              // signal trace
      x.fillStyle = rgba(px < cxp ? col.gold : c, px < cxp ? .7 : .2); x.fillRect(px, h - 14 - v * 10, L / 40 - 2, v * 10 + 2); }
    lab(x, "SEAMLESS TUBE · ECT / NDT", 10, 16, c, .8); lab(x, cxp < x0 + L * .98 ? "SCANNING…" : "PASS ✓", w - 10, 16, col.gold, .9, 9, "right");
  }
  function fuel(k, sp){                         // nuclear-grade tube bundle, top view - crisp lines (no blur), sized to fit
    const { x, w, h } = k, c = main(), top = 24, bot = 18, cx = Math.round(w / 2) + .5, cy = Math.round(top + (h - top - bot) / 2) + .5;
    const s = Math.max(4, Math.min((h - top - bot) / 2 / 6.4, w / 2 / 7.2)), pts = [];
    for (let q = -3; q <= 3; q++) for (let r = -3; r <= 3; r++) { const z = -q - r; if (Math.abs(z) > 3) continue;
      pts.push([Math.round(cx + s * 1.75 * (q + r / 2)) + .5, Math.round(cy + s * 1.52 * r) + .5, Math.max(Math.abs(q), Math.abs(r), Math.abs(z))]); }
    const a0 = t * .25 * sp;
    for (let ring = 0; ring < 2; ring++) { const R0 = s * (5.9 + ring * .5), a = ring ? -a0 : 0; x.strokeStyle = rgba(ring ? col.gold : c, ring ? .45 : .85); x.lineWidth = ring ? 1 : 1.5;
      if (ring) x.setLineDash([6, 5]); x.beginPath();
      for (let i = 0; i <= 6; i++) { const q2 = a + i * Math.PI / 3 + Math.PI / 6; i ? x.lineTo(cx + Math.cos(q2) * R0, cy + Math.sin(q2) * R0) : x.moveTo(cx + Math.cos(q2) * R0, cy + Math.sin(q2) * R0); }
      x.stroke(); x.setLineDash([]); }
    const wave = (t * 1.1 * sp) % 4.2;                                    // Cherenkov-blue pulse ring by ring
    for (const [px, py, d] of pts) { const glow = Math.max(0, 1 - Math.abs(d - wave) * 1.3);
      x.fillStyle = rgba(glow > .2 ? col.gold : c, .07 + glow * .35); x.beginPath(); x.arc(px, py, s * .78, 0, 7); x.fill();
      x.strokeStyle = rgba(glow > .2 ? col.gold : c, .7 + glow * .3); x.lineWidth = 1.3; x.beginPath(); x.arc(px, py, s * .78, 0, 7); x.stroke();
      x.strokeStyle = rgba(c, .45); x.lineWidth = 1; x.beginPath(); x.arc(px, py, s * .5, 0, 7); x.stroke();
      x.fillStyle = rgba(c, .9); x.fillRect(px - .5, py - .5, 1.5, 1.5); }
    const ax = w - 22, ay = 13; x.lineWidth = 1;
    for (let i = 0; i < 3; i++) { x.strokeStyle = rgba(col.gold, .8); x.beginPath(); x.ellipse(ax, ay, 9, 3.4, i * Math.PI / 3 + t * .6, 0, 7); x.stroke(); }
    x.fillStyle = rgba(col.gold, 1); x.beginPath(); x.arc(ax, ay, 1.8, 0, 7); x.fill();
    lab(x, "NUCLEAR GRADE TUBE BUNDLE", 10, 16, c, .85); lab(x, `${pts.length} TUBES · ASME III · ECT 100%`, 10, h - 6, c, .6);
  }
  function turbine(k, sp){
    const { x, w, h } = k, c = main(), cx = w / 2, cy = h * .42, R = Math.min(w * .36, h * .3), rot = t * (st2() ? 6 : 2.2) * sp;
    for (let i = 0; i < 3; i++) { x.strokeStyle = rgba(c, .9 - i * .3); x.lineWidth = i ? 1 : 2; x.beginPath(); x.arc(cx, cy, R * (1 + i * .08), 0, 7); x.stroke(); }
    const nb = 18;
    for (let b = 0; b < nb; b++) { const a = rot + b / nb * Math.PI * 2; x.strokeStyle = rgba(b % 3 ? c : col.gold, .75); x.lineWidth = 1.4; x.beginPath();
      for (let i = 0; i <= 10; i++) { const f = i / 10, rr = R * (.24 + f * .74), aa = a + f * .55; i ? x.lineTo(cx + Math.cos(aa) * rr, cy + Math.sin(aa) * rr) : x.moveTo(cx + Math.cos(aa) * rr, cy + Math.sin(aa) * rr); } x.stroke(); }
    const sg = x.createRadialGradient(cx, cy, 0, cx, cy, R * .26); sg.addColorStop(0, rgba(col.gold, .9)); sg.addColorStop(1, rgba(c, .2));
    x.fillStyle = sg; x.beginPath(); x.arc(cx, cy, R * .22, 0, 7); x.fill();
    x.strokeStyle = rgba(col.gold, .9); x.lineWidth = 1.5; x.beginPath(); for (let i = 0; i < 60; i++) { const a = rot * 1.5 + i * .3, rr = i / 60 * R * .2; i ? x.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr) : x.moveTo(cx, cy); } x.stroke();
    // hydraulic tube runs below (aerospace tubing) with pressure pulses
    const y0 = h * .8; for (let l = 0; l < 3; l++) { const yy = y0 + l * 7; x.strokeStyle = rgba(c, .35); x.lineWidth = 2; x.beginPath(); x.moveTo(12, yy); x.lineTo(w * .4, yy); x.quadraticCurveTo(w * .5, yy, w * .5, yy - 10); x.lineTo(w * .5, yy - 10); x.quadraticCurveTo(w * .5, yy - 20 + l * 0, w * .6, yy - 20); x.lineTo(w - 12, yy - 20); x.stroke();
      const f = ((t * .5 * sp + l * .3) % 1), px = 12 + f * (w - 24), py = px < w * .45 ? yy : px > w * .55 ? yy - 20 : yy - 10;
      x.fillStyle = rgba(col.gold, .95); x.beginPath(); x.arc(px, py, 2.2, 0, 7); x.fill(); }
    lab(x, "AEROSPACE · TURBOFAN", 10, 16, c, .8); lab(x, `N1 ${(86 + Math.sin(t) * 3 + (st2() ? 8 : 0)).toFixed(1)}%`, w - 10, 16, col.gold, .9, 9, "right");
    lab(x, "Ti / Ni-ALLOY HYDRAULIC TUBING", 10, h - 6, c, .55);
  }
  const st2 = () => document.body.classList.contains("busy");
  const isAtlas = () => document.body.classList.contains("theme-atlas") && typeof Atlas !== "undefined";
  const atl = (k, fn) => (q, sp) => isAtlas() ? Atlas.sideDraw(q.c.id, q.x, q.w, q.h, main(), col.gold, t) : fn(q, sp);
  /* ---------- three more side screens so every look has 4-5 to rotate through ---------- */
  const spec = new Array(48).fill(0);
  function bars(k, sp){                                  // live spectrum / KPI bars with a sweeping peak line
    const { x, w, h } = k, c = main(), n = spec.length, bw = (w - 24) / n, base = h - 22;
    for (let i = 0; i < n; i++) { const tgt = .25 + .55 * Math.abs(Math.sin(i * .37 + t * 1.3 * sp) * Math.cos(i * .11 - t * .7));
      spec[i] += (tgt - spec[i]) * .12; const bh = spec[i] * (h - 50), px = 12 + i * bw;
      const g = x.createLinearGradient(0, base - bh, 0, base); g.addColorStop(0, rgba(c, .95)); g.addColorStop(1, rgba(c, .12));
      x.fillStyle = g; x.fillRect(px, base - bh, bw - 2, bh); x.fillStyle = rgba(col.gold, .9); x.fillRect(px, base - bh - 3, bw - 2, 2); }
    x.strokeStyle = rgba(c, .2); x.beginPath(); x.moveTo(12, base + .5); x.lineTo(w - 12, base + .5); x.stroke();
    for (let g = 1; g <= 3; g++) { x.strokeStyle = rgba(c, .07); x.beginPath(); x.moveTo(12, base - g * (h - 50) / 3); x.lineTo(w - 12, base - g * (h - 50) / 3); x.stroke(); }
    const sx = 12 + ((t * .25 * sp) % 1) * (w - 24); x.strokeStyle = rgba(col.gold, .55); x.beginPath(); x.moveTo(sx, 26); x.lineTo(sx, base); x.stroke();
    lab(x, "PLANT LOAD · LIVE", 10, 16, c, .8); lab(x, `${Math.round(spec.reduce((a, b) => a + b, 0) / n * 100)}%`, w - 10, 16, col.gold, .9, 9, "right");
  }
  function orbit(k, sp){                                 // atom / reactor core: three tilted orbits with electrons
    const { x, w, h } = k, cx = w / 2, cy = h / 2 + 4, R = Math.min(w, h) * .36, c = main();
    const core = x.createRadialGradient(cx, cy, 0, cx, cy, R * .4); core.addColorStop(0, rgba(col.gold, .95)); core.addColorStop(.4, rgba(c, .5)); core.addColorStop(1, rgba(c, 0));
    x.fillStyle = core; x.beginPath(); x.arc(cx, cy, R * .4, 0, 7); x.fill();
    for (let o = 0; o < 3; o++) { const rot = o * Math.PI / 3 + t * .15 * sp;
      x.save(); x.translate(cx, cy); x.rotate(rot); x.strokeStyle = rgba(c, .55); x.lineWidth = 1.2; x.beginPath(); x.ellipse(0, 0, R, R * .32, 0, 0, 7); x.stroke();
      for (let e = 0; e < 2; e++) { const a = t * (1.6 + o * .4) * sp + e * Math.PI; const ex = Math.cos(a) * R, ey = Math.sin(a) * R * .32;
        x.fillStyle = rgba(e ? c : col.gold, 1); x.beginPath(); x.arc(ex, ey, 3, 0, 7); x.fill();
        x.strokeStyle = rgba(e ? c : col.gold, .3); x.beginPath(); x.arc(ex, ey, 7, 0, 7); x.stroke(); }
      x.restore(); }
    lab(x, "CORE · STABLE", 10, 16, c, .8); lab(x, `${(98 + Math.sin(t * .8) * 1.4).toFixed(1)}%`, w - 10, 16, col.gold, .9, 9, "right");
  }
  function hexes(k, sp){                                 // honeycomb data grid with travelling pulses
    const { x, w, h } = k, c = main(), r = 13, dx = r * 1.732, dy = r * 1.5;
    for (let row = 0, y = 30; y < h - 8; row++, y += dy) for (let col2 = 0, xx = 12 + (row % 2) * dx / 2; xx < w - 8; col2++, xx += dx) {
      const d = Math.hypot(xx - w / 2, y - h / 2), p = .5 + .5 * Math.sin(d * .06 - t * 2.4 * sp), hot = ((row * 7 + col2 * 13 + Math.floor(t * 1.5)) % 23) === 0;
      x.beginPath(); for (let i = 0; i < 6; i++) { const a = Math.PI / 6 + i * Math.PI / 3; x[i ? "lineTo" : "moveTo"](xx + Math.cos(a) * r * .92, y + Math.sin(a) * r * .92); } x.closePath();
      x.strokeStyle = rgba(hot ? col.gold : c, .2 + p * .45); x.lineWidth = 1; x.stroke(); if (hot || p > .9) { x.fillStyle = rgba(hot ? col.gold : c, hot ? .5 : .12); x.fill(); } }
    lab(x, "DATA GRID · SYNC", 10, 16, c, .8); lab(x, `${Math.floor(t * 3) % 1000} pkts`, w - 10, 16, col.gold, .9, 9, "right");
  }
  /* each side screen rotates through its own playlist (4-5 animations), staggered so they never change together */
  const POOL = { radar, globe, wave, net, bars, orbit, hexes, utScan, tube3d, fuel, turbine };
  const PLAY = { normal: [["radar", "bars", "orbit", "hexes", "globe"], ["globe", "orbit", "radar", "net", "bars"],
                          ["wave", "hexes", "bars", "orbit", "radar"], ["net", "radar", "hexes", "globe", "wave"]],
                 titan:  [["utScan", "turbine", "fuel", "tube3d", "orbit"], ["tube3d", "utScan", "turbine", "fuel", "hexes"],
                          ["fuel", "tube3d", "utScan", "turbine", "bars"], ["turbine", "fuel", "tube3d", "utScan", "radar"]] };
  const HOLD = 14, FADE = .45;
  const rot = (slot, startName) => (k, sp) => {
    const list = PLAY[isTitan() ? "titan" : "normal"][slot], age = t + slot * 3.5;
    if (!document.body.classList.contains("theme-holo") && !isTitan()) return POOL[startName](k, sp);   // Aurora / Arc keep their fixed screens
    const i = Math.floor(age / HOLD) % list.length, ph = age % HOLD;
    if (k.cur !== i) { if (k.cur !== undefined && typeof HoloAudio !== "undefined" && HoloAudio.open) try { HoloAudio.open(slot); } catch {} k.cur = i; }
    const a = ph < FADE ? ph / FADE : ph > HOLD - FADE ? (HOLD - ph) / FADE : 1;
    k.x.globalAlpha = Math.max(0, Math.min(1, a)); if (a < 1) { k.x.translate(0, (1 - a) * 8); }
    POOL[list[i]](k, sp); k.x.globalAlpha = 1;
  };
  const radarT = atl(null, rot(0, "radar"));
  const globeT = atl(null, rot(1, "globe"));
  const waveT = atl(null, rot(2, "wave"));
  const netT = atl(null, rot(3, "net"));

  (function frame(now){
    const dt = Math.min(.05, (now - last) / 1000); last = now;
    const sp = mode() === "busy" ? 2.6 : 1;
    if (!document.hidden && !(typeof Forge3D !== "undefined" && Forge3D.active)) { t += dt;          // Forge: the side screens are 3D
      for (const [k, fn] of [[R, radarT], [Gb, globeT], [Wv, waveT], [Nt, netT]]) { if (!k || !k.w || k.c.offsetParent === null) continue;
        k.x.setTransform(dpr, 0, 0, dpr, 0, 0); k.x.clearRect(0, 0, k.w, k.h); fn(k, sp); } }
    if (!REDUCE) requestAnimationFrame(frame); else setTimeout(() => requestAnimationFrame(frame), 33);   // calm motion (e.g. Remote Desktop): slow, never blank
  })(performance.now());
  return {};
})();
</script>
