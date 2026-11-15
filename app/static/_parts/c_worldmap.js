/* ================================================================ WORLD MAP - country-wise figures on a hologram globe map
   Opens from any chat table that has a Country column (🌍 Map button) and from WorldMap.open(...).
   Numbers come only from that table. Countries glow by value, export arcs fly from Gandhidham, click a country or a
   region to zoom in (Tony-Stark style fly-to), mouse wheel = zoom at the pointer, drag = pan, double-click / World = back.
   Map data: Natural Earth (public domain) via world-atlas, served from /vendor/worldmap.js - nothing loads from the internet. */
const WorldMap = (() => {
  const ALIAS = { "usa": "United States of America", "u.s.a": "United States of America", "us": "United States of America", "united states": "United States of America",
    "america": "United States of America", "uk": "United Kingdom", "u.k": "United Kingdom", "england": "United Kingdom", "great britain": "United Kingdom",
    "uae": "United Arab Emirates", "u.a.e": "United Arab Emirates", "dubai": "United Arab Emirates", "ksa": "Saudi Arabia", "saudi": "Saudi Arabia",
    "korea": "South Korea", "republic of korea": "South Korea", "korea, republic of": "South Korea", "russian federation": "Russia",
    "viet nam": "Vietnam", "czech republic": "Czechia", "ivory coast": "Côte d'Ivoire", "cote d'ivoire": "Côte d'Ivoire", "swaziland": "eSwatini",
    "bosnia and herzegovina": "Bosnia and Herz.", "dominican republic": "Dominican Rep.", "drc": "Dem. Rep. Congo", "congo, dem. rep.": "Dem. Rep. Congo",
    "central african republic": "Central African Rep.", "south sudan": "S. Sudan", "north macedonia": "Macedonia", "turkiye": "Turkey", "türkiye": "Turkey",
    "holland": "Netherlands", "the netherlands": "Netherlands", "burma": "Myanmar", "lao pdr": "Laos", "iran, islamic republic of": "Iran",
    "tanzania, united republic of": "Tanzania", "syrian arab republic": "Syria", "hongkong": "China", "hong kong": "China", "bharat": "India" };
  const REG = {
    "Middle East": ["United Arab Emirates", "Saudi Arabia", "Oman", "Qatar", "Kuwait", "Bahrain", "Iran", "Iraq", "Jordan", "Israel", "Lebanon", "Syria", "Yemen", "Turkey", "Egypt"],
    "Europe": ["United Kingdom", "Germany", "France", "Italy", "Spain", "Portugal", "Netherlands", "Belgium", "Switzerland", "Austria", "Poland", "Czechia", "Sweden",
      "Norway", "Finland", "Denmark", "Ireland", "Greece", "Romania", "Hungary", "Ukraine", "Bulgaria", "Serbia", "Croatia"],
    "Asia": ["India", "China", "Japan", "South Korea", "Indonesia", "Malaysia", "Thailand", "Vietnam", "Philippines", "Singapore", "Bangladesh", "Sri Lanka",
      "Pakistan", "Nepal", "Myanmar", "Kazakhstan", "Mongolia", "Taiwan"],
    "Africa": ["Nigeria", "South Africa", "Kenya", "Egypt", "Morocco", "Algeria", "Ghana", "Ethiopia", "Tanzania", "Angola", "Mozambique", "Sudan", "Libya", "Tunisia",
      "Côte d'Ivoire", "Cameroon", "Dem. Rep. Congo"],
    "N. America": ["United States of America", "Canada", "Mexico"],
    "S. America": ["Brazil", "Argentina", "Chile", "Peru", "Colombia", "Venezuela", "Ecuador", "Bolivia", "Uruguay", "Paraguay"],
    "Oceania": ["Australia", "New Zealand", "Papua New Guinea"],
    "SAARC": ["India", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal", "Bhutan", "Afghanistan"],
  };
  const COUNTRY_COL = /country|nation|destination|export\s*to|cntry|^dest$/i;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const num = v => { if (typeof v === "number") return v; const n = parseFloat(String(v ?? "").replace(/[,₹\s%]/g, "")); return isFinite(n) ? n : NaN; };
  let loading = null;
  const load = () => loading ||= new Promise((ok, bad) => { if (window.WORLD_MAP) return ok(window.WORLD_MAP);
    const s = document.createElement("script"); s.src = "/vendor/worldmap.js"; s.onload = () => ok(window.WORLD_MAP); s.onerror = () => { loading = null; bad(new Error("map not available")); };
    document.head.appendChild(s); });

  // ---------- read a chat table: which column is the country, which is the number
  function fromTable(table){
    const head = [...table.querySelectorAll("thead th")].map(th => th.textContent.trim());
    const ci = head.findIndex(h => COUNTRY_COL.test(h)); if (ci < 0) return null;
    const rows = [...table.querySelectorAll("tbody tr")].map(tr => [...tr.children].map(td => td.textContent.trim()));
    let vi = -1; for (let j = 0; j < head.length; j++) if (j !== ci && rows.length && rows.filter(r => isFinite(num(r[j]))).length >= rows.length * .7) { vi = j; break; }
    if (vi < 0) return null;
    return { country: head[ci], measure: head[vi], rows: rows.filter(r => r[ci] && !/^(total|grand total)$/i.test(r[ci])).map(r => ({ name: r[ci], value: num(r[vi]) })) };
  }
  const canon = (n, names) => { const k = n.trim().toLowerCase().replace(/\.$/, ""); if (ALIAS[k]) return ALIAS[k];
    return names.find(x => x.toLowerCase() === k) || names.find(x => x.toLowerCase().startsWith(k) || k.startsWith(x.toLowerCase())) || null; };

  // ---------- the dialog
  let dlg = null;
  function ui(){
    if (dlg) return dlg;
    const st = document.createElement("style"); st.textContent = `
    #wmDlg{width:min(97vw,1800px);max-width:none;height:92vh;padding:0;border:1px solid var(--line2);border-radius:18px;color:var(--tx);overflow:hidden;
      background:radial-gradient(1200px 700px at 50% 40%,rgba(0,60,110,.35),rgba(2,6,14,.98))}
    #wmDlg::backdrop{background:rgba(0,0,0,.7);backdrop-filter:blur(3px)}
    #wmDlg .wh{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line);flex-wrap:wrap}
    #wmDlg .wh b{font:600 14px var(--disp,inherit);letter-spacing:.14em;text-transform:uppercase;margin-right:auto}
    #wmDlg .rg{display:flex;gap:6px;flex-wrap:wrap}#wmDlg .rg button{border:1px solid var(--line2);background:rgba(255,255,255,.03);color:var(--mut);
      font:600 11px var(--ui,inherit);padding:5px 10px;border-radius:999px;cursor:pointer}#wmDlg .rg button.on,#wmDlg .rg button:hover{color:var(--tx);border-color:var(--ac)}
    #wmDlg .wb{display:grid;grid-template-columns:minmax(0,1fr) 300px;height:calc(92vh - 58px)}
    #wmDlg svg{width:100%;height:100%;display:block;cursor:grab;touch-action:none}#wmDlg svg.pan{cursor:grabbing}
    #wmDlg .sea{fill:rgba(0,90,150,.08);stroke:rgba(120,220,255,.25)}#wmDlg .gr{fill:none;stroke:rgba(120,220,255,.07);stroke-width:.6}
    #wmDlg .ct{fill:rgba(120,200,255,.07);stroke:rgba(140,220,255,.32);stroke-width:.35;vector-effect:non-scaling-stroke;transition:fill .25s}
    #wmDlg .ct.d{cursor:pointer}#wmDlg .ct:hover{fill:rgba(120,220,255,.28)}#wmDlg .ct.sel{stroke:var(--gold,#f0c060);stroke-width:1.4}
    #wmDlg .arc{fill:none;stroke:var(--gold,#f0c060);stroke-width:1.1;vector-effect:non-scaling-stroke;stroke-dasharray:4 6;animation:wmDash 1.6s linear infinite;opacity:.8}
    @keyframes wmDash{to{stroke-dashoffset:-20}}
    #wmDlg svg{--k:1}#wmDlg .dot{fill:var(--ac,#4fd0ff);r:calc(var(--r) * var(--k))}
    #wmDlg .ring{fill:none;stroke:var(--ac,#4fd0ff);vector-effect:non-scaling-stroke;animation:wmPing 2.2s ease-out infinite}
    @keyframes wmPing{0%{r:calc(2px * var(--k));opacity:.9}100%{r:calc(16px * var(--k));opacity:0}}
    #wmDlg .home{fill:var(--gold,#f0c060);r:calc(3px * var(--k))}
    #wmDlg .lbl{font-weight:600;font-family:var(--ui,sans-serif);font-size:calc(7.5px * var(--k));fill:#dff6ff;paint-order:stroke;stroke:#02060e;
      stroke-width:calc(2px * var(--k));pointer-events:none}
    #wmDlg aside{border-left:1px solid var(--line);padding:14px;overflow:auto}
    #wmDlg .card2{border:1px solid var(--line2);border-radius:12px;padding:12px;margin-bottom:12px;background:rgba(255,255,255,.03)}
    #wmDlg .card2 h4{margin:0 0 4px;font:600 11px var(--ui,inherit);letter-spacing:.14em;text-transform:uppercase;color:var(--mut)}
    #wmDlg .big{font:700 26px var(--disp,inherit);color:var(--ac)}#wmDlg .rk{display:grid;grid-template-columns:22px 1fr auto;gap:6px;padding:6px 0;border-top:1px solid var(--line);font-size:12.5px;cursor:pointer}
    #wmDlg .rk:hover{color:var(--ac)}#wmDlg .bar{grid-column:2/4;height:4px;border-radius:3px;background:linear-gradient(90deg,var(--ac),transparent)}
    #wmDlg .miss{color:var(--mut);font-size:11.5px}#wmDlg .tip{position:fixed;z-index:10001;pointer-events:none;padding:6px 10px;border-radius:8px;font-size:12px;
      background:rgba(2,8,18,.92);border:1px solid var(--line2);color:var(--tx)}
    @media(max-width:820px){#wmDlg .wb{grid-template-columns:1fr;grid-template-rows:62% 38%}#wmDlg aside{border-left:0;border-top:1px solid var(--line)}}`;
    document.head.appendChild(st);
    dlg = document.createElement("dialog"); dlg.id = "wmDlg"; dlg.setAttribute("aria-label", "World map");
    dlg.innerHTML = `<div class="wh"><b id="wmT">World map</b><div class="rg" id="wmR"></div><button class="tbtn" type="button" id="wmX">Close</button></div>
      <div class="wb"><svg id="wmS" role="img" aria-label="World map"></svg><aside id="wmA"></aside></div><div class="tip" id="wmTip" hidden></div>`;
    document.body.appendChild(dlg); dlg.querySelector("#wmX").onclick = () => dlg.close();
    return dlg;
  }

  async function open({ title = "Country-wise", measure = "Value", rows = [] } = {}){
    const d = ui(); d.showModal(); const svg = d.querySelector("#wmS"), side = d.querySelector("#wmA"), tip = d.querySelector("#wmTip");
    d.querySelector("#wmT").textContent = title; svg.innerHTML = `<text x="50%" y="50%" fill="#8fdcff" text-anchor="middle">Loading map…</text>`;
    let M; try { M = await load(); } catch (e) { svg.innerHTML = `<text x="50%" y="50%" fill="#ff9aa8" text-anchor="middle">${esc(e.message)}</text>`; return; }
    const names = M.c.map(c => c[0]), data = new Map(), missing = [];
    for (const r of rows) { if (!isFinite(r.value)) continue; const n = canon(r.name, names); if (!n) { missing.push(r.name); continue; } data.set(n, (data.get(n) || 0) + r.value); }
    const total = [...data.values()].reduce((a, b) => a + b, 0), max = Math.max(1, ...data.values());
    const fmt = v => v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
    const NS = "http://www.w3.org/2000/svg";
    let h = `<rect x="-2000" y="-2000" width="5000" height="5000" fill="transparent"/><path class="sea" d="${M.sphere}"/>` + M.grat.map(g => `<path class="gr" d="${g}"/>`).join("") + `<g id="wmC">`;
    for (const [n, p] of M.c) { const v = data.get(n); const a = v ? .18 + .72 * Math.sqrt(v / max) : 0;
      h += `<path class="ct${v ? " d" : ""}" data-n="${esc(n)}" d="${p}"${v ? ` style="fill:color-mix(in srgb,var(--ac,#4fd0ff) ${Math.round(a * 100)}%,transparent)"` : ""}/>`; }
    h += `</g><g id="wmF">`;
    const ranked = [...data.entries()].sort((a, b) => b[1] - a[1]), [hx, hy] = M.home;
    for (const [n, v] of ranked) { const c = M.c.find(x => x[0] === n); if (!c) continue; const [, , x, y] = c;
      if (n !== "India") { const mx = (hx + x) / 2, my = Math.min(hy, y) - Math.hypot(x - hx, y - hy) * .28; h += `<path class="arc" d="M${hx} ${hy}Q${mx} ${my} ${x} ${y}"/>`; }
      const r = 1.6 + 4.5 * Math.sqrt(v / max); h += `<circle class="ring" cx="${x}" cy="${y}"/><circle class="dot" cx="${x}" cy="${y}" style="--r:${r.toFixed(1)}px"/>`; }
    h += `<circle class="home" cx="${hx}" cy="${hy}"/><text class="lbl" x="${hx}" y="${hy}" dx="5" dy="10">Gandhidham</text>`;
    for (const [n] of ranked.slice(0, 12)) { const c = M.c.find(x => x[0] === n); if (c) h += `<text class="lbl" x="${c[2]}" y="${c[3]}" dx="5" dy="-4">${esc(n)}</text>`; }
    svg.innerHTML = h + `</g>`;
    // ----- side panel: KPIs first
    const shareTop = ranked.length ? ranked[0][1] / total * 100 : 0;
    side.innerHTML = `<div class="card2"><h4>${esc(measure)} · total</h4><div class="big">${fmt(total)}</div>
        <div class="miss">${ranked.length} countries${ranked.length ? ` · top: ${esc(ranked[0][0])} ${shareTop.toFixed(1)}%` : ""}</div></div>
      <div class="card2" id="wmSel"><h4>Selected</h4><div class="miss">Click a country on the map or in the list</div></div>
      <div class="card2"><h4>Ranking</h4>${ranked.map(([n, v], i) => `<div class="rk" data-n="${esc(n)}"><span>${i + 1}</span><span>${esc(n)}</span><b>${fmt(v)}</b>
        <div class="bar" style="width:${(v / max * 100).toFixed(1)}%"></div></div>`).join("") || '<div class="miss">No numbers to plot.</div>'}</div>`
      + (missing.length ? `<div class="card2"><h4>Not placed on map</h4><div class="miss">${missing.map(esc).join(", ")}</div></div>` : "");
    // ----- regions
    const rg = d.querySelector("#wmR"); rg.innerHTML = `<button type="button" class="on" data-r="World">World</button>` + Object.keys(REG).map(r => `<button type="button" data-r="${r}">${r}</button>`).join("");
    // ----- camera (viewBox), animated fly-to
    const full = [0, 0, M.w, M.h]; let vb = full.slice(), anim = 0;
    const setVB = b => { vb = b; svg.setAttribute("viewBox", b.map(v => v.toFixed(2)).join(" "));     // dots & labels keep their screen size
      svg.style.setProperty("--k", Math.max(.04, b[2] / M.w).toFixed(4)); };
    setVB(full);
    const fly = (to, ms = 650) => { cancelAnimationFrame(anim); const from = vb.slice(), t0 = performance.now();
      const step = now => { const k = Math.min(1, (now - t0) / ms), e = k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        setVB(from.map((v, i) => v + (to[i] - v) * e)); if (k < 1) anim = requestAnimationFrame(step); }; anim = requestAnimationFrame(step);
      try { HoloAudio && HoloAudio.whoosh && HoloAudio.whoosh(); } catch {} };
    const boxOf = list => { let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const n of list) { const el = svg.querySelector(`.ct[data-n="${CSS.escape(n)}"]`); if (!el) continue; const b = el.getBBox();
        if (b.width > M.w * .6) continue; x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.width); y1 = Math.max(y1, b.y + b.height); }
      if (x0 > x1) return full; const pw = (x1 - x0) * .18 + 8, ph = (y1 - y0) * .18 + 8; let w = x1 - x0 + pw * 2, hh = y1 - y0 + ph * 2;
      const ar = svg.clientWidth / Math.max(1, svg.clientHeight); if (w / hh < ar) w = hh * ar; else hh = w / ar;
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2; return [cx - w / 2, cy - hh / 2, w, hh]; };
    rg.onclick = e => { const b = e.target.closest("button"); if (!b) return; rg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
      fly(b.dataset.r === "World" ? full : boxOf(REG[b.dataset.r])); };
    const select = n => { svg.querySelectorAll(".ct.sel").forEach(x => x.classList.remove("sel")); const el = svg.querySelector(`.ct[data-n="${CSS.escape(n)}"]`);
      if (el) el.classList.add("sel"); const v = data.get(n);
      d.querySelector("#wmSel").innerHTML = `<h4>Selected</h4><div style="font-weight:600">${esc(n)}</div>` + (v !== undefined
        ? `<div class="big">${fmt(v)}</div><div class="miss">${(v / total * 100).toFixed(1)}% of total · rank ${ranked.findIndex(r => r[0] === n) + 1} of ${ranked.length}</div>`
        : `<div class="miss">No ${esc(measure)} for this country in this report.</div>`);
      fly(boxOf([n])); };
    side.onclick = e => { const r = e.target.closest(".rk"); if (r) select(r.dataset.n); };
    // ----- mouse: hover tip, click = fly to country, wheel = zoom at pointer, drag = pan, dblclick = world
    const pt = e => { const r = svg.getBoundingClientRect(); return [vb[0] + (e.clientX - r.left) / r.width * vb[2], vb[1] + (e.clientY - r.top) / r.height * vb[3]]; };
    let pan = null, moved = 0;
    svg.onpointerdown = e => { pan = { x: e.clientX, y: e.clientY, vb: vb.slice() }; moved = 0; svg.setPointerCapture(e.pointerId); };
    svg.onpointermove = e => {
      const c = e.target.closest && e.target.closest(".ct");
      if (c && !pan) { const n = c.dataset.n, v = data.get(n); tip.hidden = false; tip.style.left = e.clientX + 14 + "px"; tip.style.top = e.clientY + 12 + "px";
        tip.innerHTML = `<b>${esc(n)}</b>${v !== undefined ? ` · ${fmt(v)} (${(v / total * 100).toFixed(1)}%)` : ""}`; } else if (!pan) tip.hidden = true;
      if (!pan) return; const r = svg.getBoundingClientRect(), dx = (e.clientX - pan.x) / r.width * pan.vb[2], dy = (e.clientY - pan.y) / r.height * pan.vb[3];
      moved = Math.max(moved, Math.abs(e.clientX - pan.x) + Math.abs(e.clientY - pan.y)); if (moved > 4) { svg.classList.add("pan"); setVB([pan.vb[0] - dx, pan.vb[1] - dy, pan.vb[2], pan.vb[3]]); } };
    svg.onpointerup = e => { svg.classList.remove("pan"); const was = moved; pan = null;
      if (was <= 4) { const hit = document.elementFromPoint(e.clientX, e.clientY), c = hit && hit.closest(".ct"); if (c) select(c.dataset.n); } };
    svg.onwheel = e => { e.preventDefault(); cancelAnimationFrame(anim); const [px, py] = pt(e), f = e.deltaY < 0 ? .85 : 1 / .85;
      const w = Math.min(M.w * 1.4, Math.max(18, vb[2] * f)), hh = w * vb[3] / vb[2]; setVB([px - (px - vb[0]) * w / vb[2], py - (py - vb[1]) * hh / vb[3], w, hh]); };
    svg.ondblclick = () => { fly(full); rg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x.dataset.r === "World")); };
    svg.onpointerleave = () => { tip.hidden = true; };
  }
  return { open, fromTable, load };
})();
