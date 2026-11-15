/* ================================================================ RAIL - left menu: open / mini / hidden, theme flyout, edge peek
   Ctrl+B = open <-> mini (or bring it back when hidden) · Ctrl+Shift+B = hide · hover the left edge = peek while hidden */
const Rail = (() => {
  const B = document.body, desk = () => matchMedia("(min-width:901px)").matches;
  const TH = {
    aurora: ["Aurora", "Premium particle core", "radial-gradient(circle at 50% 55%,#ffcf7a 0 6%,#3a6ea8 20%,#0b1a30 60%,#050a14)"],
    arc:    ["Arc", "Iron-Man reactor HUD", "radial-gradient(circle at 50% 50%,#e6fbff 0 5%,#3fd8ff 14%,transparent 16%,transparent 26%,#ffb547 27% 29%,#031424 31%)"],
    holo:   ["Holo", "Hologram workspace", "linear-gradient(135deg,#02131f,#06324a 50%,#ffb547 160%),repeating-linear-gradient(0deg,rgba(120,230,255,.18) 0 1px,transparent 1px 8px)"],
    forge:  ["Forge", "Solid 3D steel", "linear-gradient(160deg,#0b2540,#2c6aa0 45%,#c9d6e2 70%,#0a1a2c)"],
    titan:  ["Titan", "Blueprint hologram", "repeating-linear-gradient(90deg,rgba(85,185,255,.35) 0 1px,transparent 1px 10px),repeating-linear-gradient(0deg,rgba(85,185,255,.35) 0 1px,transparent 1px 10px),#041a33"],
    atlas:  ["Atlas", "Product hologram", "radial-gradient(circle at 50% 60%,#9be3ff 0 4%,#1d6fb8 18%,#062042 45%,#020b18)"],
  };
  const seg = $(".top .seg"), thBtn = $("#thBtn");
  seg.querySelectorAll("button").forEach(b => { const t = TH[b.dataset.theme]; if (!t) return; b.style.setProperty("--pv", t[2]); b.dataset.d = t[1]; b.removeAttribute("title"); });
  function syncTheme(){ const on = seg.querySelector("button.on"), t = TH[on?.dataset.theme] || TH.aurora;
    $("#thName").textContent = t[0]; $("#thSw").style.setProperty("--sw", t[2]); }
  new MutationObserver(syncTheme).observe(seg, { subtree: true, attributes: true, attributeFilter: ["class"] }); syncTheme();
  function flyout(open){ if (!desk()) return; open = open ?? !seg.classList.contains("open");
    if (open) { const r = thBtn.getBoundingClientRect(), h = seg.offsetHeight || 300; seg.style.top = Math.max(10, Math.min(innerHeight - h - 10, r.top - 20)) + "px"; }
    seg.classList.toggle("open", open); thBtn.setAttribute("aria-expanded", open); }
  thBtn.onclick = e => { e.stopPropagation(); flyout(); };
  seg.addEventListener("click", e => { if (e.target.closest("button")) setTimeout(() => flyout(false), 120); });
  addEventListener("pointerdown", e => { if (seg.classList.contains("open") && !e.target.closest(".thwrap")) flyout(false); }, true);

  // ---- state
  const KEY = "rb_rail";
  function set(m){ m = ["open", "mini", "hidden"].includes(m) ? m : "open";
    B.classList.toggle("rail-mini", m === "mini"); B.classList.toggle("rail-hidden", m === "hidden"); B.classList.remove("rail-peek");
    $("#railTog").title = m === "mini" ? "Expand menu  (Ctrl+B)" : "Collapse menu  (Ctrl+B)"; flyout(false);
    store.set(KEY, m); setTimeout(() => dispatchEvent(new Event("resize")), 380); }
  const mode = () => B.classList.contains("rail-hidden") ? "hidden" : B.classList.contains("rail-mini") ? "mini" : "open";
  set(store.get(KEY) || "open");
  $("#railTog").onclick = () => set(mode() === "mini" ? "open" : "mini");
  $("#railHide").onclick = () => { store.set("rb_rail_last", mode()); set("hidden"); };
  $("#railHandle").onclick = () => set(store.get("rb_rail_last") || "open");
  addEventListener("keydown", e => { if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "b" || !desk()) return; e.preventDefault();
    if (e.shiftKey) { store.set("rb_rail_last", mode() === "hidden" ? "open" : mode()); return set(mode() === "hidden" ? "open" : "hidden"); }
    set(mode() === "hidden" ? (store.get("rb_rail_last") || "open") : mode() === "mini" ? "open" : "mini"); });
  // peek while hidden: hover the left edge, leave the menu to slide it away again
  let pt = 0;
  $("#railPeek").addEventListener("pointerenter", () => { clearTimeout(pt); pt = setTimeout(() => B.classList.add("rail-peek"), 180); });
  $("#railPeek").addEventListener("pointerleave", () => clearTimeout(pt));
  $("#rail").addEventListener("pointerleave", () => { if (B.classList.contains("rail-peek") && !seg.classList.contains("open") && $("#sndPop").hidden) pt = setTimeout(() => B.classList.remove("rail-peek"), 350); });
  $("#rail").addEventListener("pointerenter", () => clearTimeout(pt));
  // active state for the tool buttons that open something
  new MutationObserver(() => $("#panelsBtn").classList.toggle("on", B.classList.contains("drawer"))).observe(B, { attributes: true, attributeFilter: ["class"] });
  function who(me){ if (!me) return; $("#railName").textContent = me.name || ""; $("#railRole").textContent = me.role || ""; }
  return { set, mode, who };
})();
