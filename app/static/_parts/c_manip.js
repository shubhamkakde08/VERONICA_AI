/* ================================================================ MANIP - move / zoom / focus any screen by mouse
   Side screens (radar, globe, …) and hologram panels:
     drag from anywhere on it = move it          · mouse wheel on a side screen (Ctrl+wheel on a panel) = zoom in / out
     double-click = pull it to the centre big ("assemble") · double-click again / Esc / click outside = send it back
     right-click = put it back exactly where it was
   Hand gestures use the same handles (Manip.move / Manip.focus) so mouse and hands behave alike. */
const Manip = (() => {
  const MOV = ".hudc, .hp:not(.out)";
  const css = document.createElement("style");
  css.textContent = `
  .hudc,.hp{touch-action:none}
  .mdrag{cursor:grabbing!important;z-index:50!important;transition:none!important}
  .hudc{transition:scale .12s ease-out}
  .col.mout{overflow:visible!important}
  .mfocus{position:fixed!important;left:50%!important;top:50%!important;width:min(78vw,1100px)!important;height:min(76vh,760px)!important;
    translate:-50% -50% !important;scale:1!important;z-index:9000!important;animation:mAssemble .55s cubic-bezier(.2,.9,.25,1.05) both;
    box-shadow:0 0 0 1px color-mix(in srgb,var(--ac) 55%,transparent),0 0 60px color-mix(in srgb,var(--ac) 35%,transparent)!important}
  .mfocus.mleave{animation:mDisassemble .38s cubic-bezier(.6,0,.8,.4) both}
  #mVeil{position:fixed;inset:0;z-index:8999;background:radial-gradient(circle at 50% 50%,rgba(0,40,70,.35),rgba(0,0,0,.72));backdrop-filter:blur(3px);
    animation:mVeil .4s ease-out both}
  #mVeil.mleave{animation:mVeil .3s ease-in reverse both}
  @keyframes mAssemble{0%{opacity:0;scale:.18;filter:blur(8px) brightness(2.2);clip-path:inset(48% 48% 48% 48%)}
    45%{opacity:1;filter:blur(1px) brightness(1.6);clip-path:inset(0 0 0 0)}100%{opacity:1;scale:1;filter:none;clip-path:inset(0 0 0 0)}}
  @keyframes mDisassemble{0%{opacity:1;scale:1;filter:none}60%{opacity:.7;filter:blur(2px) brightness(1.8);clip-path:inset(20% 0 20% 0)}
    100%{opacity:0;scale:.2;filter:blur(8px);clip-path:inset(50% 0 50% 0)}}
  @keyframes mVeil{from{opacity:0}to{opacity:1}}
  .mhint{position:fixed;z-index:9001;left:50%;bottom:22px;translate:-50% 0;padding:6px 14px;border-radius:999px;font:600 11.5px var(--ui,sans-serif);
    color:var(--tx);background:rgba(3,10,20,.85);border:1px solid var(--line2);pointer-events:none;animation:mVeil .3s both}
  @media (prefers-reduced-motion:reduce){.mfocus,.mfocus.mleave,#mVeil{animation:none}}`;
  document.head.appendChild(css);
  const sfx = name => { try { if (typeof HoloAudio !== "undefined" && HoloAudio[name]) HoloAudio[name](); } catch {} };
  const isHp = el => el.classList.contains("hp");
  const blocked = t => t.closest("button, a, input, select, textarea, label, .x, [contenteditable], .hb2 table");
  const scrollsY = (t, root) => { for (let e = t; e && e !== root.parentElement; e = e.parentElement) { const s = getComputedStyle(e);
    if (/(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 4) return true; } return false; };

  // ---------- move (translate for side screens, left/top for hologram panels which are already positioned)
  function startPos(el){ if (isHp(el)) return { l: parseFloat(el.style.left) || el.offsetLeft, t: parseFloat(el.style.top) || el.offsetTop };
    const [x = "0", y = "0"] = (el.style.translate || "0 0").split(" "); return { x: parseFloat(x) || 0, y: parseFloat(y) || 0 }; }
  function move(el, p0, dx, dy){ if (isHp(el)) { el.style.left = Math.round(p0.l + dx) + "px"; el.style.top = Math.round(p0.t + dy) + "px"; }
    else { el.style.translate = `${Math.round(p0.x + dx)}px ${Math.round(p0.y + dy)}px`; mark(el); } }
  function mark(el){ const c = el.closest(".col"); if (!c) return;                       // a moved screen may leave its column
    c.classList.toggle("mout", [...c.querySelectorAll(".hudc")].some(h => h.style.translate || h.style.scale)); }
  function zoom(el, f){ const s = Math.max(.55, Math.min(2.6, (parseFloat(el.style.scale) || 1) * f));
    el.style.scale = Math.abs(s - 1) < .04 ? "" : s.toFixed(3); el.style.zIndex = el.style.scale ? 40 : ""; mark(el); return s; }
  function reset(el){ el.style.translate = ""; el.style.scale = ""; el.style.rotate = ""; el.style.zIndex = "";
    if (isHp(el) && el.dataset.ml !== undefined) { el.style.left = el.dataset.ml; el.style.top = el.dataset.mt; } mark(el); }

  // ---------- focus: assemble a screen in the centre, disassemble it back
  let focused = null, veil = null;
  function focus(el){
    if (focused) return unfocus();
    if (!el || isHp(el) && el.classList.contains("focus")) return;
    focused = el; veil = document.createElement("div"); veil.id = "mVeil"; veil.onclick = unfocus; document.body.appendChild(veil);
    el.classList.remove("mleave"); el.classList.add("mfocus"); sfx("whoosh"); sfx("open");
    hint("double-click, Esc or click outside to send it back");
  }
  function unfocus(){
    if (!focused) return; const el = focused, v = veil; focused = veil = null; sfx("whoosh");
    el.classList.add("mleave"); v && v.classList.add("mleave");
    setTimeout(() => { el.classList.remove("mfocus", "mleave"); v && v.remove(); }, 380);
  }
  let hintEl = null, hintT = 0;
  function hint(t){ if (!hintEl) { hintEl = document.createElement("div"); hintEl.className = "mhint"; document.body.appendChild(hintEl); }
    hintEl.textContent = t; hintEl.hidden = false; clearTimeout(hintT); hintT = setTimeout(() => { hintEl.hidden = true; }, 2600); }

  // ---------- mouse
  let drag = null;
  addEventListener("pointerdown", e => {
    if (e.button !== 0 || e.pointerType === "touch" && e.isPrimary === false) return;
    const el = e.target.closest(MOV); if (!el || el.classList.contains("mfocus") || blocked(e.target)) return;
    if (isHp(el) && !e.target.closest("header") && scrollsY(e.target, el)) return;        // let a panel's list scroll
    if (isHp(el) && el.dataset.ml === undefined) { el.dataset.ml = el.style.left; el.dataset.mt = el.style.top; }
    drag = { el, x: e.clientX, y: e.clientY, p0: startPos(el), on: false, id: e.pointerId };
  }, true);
  addEventListener("pointermove", e => {
    if (!drag || e.pointerId !== drag.id) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.on && Math.hypot(dx, dy) < 6) return;
    if (!drag.on) { drag.on = true; drag.el.classList.add("mdrag"); try { drag.el.setPointerCapture(e.pointerId); } catch {} }
    move(drag.el, drag.p0, dx, dy); e.preventDefault();
  }, true);
  const end = e => { if (!drag) return; if (drag.on) { drag.el.classList.remove("mdrag"); const stop = ev => { ev.stopPropagation(); ev.preventDefault(); };
    addEventListener("click", stop, { capture: true, once: true }); setTimeout(() => removeEventListener("click", stop, true), 50); } drag = null; };
  addEventListener("pointerup", end, true); addEventListener("pointercancel", end, true);
  addEventListener("wheel", e => {
    const el = e.target.closest(MOV); if (!el || el.classList.contains("mfocus")) return;
    if (isHp(el) && !e.ctrlKey) return;                                                      // panels: Ctrl + wheel (wheel alone scrolls them)
    e.preventDefault(); const s = zoom(el, e.deltaY < 0 ? 1.1 : 1 / 1.1); hint(`zoom ${Math.round(s * 100)}%  ·  right-click = reset`);
  }, { passive: false, capture: true });
  addEventListener("dblclick", e => {
    const el = e.target.closest(".hudc, .mfocus"); if (!el || blocked(e.target)) return;
    e.preventDefault(); el.classList.contains("mfocus") ? unfocus() : focus(el);
  }, true);
  addEventListener("contextmenu", e => { const el = e.target.closest(MOV); if (!el || !(el.style.translate || el.style.scale || el.dataset.ml !== undefined)) return;
    e.preventDefault(); reset(el); hint("back in place"); }, true);
  addEventListener("keydown", e => { if (e.key === "Escape" && focused) { unfocus(); } }, true);
  return { move, startPos, zoom, focus, unfocus, reset, get focused(){ return focused; } };
})();
