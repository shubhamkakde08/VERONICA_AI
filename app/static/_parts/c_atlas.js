/* ================================================================ ATLAS theme (admin / manager only)
   A blue holographic product platform: coil reel, seamless pipe bundle, flange, elbow, tee, reducer on a glowing
   round projector, with a nuclear plant and a fighter jet behind - the company's products and where they go.
   EXPLODED VIEW: every part can be pulled apart and put back together -
     hand gestures: two hands pinching on the platform (or on a side screen) -> pull apart = EXPLODE, push together = ASSEMBLE
                    quick pinch on a part = REMOVE it (ghost outline stays) · pinch it again = FIT it back
     mouse / touch: the ASSEMBLY screen has the same buttons (Explode, Assemble, every part).
   Side screens (pipe bundle, coil reel, fittings set, plant + jet) explode / assemble the same way. */
const Atlas = (() => {
  const PARTS = [
    { id: "towers", short: "Plant", label: "Nuclear plant", x: -.34, y: -.66, s: .42 },
    { id: "jet", short: "Jet", label: "Fighter jet", x: .62, y: -.62, s: .3 },
    { id: "reel", short: "Coil reel", label: "Coil reel", x: -.74, y: .02, s: .34 },
    { id: "pipes", short: "Pipes", label: "Seamless pipe bundle", x: -.08, y: .06, s: .38 },
    { id: "flange", short: "Flange", label: "Weld-neck flange", x: .4, y: .14, s: .16 },
    { id: "elbow", short: "Elbow", label: "90° elbow", x: .66, y: -.04, s: .18 },
    { id: "tee", short: "Tee", label: "Equal tee", x: .8, y: .2, s: .17 },
    { id: "reducer", short: "Reducer", label: "Concentric reducer", x: .26, y: .34, s: .14 },
  ];
  const st = { e: 0, eT: 0, removed: new Set(), a: Object.fromEntries(PARTS.map(p => [p.id, 1])), hits: [], rect: null };
  const side = {};                                            // side screens: { hudRadar: {e, eT}, ... }
  const listeners = [];
  const changed = () => listeners.forEach(f => { try { f(); } catch {} });
  const on = () => document.body.classList.contains("theme-atlas");
  const rgbaS = (c, a) => `rgba(${c},${a})`;                  // c = "r,g,b"
  const rgbaH = (hex, a) => { const h = hex.replace("#", ""), n = parseInt(h.length === 3 ? h.split("").map(q => q + q).join("") : h, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };

  /* ---------- primitives (x = 2D context, col(a) -> colour string) */
  function pipe(x, px, py, len, r, ang, col, bright = 1){
    const dx = Math.cos(ang), dy = Math.sin(ang), nx = -dy, ny = dx, ex = px + dx * len, ey = py + dy * len;
    const g = x.createLinearGradient(px + nx * r, py + ny * r, px - nx * r, py - ny * r);
    g.addColorStop(0, col(.1 * bright)); g.addColorStop(.35, col(.32 * bright)); g.addColorStop(1, col(.05 * bright));
    x.fillStyle = g; x.beginPath(); x.moveTo(px + nx * r, py + ny * r); x.lineTo(ex + nx * r, ey + ny * r); x.lineTo(ex - nx * r, ey - ny * r); x.lineTo(px - nx * r, py - ny * r); x.closePath(); x.fill();
    x.strokeStyle = col(.85 * bright); x.lineWidth = 1.2;
    x.beginPath(); x.moveTo(px + nx * r, py + ny * r); x.lineTo(ex + nx * r, ey + ny * r); x.moveTo(px - nx * r, py - ny * r); x.lineTo(ex - nx * r, ey - ny * r); x.stroke();
    x.strokeStyle = col(.25 * bright); x.lineWidth = 1;
    for (let k = 1; k < 6; k++) { const f = k / 6; x.beginPath(); x.ellipse(px + dx * len * f, py + dy * len * f, r * .3, r, ang, -Math.PI / 2, Math.PI / 2); x.stroke(); }
    x.strokeStyle = col(.9 * bright); x.lineWidth = 1.4; x.beginPath(); x.ellipse(ex, ey, r * .32, r, ang, 0, 7); x.stroke();
    x.strokeStyle = col(.55 * bright); x.beginPath(); x.ellipse(ex, ey, r * .24, r * .76, ang, 0, 7); x.stroke();
    x.fillStyle = col(.08 * bright); x.fill();
  }
  function reel(x, px, py, R, col, t, bright = 1){
    const w = R * .95;
    for (const [ox, front] of [[-w / 2, false], [w / 2, true]]) {
      x.strokeStyle = col((front ? .95 : .4) * bright); x.lineWidth = front ? 1.6 : 1;
      x.beginPath(); x.ellipse(px + ox, py, R * .34, R, 0, 0, 7); x.stroke();
      if (front) { for (let k = 0; k < 10; k++) { const a = k / 10 * Math.PI * 2 + t * .4; x.beginPath(); x.moveTo(px + ox, py); x.lineTo(px + ox + Math.cos(a) * R * .32, py + Math.sin(a) * R * .95); x.stroke(); }
        x.beginPath(); x.ellipse(px + ox, py, R * .1, R * .28, 0, 0, 7); x.stroke(); }
    }
    for (let k = -7; k <= 7; k++) { const yy = py + k * R * .1; x.strokeStyle = col((.35 + .4 * Math.abs(Math.sin(k + t))) * bright); x.lineWidth = 1.6;
      x.beginPath(); x.moveTo(px - w / 2 + R * .05, yy); x.quadraticCurveTo(px, yy + R * .06, px + w / 2 - R * .05, yy); x.stroke(); }
  }
  function flange(x, px, py, R, col, bright = 1){
    x.strokeStyle = col(.95 * bright); x.lineWidth = 1.5; x.beginPath(); x.ellipse(px, py, R * .36, R, 0, 0, 7); x.stroke();
    x.fillStyle = col(.12 * bright); x.fill();
    x.strokeStyle = col(.6 * bright); x.beginPath(); x.ellipse(px, py, R * .2, R * .5, 0, 0, 7); x.stroke();
    for (let k = 0; k < 8; k++) { const a = k / 8 * Math.PI * 2; x.beginPath(); x.ellipse(px + Math.cos(a) * R * .27, py + Math.sin(a) * R * .76, R * .04, R * .09, 0, 0, 7); x.stroke(); }
    x.beginPath(); x.ellipse(px + R * .2, py, R * .36, R, 0, -Math.PI / 2, Math.PI / 2); x.stroke();
  }
  function elbow(x, px, py, R, col, bright = 1){
    const r = R * .32, rr = R * .7;
    for (let k = 0; k <= 12; k++) { const a = Math.PI + k / 12 * Math.PI / 2, cx = px + rr + Math.cos(a) * rr, cy = py + Math.sin(a) * rr;
      x.strokeStyle = col((k % 6 ? .3 : .9) * bright); x.lineWidth = k % 6 ? 1 : 1.5; x.beginPath(); x.ellipse(cx, cy, r * .35, r, a + Math.PI / 2, 0, 7); x.stroke(); }
    x.strokeStyle = col(.85 * bright); x.lineWidth = 1.3;
    x.beginPath(); x.arc(px + rr, py, rr + r, Math.PI, Math.PI * 1.5); x.stroke(); x.beginPath(); x.arc(px + rr, py, rr - r, Math.PI, Math.PI * 1.5); x.stroke();
  }
  function tee(x, px, py, R, col, bright = 1){ pipe(x, px - R, py, R * 2, R * .34, 0, col, bright); pipe(x, px, py - R * .1, R * .9, R * .3, -Math.PI / 2, col, bright); }
  function reducer(x, px, py, R, col, bright = 1){
    const r1 = R * .5, r2 = R * .3, L = R * 1.2;
    x.strokeStyle = col(.9 * bright); x.lineWidth = 1.4;
    x.beginPath(); x.ellipse(px, py, r1 * .34, r1, 0, 0, 7); x.stroke(); x.beginPath(); x.ellipse(px + L, py, r2 * .34, r2, 0, 0, 7); x.stroke();
    x.beginPath(); x.moveTo(px, py - r1); x.lineTo(px + L, py - r2); x.moveTo(px, py + r1); x.lineTo(px + L, py + r2); x.stroke();
    x.fillStyle = col(.1 * bright); x.beginPath(); x.moveTo(px, py - r1); x.lineTo(px + L, py - r2); x.lineTo(px + L, py + r2); x.lineTo(px, py + r1); x.closePath(); x.fill();
  }
  function tower(x, px, py, H, col, t, bright = 1){
    const w = H * .36, top = py - H;
    x.strokeStyle = col(.85 * bright); x.lineWidth = 1.4;
    x.beginPath(); x.moveTo(px - w, py); x.quadraticCurveTo(px - w * .45, py - H * .55, px - w * .62, top); x.moveTo(px + w, py); x.quadraticCurveTo(px + w * .45, py - H * .55, px + w * .62, top); x.stroke();
    x.beginPath(); x.ellipse(px, top, w * .62, w * .16, 0, 0, 7); x.stroke(); x.beginPath(); x.ellipse(px, py, w, w * .2, 0, 0, Math.PI); x.stroke();
    x.strokeStyle = col(.18 * bright); x.lineWidth = 1;
    for (let k = 1; k < 6; k++) { const f = k / 6, yy = py - H * f, ww = w * (1 - .45 * Math.sin(f * Math.PI * .9)); x.beginPath(); x.ellipse(px, yy, ww, ww * .18, 0, 0, Math.PI); x.stroke(); }
    for (let k = 0; k < 7; k++) { const ph = (t * .25 + k / 7) % 1, sx = px + Math.sin(k * 2.3 + t) * w * .35 * ph, sy = top - ph * H * .6, sr = w * (.25 + ph * .55);
      x.fillStyle = col(.16 * (1 - ph) * bright); x.beginPath(); x.arc(sx, sy, sr, 0, 7); x.fill(); }
  }
  function jet(x, px, py, S, ang, col, bright = 1){
    const P = [[5, 0], [3.4, .35], [1.2, .7], [.2, .85], [-2.3, 3.3], [-3, 3.3], [-2.7, .95], [-4.2, 2], [-4.7, 2], [-4.5, .5], [-5, .3], [-5, -.3], [-4.5, -.5], [-4.7, -2], [-4.2, -2], [-2.7, -.95], [-3, -3.3], [-2.3, -3.3], [.2, -.85], [1.2, -.7], [3.4, -.35]];
    x.beginPath(); P.forEach(([a, b], i) => { const X = px + (a * Math.cos(ang) - b * .55 * Math.sin(ang)) * S, Y = py + (a * Math.sin(ang) + b * .55 * Math.cos(ang)) * S; i ? x.lineTo(X, Y) : x.moveTo(X, Y); });
    x.closePath(); x.fillStyle = col(.18 * bright); x.fill(); x.strokeStyle = col(.95 * bright); x.lineWidth = 1.3; x.stroke();
    const tx = px - 5 * Math.cos(ang) * S, ty = py - 5 * Math.sin(ang) * S, gr = x.createRadialGradient(tx, ty, 0, tx, ty, S * 2.4);
    gr.addColorStop(0, col(.8 * bright)); gr.addColorStop(1, col(0)); x.fillStyle = gr; x.beginPath(); x.arc(tx, ty, S * 2.4, 0, 7); x.fill();
  }
  const DRAW = {
    towers: (x, px, py, S, col, t, b) => { tower(x, px - S * .45, py + S * .5, S * 1.1, col, t, b); tower(x, px + S * .35, py + S * .55, S * 1.2, col, t + 1.7, b);
      x.strokeStyle = col(.5 * b); x.beginPath(); x.ellipse(px - S * 1.1, py + S * .5, S * .25, S * .2, 0, Math.PI, 0); x.stroke(); },
    jet: (x, px, py, S, col, t, b) => jet(x, px, py, S * .2, -.45, col, b),
    reel: (x, px, py, S, col, t, b) => reel(x, px, py, S, col, t, b),
    pipes: (x, px, py, S, col, t, b) => { const r = S * .16; [[0, -1.1], [-.25, 0], [.3, -.15], [-.05, 1.05], [.55, .9], [.1, 2.1]].forEach(([ox, oy], i) =>
      pipe(x, px - S * 1.05 + ox * S * .4, py + oy * r * 1.15 - S * .2, S * (1.8 - i * .1), r, -.22, col, b)); },
    flange: (x, px, py, S, col, t, b) => flange(x, px, py, S, col, b),
    elbow: (x, px, py, S, col, t, b) => elbow(x, px, py, S, col, b),
    tee: (x, px, py, S, col, t, b) => tee(x, px, py, S, col, b),
    reducer: (x, px, py, S, col, t, b) => reducer(x, px, py, S, col, b),
  };

  /* ---------- the centre hologram */
  function draw(x, cx, cy, R, c, o, t){
    st.e += (st.eT - st.e) * .08;
    st.rect = x.canvas.getBoundingClientRect();
    document.body.classList.toggle("atlas-x", st.e > .2);                  // exploded: other screens step back so the parts are visible
    const S = R * 1.45, py0 = cy + R * .4, col = a => rgbaS(c, a), hi = a => rgbaS(o, a);
    // projector platform: rings, light segments, beam
    for (let k = 0; k < 4; k++) { x.strokeStyle = col(.5 - k * .1); x.lineWidth = k ? 1 : 2; x.beginPath(); x.ellipse(cx, py0 + S * .48, S * (1.05 + k * .14), S * (.2 + k * .03), 0, 0, 7); x.stroke(); }
    for (let k = 0; k < 16; k++) { const a = k / 16 * Math.PI * 2 + t * .3; if (Math.sin(a) < 0) continue;
      x.strokeStyle = hi(.9); x.lineWidth = 3; x.beginPath(); x.ellipse(cx, py0 + S * .62, S * 1.2, S * .24, 0, a, a + .12); x.stroke(); }
    const beam = x.createLinearGradient(0, py0 + S * .5, 0, cy - S); beam.addColorStop(0, col(.22)); beam.addColorStop(1, col(0));
    x.fillStyle = beam; x.beginPath(); x.moveTo(cx - S * 1.05, py0 + S * .48); x.lineTo(cx - S * 1.3, cy - S); x.lineTo(cx + S * 1.3, cy - S); x.lineTo(cx + S * 1.05, py0 + S * .48); x.fill();
    // parts (back to front)
    st.hits = [];
    const e = st.e;
    PARTS.forEach((p, i) => {
      const target = st.removed.has(p.id) ? 0 : 1; st.a[p.id] += (target - st.a[p.id]) * .1;
      const L = Math.hypot(p.x, p.y + .1) || 1, ox = p.x / L * e * S * .3, oy = (p.y + .1) / L * e * S * .5 - e * S * .2 + Math.sin(t * 1.3 + i) * e * 4;
      const px = cx + p.x * S + ox, py = py0 + p.y * S + oy, ps = p.s * S * (1 + e * .06), a = st.a[p.id];
      st.hits.push({ id: p.id, x: px, y: py, r: ps * 1.1 });
      if (a < .98) { x.save(); x.globalAlpha = .18; x.setLineDash([3, 4]); DRAW[p.id](x, px, py, ps, col, t, .6); x.restore(); }      // ghost of a removed part
      if (a > .02) { x.save(); x.globalAlpha = a; DRAW[p.id](x, px, py, ps, col, t, 1); x.restore(); }
      if (e > .25) {                                                                                   // exploded-view callouts
        const lx = px + (p.x >= 0 ? 1 : -1) * ps * 1.1, ly = py - ps * .9;
        x.strokeStyle = hi(.55 * e); x.lineWidth = 1; x.beginPath(); x.moveTo(px, py); x.lineTo(lx, ly); x.lineTo(lx + (p.x >= 0 ? 26 : -26), ly); x.stroke();
        x.font = '600 10px "JetBrains Mono",monospace'; x.textAlign = p.x >= 0 ? "left" : "right"; x.fillStyle = hi(.95 * e);
        x.fillText(String(i + 1).padStart(2, "0") + " " + p.label.toUpperCase() + (st.removed.has(p.id) ? " · REMOVED" : ""), lx + (p.x >= 0 ? 30 : -30), ly + 3);
      }
    });
    x.font = '600 10px "JetBrains Mono",monospace'; x.textAlign = "center"; x.fillStyle = col(.7);
    x.fillText(e > .15 ? `EXPLODED VIEW ${Math.round(e * 100)}% · ${PARTS.length - st.removed.size}/${PARTS.length} PARTS FITTED` : "VENUS PIPES & TUBES · PRODUCT HOLOGRAM", cx, py0 + S * .95);
  }
  function pick(clientX, clientY){
    if (!on() || !st.rect) return null;
    const x = clientX - st.rect.left, y = clientY - st.rect.top;
    let best = null; st.hits.forEach(h => { const d = Math.hypot(h.x - x, h.y - y); if (d < h.r && (!best || d < best.d)) best = { id: h.id, d }; });
    return best && best.id;
  }
  function toggle(id){ if (!PARTS.some(p => p.id === id)) return; st.removed.has(id) ? st.removed.delete(id) : st.removed.add(id);
    if (typeof HoloAudio !== "undefined") st.removed.has(id) ? HoloAudio.whoosh() : HoloAudio.scene(); changed(); }
  function setExplode(id, v){ v = Math.max(0, Math.min(1, v)); if (id === "core") st.eT = v; else (side[id] = side[id] || { e: 0, eT: 0 }).eT = v; changed(); }
  function getExplode(id){ return id === "core" ? st.eT : (side[id] ? side[id].eT : 0); }
  function sideE(id){ const s = side[id] = side[id] || { e: 0, eT: 0 }; s.e += (s.eT - s.e) * .08; return s.e; }

  /* ---------- side screens (HudFx canvases) */
  function sideDraw(id, x, w, h, c, g, t){
    const e = sideE(id), col = a => rgbaH(c, a), gl = a => rgbaH(g, a);
    const lab = (s, px, py, al = "left", a = .8) => { x.font = '600 9px "JetBrains Mono",monospace'; x.textAlign = al; x.fillStyle = col(a); x.fillText(s, px, py); };
    if (id === "hudRadar") {                                    // seamless pipe bundle, end view -> pipes spread apart
      const cx = w / 2, cy = h / 2 + 6, r = Math.min(w, h) * .085;
      const P = [[0, 0]]; for (let k = 0; k < 6; k++) P.push([Math.cos(k * Math.PI / 3) * 2.05, Math.sin(k * Math.PI / 3) * 2.05]);
      for (let k = 0; k < 6; k++) P.push([Math.cos(k * Math.PI / 3 + Math.PI / 6) * 3.55, Math.sin(k * Math.PI / 3 + Math.PI / 6) * 3.55]);
      P.forEach(([a, b], i) => { const k = 1 + e * .9, px = cx + a * r * k, py = cy + b * r * k;
        for (let d = 3; d >= 0; d--) { x.strokeStyle = col(.12 + (3 - d) * .05); x.beginPath(); x.arc(px + d * r * .35, py - d * r * .25, r, 0, 7); x.stroke(); }
        x.strokeStyle = col(.95); x.lineWidth = 1.4; x.beginPath(); x.arc(px, py, r, 0, 7); x.stroke(); x.lineWidth = 1;
        x.strokeStyle = gl(.6); x.beginPath(); x.arc(px, py, r * .74, 0, 7); x.stroke();
        if (e > .4 && i < 7) lab(String(i + 1).padStart(2, "0"), px - 5, py + 3, "left", e); });
      lab("SEAMLESS PIPE BUNDLE", 10, 16); lab(e > .1 ? `SPREAD ${Math.round(e * 100)}%` : "OD 6–168 MM", w - 10, 16, "right", .7);
    } else if (id === "hudGlobe") {                             // coil reel -> strand unspools as it explodes
      const cx = w * .42, cy = h / 2 + 4, R = Math.min(w * .28, h * .36);
      reel(x, cx, cy, R, col, t, 1);
      if (e > .02) { x.strokeStyle = gl(.95); x.lineWidth = 2; x.beginPath(); x.moveTo(cx + R * .45, cy - R * .6);
        for (let k = 0; k <= 30; k++) { const f = k / 30; x.lineTo(cx + R * .45 + f * (w * .55) * e, cy - R * .6 + Math.sin(f * 9 + t * 3) * 6 * e + f * R * .9 * e); } x.stroke(); }
      lab("COIL REEL · TUBING", 10, 16); lab(e > .1 ? `UNSPOOLED ${Math.round(e * 100)}%` : "WOUND", w - 10, 16, "right", .7);
    } else if (id === "hudWave") {                              // fittings set -> parts move to the four corners
      const cx = w / 2, cy = h / 2 + 6, S = Math.min(w, h) * .2, d = e * Math.min(w, h) * .22;
      elbow(x, cx - S * 1.2 - d, cy - S * .6 - d * .6, S, col); tee(x, cx + S * .9 + d, cy - S * .4 - d * .6, S * .8, col);
      flange(x, cx - S * .7 - d, cy + S * .8 + d * .5, S * .8, col); reducer(x, cx + S * .3 + d, cy + S * .7 + d * .5, S * .9, col);
      if (e > .4) { lab("ELBOW", 8, cy - S - d * .6, "left", e); lab("TEE", w - 8, cy - S - d * .6, "right", e); lab("FLANGE", 8, h - 22, "left", e); lab("REDUCER", w - 8, h - 22, "right", e); }
      lab("FITTINGS · FLANGES", 10, 16); lab(e > .1 ? `EXPLODED ${Math.round(e * 100)}%` : "ASSEMBLED", w - 10, 16, "right", .7);
    } else if (id === "hudNet") {                               // nuclear plant + fighter jet -> they separate
      const cy = h * .62, H = h * .42;
      tower(x, w * .3 - e * w * .12, cy, H, col, t); tower(x, w * .48 - e * w * .06, cy + 4, H * 1.08, col, t + 1.3);
      x.strokeStyle = col(.4); x.beginPath(); x.moveTo(8, cy + 8); x.lineTo(w - 8, cy + 8); x.stroke();
      const jf = (t * .12) % 1; jet(x, w * (.55 + e * .25) + Math.sin(t) * 6, h * (.3 - e * .1) + Math.cos(t * 1.3) * 4, Math.min(w, h) * .022, -.35, gl, 1);
      lab("NUCLEAR · AEROSPACE", 10, 16); lab(e > .1 ? `SEPARATED ${Math.round(e * 100)}%` : "ASME III · AS9100", w - 10, 16, "right", .7);
      lab("Ti / Ni-ALLOY · 316L · 304L", 10, h - 6, "left", .55);
    }
  }
  const SIDE_IDS = ["hudRadar", "hudGlobe", "hudWave", "hudNet"];
  function sideAt(clientX, clientY){
    for (const id of SIDE_IDS) { const el = document.getElementById(id); if (!el || el.offsetParent === null) continue;
      const r = el.getBoundingClientRect(); if (clientX >= r.left && clientX <= r.right && clientY >= r.top && clientY <= r.bottom) return id; }
    return null;
  }

  /* ---------- ASSEMBLY screen (works with mouse / touch too) */
  function panelHtml(){
    return `<div class="atl"><div class="atlb"><button type="button" data-atl="explode">⤢ EXPLODE</button><button type="button" data-atl="assemble">⤡ ASSEMBLE</button><button type="button" data-atl="reset">↺ ALL PARTS</button></div>`
      + `<div class="atlg">` + PARTS.map((p, i) => `<button type="button" class="atlp${st.removed.has(p.id) ? " off" : ""}" data-atl-part="${p.id}" title="${st.removed.has(p.id) ? "Fit back" : "Remove"} ${p.label}"><span>${String(i + 1).padStart(2, "0")} ${p.short}</span><b>${st.removed.has(p.id) ? "✕" : "✓"}</b></button>`).join("")
      + `</div><small>✋ apart = explode · together = assemble · pinch a part = remove / fit</small></div>`;
  }
  listeners.push(() => document.querySelectorAll(".hp .atl").forEach(el => { el.outerHTML = panelHtml(); }));
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-atl], [data-atl-part]"); if (!b) return;
    e.stopPropagation();
    if (b.dataset.atlPart) return toggle(b.dataset.atlPart);
    const a = b.dataset.atl;
    if (a === "explode") { setExplode("core", 1); SIDE_IDS.forEach(id => setExplode(id, 1)); if (typeof HoloAudio !== "undefined") HoloAudio.whoosh(); }
    if (a === "assemble") { setExplode("core", 0); SIDE_IDS.forEach(id => setExplode(id, 0)); if (typeof HoloAudio !== "undefined") HoloAudio.scene(); }
    if (a === "reset") { st.removed.clear(); changed(); }
  }, true);

  return { on, draw, pick, toggle, setExplode, getExplode, sideDraw, sideAt, panelHtml, PARTS };
})();
