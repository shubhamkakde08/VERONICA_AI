/* ================================================================ FORGE theme - solid 3D metal hologram (Three.js, served locally)
   Centre screen : a piping SPOOL in shiny steel turning 360°. It is taken apart the way a fitter would -
                   welds glow, bolts back out, flanges slide off, pipes slide apart along their line, tee drops,
                   branch lifts, elbow swings out - holds with numbered parts + BILL OF MATERIALS, then goes back.
   Side screens  : seamless pipe bundle (pipes slide out one by one) · coil reel (spinning, tube unspooling) ·
                   fittings carousel · FIGHTER JET (barrel roll -> SONIC BOOM vapour cone + boom sound + shake,
                   then the jet opens into its modules with its bill of materials).
   One WebGL renderer draws every screen (scissor viewports) and copies them onto the screens' own canvases. */
const Forge3D = (() => {
  let ready = false, loading = false, failed = false, T = null, R = null, glc = null, t0 = performance.now(), lastF = 0, now_t = 0;
  const S = {};                                            // the five scenes
  const on = () => document.body.classList.contains("theme-forge") && !document.hidden;
  const smooth = v => v <= 0 ? 0 : v >= 1 ? 1 : v * v * (3 - 2 * v);
  const seg = (u, a, b) => smooth((u - a) / (b - a));

  function load(){
    if (ready || loading || failed) return; loading = true;
    const s = document.createElement("script"); s.src = "/vendor/three.min.js";
    s.onload = () => { try { T = window.THREE; build(); ready = true; } catch (e) { failed = true; console.warn("Forge3D", e); } loading = false; };
    s.onerror = () => { failed = true; loading = false; };
    document.head.appendChild(s);
  }

  /* ---------------- materials */
  let ENV = null;
  function envMap(){                                       // small studio-like cube map drawn on canvases (no image files)
    const faces = [0, 1, 2, 3, 4, 5].map(i => { const c = document.createElement("canvas"); c.width = c.height = 64; const x = c.getContext("2d");
      const g = x.createLinearGradient(0, 0, 0, 64);
      if (i === 2) { g.addColorStop(0, "#dff3ff"); g.addColorStop(1, "#7fb6e6"); } else if (i === 3) { g.addColorStop(0, "#04101f"); g.addColorStop(1, "#020812"); }
      else { g.addColorStop(0, "#9fd0ff"); g.addColorStop(.45, "#2a5d93"); g.addColorStop(.55, "#0a1e38"); g.addColorStop(1, "#030b18"); }
      x.fillStyle = g; x.fillRect(0, 0, 64, 64);
      if (i < 2 || i > 3) { x.fillStyle = "rgba(255,255,255,.85)"; x.fillRect(12 + i * 4, 10, 10, 26); }    // soft-box highlights -> shiny steel
      return c; });
    const cube = new T.CubeTexture(faces); cube.needsUpdate = true;
    const pm = new T.PMREMGenerator(R); const env = pm.fromCubemap(cube).texture; pm.dispose(); return env;
  }
  const MAT = {};
  function mats(){
    ENV = envMap();
    MAT.steel = new T.MeshStandardMaterial({ color: 0xc3d3e3, metalness: 1, roughness: .24, envMap: ENV, envMapIntensity: 1.25 });
    MAT.dark = new T.MeshStandardMaterial({ color: 0x8aa2bb, metalness: 1, roughness: .38, envMap: ENV, envMapIntensity: 1 });
    MAT.bolt = new T.MeshStandardMaterial({ color: 0xd8c38f, metalness: 1, roughness: .3, envMap: ENV, envMapIntensity: 1.1 });
    MAT.weld = new T.MeshStandardMaterial({ color: 0x9fdcff, metalness: .6, roughness: .35, envMap: ENV, emissive: 0x2a8cff, emissiveIntensity: .25 });
    MAT.jet = new T.MeshStandardMaterial({ color: 0x9fb2c6, metalness: .85, roughness: .32, envMap: ENV, envMapIntensity: 1.1 });
    MAT.glass = new T.MeshStandardMaterial({ color: 0x9fe6ff, metalness: .2, roughness: .05, envMap: ENV, transparent: true, opacity: .55 });
    MAT.edge = new T.LineBasicMaterial({ color: 0x5cc4ff, transparent: true, opacity: .5, blending: T.AdditiveBlending, depthWrite: false });
    MAT.cone = new T.MeshBasicMaterial({ color: 0xe8f6ff, transparent: true, opacity: .0, blending: T.AdditiveBlending, depthWrite: false, side: T.DoubleSide });
    MAT.flame = new T.MeshBasicMaterial({ color: 0x8fd8ff, transparent: true, opacity: .8, blending: T.AdditiveBlending, depthWrite: false });
    MAT.ring = new T.MeshBasicMaterial({ color: 0x4fb3ff, transparent: true, opacity: .55, blending: T.AdditiveBlending, depthWrite: false, side: T.DoubleSide });
  }
  function mesh(geo, mat = MAT.steel, edges = true){
    const g = new T.Group(), m = new T.Mesh(geo, mat); g.add(m);
    if (edges) g.add(new T.LineSegments(new T.EdgesGeometry(geo, 35), MAT.edge));
    return g;
  }
  const cylX = (r1, r2, len, seg = 36) => { const g = new T.CylinderGeometry(r2, r1, len, seg, 1, false); g.rotateZ(-Math.PI / 2); return g; };
  const pipeX = (ro, ri, len) => { const s = new T.Shape(); s.absarc(0, 0, ro, 0, Math.PI * 2); const h = new T.Path(); h.absarc(0, 0, ri, 0, Math.PI * 2, true); s.holes.push(h);
    const g = new T.ExtrudeGeometry(s, { depth: len, bevelEnabled: false, curveSegments: 40 }); g.rotateY(Math.PI / 2); g.translate(-len / 2, 0, 0); return g; };
  function flangeGeo(r = .62, t = .13, hubR = .4, hubL = .24, bore = .27){
    const p = [[bore, 0], [r, 0], [r, t], [hubR, t], [bore + .06, t + hubL], [bore, t + hubL]].map(([a, b]) => new T.Vector2(a, b));
    return new T.LatheGeometry(p, 48);
  }
  function stage(cam){
    const sc = new T.Scene();
    sc.add(new T.HemisphereLight(0x9fd6ff, 0x061224, .55));
    const key = new T.DirectionalLight(0xffffff, 1.1); key.position.set(4, 6, 5); sc.add(key);
    const rim = new T.DirectionalLight(0x4fb3ff, 1.4); rim.position.set(-5, 2, -6); sc.add(rim);
    const fill = new T.PointLight(0x2f86ff, .9, 30); fill.position.set(0, -3, 3); sc.add(fill);
    return { sc, cam };
  }
  function platform(sc, r = 3.2, y = -1.6){
    const g = new T.Group();
    for (const [rr, w, o] of [[r, .03, .75], [r * 1.12, .015, .45], [r * 1.35, .04, .3]]) {
      const m = new T.Mesh(new T.RingGeometry(rr, rr + w, 128), MAT.ring.clone()); m.material.opacity = o; m.rotation.x = -Math.PI / 2; g.add(m); }
    const disc = new T.Mesh(new T.CircleGeometry(r, 64), new T.MeshBasicMaterial({ color: 0x0e3a6e, transparent: true, opacity: .12, blending: T.AdditiveBlending, depthWrite: false }));
    disc.rotation.x = -Math.PI / 2; g.add(disc);
    const beam = new T.Mesh(new T.CylinderGeometry(r * .92, r, 4.2, 64, 1, true), new T.MeshBasicMaterial({ color: 0x2f86ff, transparent: true, opacity: .025, blending: T.AdditiveBlending, depthWrite: false, side: T.DoubleSide }));
    beam.position.y = 2.1; g.add(beam);
    g.position.y = y; sc.add(g); return g;
  }

  /* ---------------- centre: piping layout (as in the reference) - pipes, elbows, 3 gate valves with handwheels,
     basket strainer on the riser, flanged joints with gaskets + studs, U-bolt pipe supports on a grid floor */
  function spool(){
    const cam = new T.PerspectiveCamera(34, 1.6, .1, 100); cam.position.set(0, 3.4, 15); cam.lookAt(0, .5, 0);
    const st = stage(cam), root = new T.Group(); st.sc.add(root);
    const grid = new T.GridHelper(10, 40, 0x2aa8d8, 0x154a66); grid.material.transparent = true; grid.material.opacity = .45; grid.position.y = -1.05; root.add(grid);
    const fl = new T.Mesh(new T.PlaneGeometry(10, 10), new T.MeshBasicMaterial({ color: 0x06263f, transparent: true, opacity: .35, depthWrite: false })); fl.rotation.x = -Math.PI / 2; fl.position.y = -1.06; root.add(fl);
    st.plat = new T.Group(); st.sc.add(st.plat);
    const teal = new T.MeshStandardMaterial({ color: 0x3fb4c9, metalness: .75, roughness: .3, envMap: ENV, envMapIntensity: 1.1, emissive: 0x0a3a4a, emissiveIntensity: .5 });
    const tealD = new T.MeshStandardMaterial({ color: 0x2c93a8, metalness: .75, roughness: .35, envMap: ENV, emissive: 0x08303c, emissiveIntensity: .5 });
    const yel = new T.MeshStandardMaterial({ color: 0xffd23f, metalness: .4, roughness: .35, emissive: 0x6a4a00, emissiveIntensity: .6 });
    const org = new T.MeshStandardMaterial({ color: 0xff8a2a, metalness: .2, roughness: .5, emissive: 0xff5a00, emissiveIntensity: .45 });
    const glass = new T.MeshStandardMaterial({ color: 0xbfe8a8, metalness: .1, roughness: .1, transparent: true, opacity: .55, emissive: 0x3a5a20, emissiveIntensity: .4 });
    const boltM = new T.MeshStandardMaterial({ color: 0xdff6ff, metalness: .9, roughness: .25, envMap: ENV });
    const r = .17, parts = [], V = (x, y, z) => new T.Vector3(x, y, z);
    const add = (n, obj, dir, dist, step) => { root.add(obj); parts.push({ n, obj, base: obj.position.clone(), dir: dir.clone().normalize(), dist, step }); return obj; };
    const pipe = (a, b, rr = r, m = teal) => { const d = new T.Vector3().subVectors(b, a), g = new T.CylinderGeometry(rr, rr, d.length(), 28, 1, false), o = mesh(g, m);
      o.position.copy(a).addScaledVector(d, .5); o.quaternion.setFromUnitVectors(V(0, 1, 0), d.clone().normalize()); return o; };
    const disc = (ax, rad, th, m) => { const g = new T.CylinderGeometry(rad, rad, th, 32); const o = mesh(g, m, m !== org); if (ax === "x") o.rotation.z = Math.PI / 2; return o; };
    const bolts = (ax, rr = .27, n = 8, len = .34) => { const g = new T.Group(); for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2, c = Math.cos(a) * rr, s = Math.sin(a) * rr;
        const b = new T.Mesh(new T.CylinderGeometry(.022, .022, len, 8), boltM); const nut1 = new T.Mesh(new T.SphereGeometry(.04, 8, 6), boltM), nut2 = nut1.clone();
        if (ax === "x") { b.rotation.z = Math.PI / 2; b.position.set(0, c, s); nut1.position.set(-len / 2, c, s); nut2.position.set(len / 2, c, s); }
        else { b.position.set(c, 0, s); nut1.position.set(c, -len / 2, s); nut2.position.set(c, len / 2, s); }
        g.add(b, nut1, nut2); } return g; };
    // flanged joint at p along axis: flange | gasket | flange + bolts  -> 3 parts that come apart
    const joint = (p, ax, sign = 1) => {
      const off = ax === "x" ? V(.07, 0, 0) : V(0, .07, 0);
      const f1 = disc(ax, .33, .07, tealD); f1.position.copy(p).sub(off); add(4, f1, ax === "x" ? V(-1, 0, 0) : V(0, -1, 0), .45, 2);
      const g = disc(ax, .3, .025, org); g.position.copy(p); add(5, g, V(0, 0, 1), .9, 2);
      const f2 = disc(ax, .33, .07, tealD); f2.position.copy(p).add(off); add(4, f2, ax === "x" ? V(1, 0, 0) : V(0, 1, 0), .45, 2);
      const b = bolts(ax); b.position.copy(p); add(6, b, V(0, 0, 1).multiplyScalar(sign), 1.6, 1);
    };
    const valve = (p, ax) => {                               // gate valve: body + bonnet + stem + yellow handwheel
      const g = new T.Group(); g.position.copy(p);
      const body = mesh(new T.SphereGeometry(.3, 28, 18), tealD); body.scale.set(ax === "x" ? 1.25 : 1, ax === "x" ? 1 : 1.25, 1); g.add(body);
      const bon = mesh(new T.CylinderGeometry(.13, .17, .38, 20), tealD); bon.position.y = .42; g.add(bon);
      const stem = new T.Mesh(new T.CylinderGeometry(.025, .025, .5, 8), boltM); stem.position.y = .82; g.add(stem);
      const wheel = new T.Group(); const rim = new T.Mesh(new T.TorusGeometry(.26, .03, 10, 36), yel); rim.rotation.x = Math.PI / 2; wheel.add(rim);
      for (let i = 0; i < 4; i++) { const sp = new T.Mesh(new T.CylinderGeometry(.015, .015, .52, 6), yel); sp.rotation.z = Math.PI / 2; sp.rotation.y = i * Math.PI / 4; wheel.add(sp); }
      wheel.position.y = 1.05; g.add(wheel); g.userData.wheel = wheel;
      return add(3, g, V(0, 1, 0), 1.3, 2);
    };
    const supp = (x, z, yTop, yBot = -1.05) => { const g = new T.Group();
      const post = new T.Mesh(new T.CylinderGeometry(.05, .05, yTop - yBot - .2, 12), tealD); post.position.set(x, (yTop + yBot) / 2 - .1, z); g.add(post);
      const base = mesh(new T.BoxGeometry(.42, .05, .42), tealD); base.position.set(x, yBot + .03, z); g.add(base);
      const cap = mesh(new T.BoxGeometry(.3, .04, .22), tealD); cap.position.set(x, yTop - .2, z); g.add(cap);
      const u = new T.Mesh(new T.TorusGeometry(.19, .018, 8, 24, Math.PI), boltM); u.position.set(x, yTop - .2, z); u.rotation.y = Math.PI / 2; g.add(u);
      return add(7, g, V(0, -1, 0), .9, 4); };

    // lower line  (y = 0)
    joint(V(-3.7, 0, 0), "x", 1);
    add(1, pipe(V(-3.62, 0, 0), V(-2.05, 0, 0)), V(-1, 0, 0), .6, 3);
    joint(V(-1.98, 0, 0), "x", -1); valve(V(-1.55, 0, 0), "x"); joint(V(-1.12, 0, 0), "x", 1);
    add(1, pipe(V(-1.05, 0, 0), V(.83, 0, 0)), V(0, -1, 0), .5, 3);
    const e1 = mesh(new T.TorusGeometry(.32, r, 22, 32, Math.PI / 2), teal); e1.position.set(.83, .32, 0); e1.rotation.z = -Math.PI / 2; add(2, e1, V(1, -1, 0), .6, 3);
    // riser  (x = 1.15)
    add(1, pipe(V(1.15, .32, 0), V(1.15, .78, 0)), V(1, 0, 0), .5, 3);
    joint(V(1.15, .85, 0), "y", 1);
    const str = new T.Group(); str.position.set(1.15, 1.3, 0);                    // basket strainer (glass body, orange screen)
    const sb = mesh(new T.CylinderGeometry(.34, .34, .62, 32), glass); sb.rotation.x = Math.PI / 2; str.add(sb);
    for (const z of [-.33, .33]) { const fr = disc("x", .38, .06, tealD); fr.rotation.set(Math.PI / 2, 0, 0); fr.position.z = z; str.add(fr); }
    for (let i = 0; i < 5; i++) { const ring = new T.Mesh(new T.TorusGeometry(.24, .015, 6, 28), org); ring.position.z = -.2 + i * .1; str.add(ring); }
    str.rotation.y = -.55; add(8, str, V(-1, .2, 1), 1.4, 2);
    joint(V(1.15, 1.75, 0), "y", -1);
    add(1, pipe(V(1.15, 1.82, 0), V(1.15, 2.55, 0)), V(1, 0, 0), .5, 3);
    const e2 = mesh(new T.TorusGeometry(.32, r, 22, 32, Math.PI / 2), teal); e2.position.set(1.47, 2.55, 0); e2.rotation.z = Math.PI / 2; add(2, e2, V(-1, 1, 0), .6, 3);
    // upper line  (y = 2.87)
    add(1, pipe(V(1.47, 2.87, 0), V(2.55, 2.87, 0)), V(0, 1, 0), .5, 3);
    joint(V(2.62, 2.87, 0), "x", -1); valve(V(3.05, 2.87, 0), "x"); joint(V(3.48, 2.87, 0), "x", 1);
    add(1, pipe(V(3.55, 2.87, 0), V(4.6, 2.87, 0)), V(1, 0, 0), .6, 3);
    joint(V(4.67, 2.87, 0), "x", 1);
    // valve on the riser strainer (handwheel above it, as in the reference)
    const rv = valve(V(1.15, 2.05, .0), "y"); rv.scale.setScalar(.75); rv.position.set(.85, 1.62, .32); parts[parts.length - 1].base.copy(rv.position);
    // supports
    supp(-2.75, 0, -.0); supp(.15, 0, -.0); supp(.85, .5, 1.1); supp(4.05, 0, 2.87);
    root.position.set(-.35, -.75, 0); root.scale.setScalar(.7);
    st.root = root; st.parts = parts; st.welds = [];
    return st;
  }
  const SPOOL_BOM = [
    [1, "Seamless pipe 6\" SCH40", "A106 Gr.B / A312 TP316L", 7],
    [2, "90° LR elbow 6\"", "A234 WPB / A403 WP316L", 2],
    [3, "Gate valve 6\" Cl.150 + handwheel", "A216 WCB · API 600", 3],
    [4, "WN flange 6\" Cl.150", "A105 / A182 F316L", 12],
    [5, "Spiral-wound gasket 6\"", "SS316 / graphite", 6],
    [6, "Stud bolts + nuts", "A193 B7 / A194 2H", 48],
    [7, "Pipe support (post + U-bolt)", "IS 2062 · galvanised", 4],
    [8, "Basket strainer 6\"", "WCB body · SS304 screen", 1],
  ];
  // 15 s cycle: 0-2.5 assembled · welds 2.5-3.5 · bolts 3.5-4.7 · flanges 4.7-5.9 · pipes/tee/elbow 5.9-7.3 · branch 7.3-8.3
  // hold + BOM 8.3-11.5 · same steps back 11.5-15
  const STEP = [[2.5, 3.5], [3.5, 4.7], [4.7, 5.9], [5.9, 7.3], [7.3, 8.3]];
  function spoolAt(u, step){ const [a, b] = STEP[step]; if (u < 11.5) return seg(u, a, b);
    const back = 11.5 + (8.3 - b) * (3.5 / 5.8), dur = (b - a) * (3.5 / 5.8); return 1 - seg(u, back, back + dur); }

  /* ---------------- side: pipe bundle */
  function bundle(){
    const cam = new T.PerspectiveCamera(34, 1.3, .1, 100); cam.position.set(5.6, 2.9, 7.0); cam.lookAt(0, -.1, 0);
    const st = stage(cam), root = new T.Group(); st.sc.add(root); const pipes = [];
    const pos = [[0, 0]]; for (let i = 0; i < 6; i++) { const a = i / 6 * Math.PI * 2; pos.push([Math.cos(a) * .62, Math.sin(a) * .62]); }
    pos.forEach(([y, z], i) => { const p = mesh(pipeX(.3, .24, 3.4)); p.position.set(0, y, z); root.add(p); pipes.push(p); });
    for (const x of [-1.2, 1.2]) { const band = mesh(new T.TorusGeometry(1.0, .035, 8, 48), MAT.bolt, false); band.rotation.y = Math.PI / 2; band.position.x = x; root.add(band); }
    platform(st.sc, 2.3, -1.25); st.root = root; st.pipes = pipes; return st;
  }
  /* ---------------- side: coil reel */
  function reel(){
    const cam = new T.PerspectiveCamera(34, 1.3, .1, 100); cam.position.set(4.6, 2.5, 6.6); cam.lookAt(0, -.1, 0);
    const st = stage(cam), root = new T.Group(); st.sc.add(root);
    for (const z of [-.75, .75]) { const d = mesh(new T.CylinderGeometry(1.35, 1.35, .08, 48), MAT.dark); d.rotation.x = Math.PI / 2; d.position.z = z; root.add(d);
      for (let i = 0; i < 6; i++) { const sp = mesh(new T.BoxGeometry(.08, 1.2, .06), MAT.dark, false); sp.rotation.z = i / 6 * Math.PI; sp.position.z = z * 1.08; root.add(sp); } }
    const core = mesh(new T.CylinderGeometry(.42, .42, 1.5, 32, 1, true), MAT.dark); core.rotation.x = Math.PI / 2; root.add(core);
    const pts = []; for (let i = 0; i <= 900; i++) { const a = i / 900 * Math.PI * 2 * 14, layer = Math.floor(i / 300), z = -.65 + ((i % 300) / 300) * 1.3 * (layer % 2 ? -1 : 1) + (layer % 2 ? 1.3 : 0);
      const r = .52 + layer * .16; pts.push(new T.Vector3(Math.cos(a) * r, Math.sin(a) * r, z)); }
    const coil = new T.Mesh(new T.TubeGeometry(new T.CatmullRomCurve3(pts), 1400, .07, 8, false), MAT.steel); root.add(coil);
    const tail = new T.Mesh(new T.TubeGeometry(new T.LineCurve3(new T.Vector3(0, .9, 0), new T.Vector3(2.6, .9, 0)), 8, .07, 8, false), MAT.steel); st.sc.add(tail);
    platform(st.sc, 2.0, -1.5); st.root = root; st.tail = tail; return st;
  }
  /* ---------------- side: fittings carousel */
  function fittings(){
    const cam = new T.PerspectiveCamera(34, 1.3, .1, 100); cam.position.set(0, 2.8, 7.2); cam.lookAt(0, -.1, 0);
    const st = stage(cam), root = new T.Group(); st.sc.add(root); const items = [];
    const mk = [
      () => mesh(new T.TorusGeometry(.42, .2, 20, 32, Math.PI / 2)),
      () => { const g = new T.Group(); g.add(mesh(pipeX(.2, .16, .8), MAT.dark)); const b = mesh(new T.CylinderGeometry(.2, .2, .42, 28, 1, true), MAT.dark); b.position.y = .21; g.add(b); return g; },
      () => mesh(new T.CylinderGeometry(.12, .22, .55, 32, 1, true)),
      () => { const f = mesh(flangeGeo(.45, .1, .3, .18, .2)); return f; },
      () => mesh(new T.SphereGeometry(.22, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), MAT.dark),
      () => mesh(new T.TorusGeometry(.5, .19, 20, 24, Math.PI / 4)),
    ];
    mk.forEach((f, i) => { const g = new T.Group(); g.add(f()); const a = i / mk.length * Math.PI * 2; g.position.set(Math.cos(a) * 1.35, 0, Math.sin(a) * 1.35); root.add(g); items.push(g); });
    platform(st.sc, 2.1, -.85); st.root = root; st.items = items; return st;
  }
  /* ---------------- side: fighter jet (barrel roll, sonic boom, then opens into its modules) */
  function jet(){
    const cam = new T.PerspectiveCamera(36, 1.3, .1, 200); cam.position.set(7.8, 3.6, 10.8); cam.lookAt(-.3, -.2, 0);
    const st = stage(cam), body = new T.Group(), root = new T.Group(); root.add(body); st.sc.add(root); const mods = [];
    const add = (name, obj, dir, dist) => { body.add(obj); mods.push({ name, obj, base: obj.position.clone(), dir: dir.normalize(), dist }); };
    const V = (x, y, z) => new T.Vector3(x, y, z);
    const prof = [[0, 2.9], [.12, 2.6], [.3, 2.1], [.42, 1.4], [.48, .4], [.5, -1.2], [.46, -2.2], [.38, -2.5], [0, -2.5]].map(([r, y]) => new T.Vector2(r, y));
    const fg = new T.LatheGeometry(prof, 36); fg.rotateZ(-Math.PI / 2); const fus = mesh(fg, MAT.jet); fus.scale.set(1, .8, 1.15); add("Fuselage", fus, V(0, -1, 0), .6);
    const can = mesh(new T.SphereGeometry(.28, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), MAT.glass, false); can.scale.set(2.6, 1, 1); can.position.set(1.55, .3, 0); add("Canopy", can, V(.3, 1, 0), 1.2);
    const wing = s => { const sh = new T.Shape(); sh.moveTo(.9, 0); sh.lineTo(-1.25, s * 2.35); sh.lineTo(-1.75, s * 2.35); sh.lineTo(-1.6, 0); sh.lineTo(.9, 0);
      const g = new T.ExtrudeGeometry(sh, { depth: .06, bevelEnabled: false }); g.rotateX(Math.PI / 2); return g; };
    for (const [n, s] of [["Left wing", 1], ["Right wing", -1]]) { const w = mesh(wing(s), MAT.jet); w.position.set(-.1, .01, s * .35); add(n, w, V(0, .1, s), 1.6); }
    const fin = () => { const sh = new T.Shape(); sh.moveTo(-1.4, 0); sh.lineTo(-2.2, 1.15); sh.lineTo(-2.55, 1.15); sh.lineTo(-2.45, 0); return new T.ExtrudeGeometry(sh, { depth: .045, bevelEnabled: false }); };
    for (const [n, s] of [["Left fin", 1], ["Right fin", -1]]) { const f = mesh(fin(), MAT.jet); f.position.set(0, .25, s * .42); f.rotation.x = -s * .45; add(n, f, V(-.2, 1, s * .6), 1.4); }
    const stab = s => { const sh = new T.Shape(); sh.moveTo(-1.9, 0); sh.lineTo(-2.6, s * 1.1); sh.lineTo(-2.95, s * 1.1); sh.lineTo(-2.75, 0); const g = new T.ExtrudeGeometry(sh, { depth: .05, bevelEnabled: false }); g.rotateX(Math.PI / 2); return g; };
    for (const [n, s] of [["Left stabiliser", 1], ["Right stabiliser", -1]]) { const m = mesh(stab(s), MAT.jet); m.position.set(0, -.05, s * .3); add(n, m, V(-.4, -.2, s), 1.4); }
    for (const [n, s] of [["Left engine", 1], ["Right engine", -1]]) { const e = mesh(cylX(.2, .17, 1.8, 28), MAT.dark); e.position.set(-1.6, -.05, s * .2); add(n, e, V(-1, -.4, s * .5), 1.7);
      const fl = new T.Mesh(new T.ConeGeometry(.15, 1.1, 18, 1, true), MAT.flame); fl.rotation.z = Math.PI / 2; fl.position.set(-3.0, -.05, s * .2); body.add(fl); (st.flames = st.flames || []).push(fl); }
    // vapour cone + shock ring for the sonic boom
    const cone = new T.Mesh(new T.ConeGeometry(1.25, 2.6, 48, 1, true), MAT.cone); cone.rotation.z = Math.PI / 2; cone.position.x = .3; root.add(cone);
    const shock = new T.Mesh(new T.RingGeometry(.9, 1.0, 64), MAT.ring.clone()); shock.rotation.y = Math.PI / 2; root.add(shock); shock.material.opacity = 0;
    platform(st.sc, 2.6, -2.2);
    st.root = root; st.body = body; st.mods = mods; st.cone = cone; st.shock = shock; return st;
  }
  const JET_BOM = ["Fuselage · Ti + composite", "Canopy · polycarbonate", "Wings ×2 · Al-Li", "Fins ×2 · composite", "Stabilisers ×2", "Engines ×2 · turbofan",
                   "Hydraulic tubing · Ti-3Al-2.5V", "Fuel lines · SS 321", "Bleed-air duct · Inconel 625"];

  function build(){
    glc = document.createElement("canvas");
    R = new T.WebGLRenderer({ canvas: glc, antialias: true, alpha: true, preserveDrawingBuffer: true });
    R.setPixelRatio(1); R.outputEncoding = T.sRGBEncoding; R.toneMapping = T.ACESFilmicToneMapping; R.toneMappingExposure = .82;
    R.setClearColor(0x000000, 0); R.autoClear = false;
    mats();
    S.center = spool(); S.hudRadar = bundle(); S.hudGlobe = reel(); S.hudWave = fittings(); S.hudNet = jet();
    S.center.el = document.getElementById("forgeStage"); for (const k of ["hudRadar", "hudGlobe", "hudWave", "hudNet"]) S[k].el = document.getElementById(k);
    requestAnimationFrame(loop);
  }

  /* ---------------- sonic boom sound (synthesised, no file) */
  function boomSound(){
    let snd = true; try { snd = store.get("rb_holo_sfx") !== "0"; } catch {}
    if (!snd || typeof Voice === "undefined") return; const ctx = Voice.audioCtx(); if (!ctx) return;
    const t = ctx.currentTime, len = 1.6, buf = ctx.createBuffer(1, ctx.sampleRate * len, ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) { const k = i / d.length; d[i] = (Math.random() * 2 - 1) * Math.pow(1 - k, 2.2) * (k < .03 ? k / .03 : 1); }
    const src = ctx.createBufferSource(); src.buffer = buf; const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.setValueAtTime(900, t); lp.frequency.exponentialRampToValueAtTime(120, t + 1.2);
    const g = ctx.createGain(); g.gain.setValueAtTime(.0001, t); g.gain.exponentialRampToValueAtTime(.55, t + .02); g.gain.exponentialRampToValueAtTime(.0001, t + len);
    src.connect(lp); lp.connect(g); g.connect(ctx.destination); src.start(t); src.stop(t + len);
    const o = ctx.createOscillator(), og = ctx.createGain(); o.frequency.setValueAtTime(70, t); o.frequency.exponentialRampToValueAtTime(32, t + .5);
    og.gain.setValueAtTime(.5, t); og.gain.exponentialRampToValueAtTime(.0001, t + .6); o.connect(og); og.connect(ctx.destination); o.start(t); o.stop(t + .65);
  }

  /* ---------------- per-frame animation */
  let boomDone = -1;
  function animate(t){
    // centre spool: 360° turn + take-apart sequence
    const c = S.center, u = t % 15;
    c.root.rotation.y = t * Math.PI * 2 / 24; c.root.rotation.x = .12 + Math.sin(t * .4) * .03;
    for (const p of c.parts) { const e = spoolAt(u, p.step); p.e = e; p.obj.position.copy(p.base).addScaledVector(p.dir, e * p.dist * .72); }
    c.phase = u < 2.5 ? "ASSEMBLED" : u < 3.5 ? "INSPECTING JOINTS" : u < 4.7 ? "STUD BOLTS OUT" : u < 5.9 ? "VALVES + FLANGES OFF" : u < 7.3 ? "PIPES APART" : u < 8.3 ? "SUPPORTS DOWN" : u < 11.5 ? "EXPLODED VIEW · BOM" : u < 14.6 ? "ASSEMBLING" : "ASSEMBLED";
    for (const p of c.parts) if (p.obj.userData.wheel) p.obj.userData.wheel.rotation.y = (u > 4.7 && u < 5.9) || (u > 11.5 && u < 13) ? t * 6 : 0;   // handwheels turn while valves come off / go on
    // pipe bundle: turning, pipes slide out one after another
    const b = S.hudRadar; b.root.rotation.y = t * .35; b.root.rotation.x = Math.sin(t * .3) * .15;
    b.pipes.forEach((p, i) => { const k = (t * .45 - i * .55) % 7; p.position.x = (k > 0 && k < 2 ? Math.sin(k / 2 * Math.PI) * 1.4 : 0) * (i % 2 ? 1 : -1); });
    // reel: spinning, tube feeding out
    const r = S.hudGlobe; r.root.rotation.z = -t * .9; r.root.rotation.y = .5 + Math.sin(t * .2) * .2; r.tail.position.x = ((t * .6) % 1) * .4 - .2;
    // fittings carousel
    const f = S.hudWave; f.root.rotation.y = t * .45; f.items.forEach((g, i) => { g.rotation.x = t * (.6 + i * .1); g.rotation.y = t * .8; });
    // jet: 12 s cycle - fly + barrel roll (0-4), sonic boom (4-5.5), modules open with BOM (6-10), close (10-12)
    const j = S.hudNet, v = t % 12;
    j.root.rotation.y = -.5 + Math.sin(t * .25) * .25;
    j.body.rotation.x = v > 1 && v < 3.2 ? seg(v, 1, 3.2) * Math.PI * 2 : 0;                      // 360° barrel roll
    j.root.position.y = Math.sin(t * 1.3) * .12;
    const boom = v > 4 && v < 5.6 ? (v - 4) / 1.6 : 0;
    j.cone.material.opacity = boom ? .55 * (1 - boom) : 0; j.cone.scale.setScalar(.6 + boom * 1.2);
    j.shock.material.opacity = boom ? .8 * (1 - boom) : 0; j.shock.scale.setScalar(.3 + boom * 4);
    if (boom && boomDone !== Math.floor(t / 12)) { boomDone = Math.floor(t / 12); boomSound(); shake(); }
    j.flames.forEach(fl => { fl.scale.y = 1 + (v > 3 && v < 5.8 ? 1.4 : .2) + Math.random() * .25; });
    const ex = v < 6 ? 0 : v < 7.3 ? seg(v, 6, 7.3) : v < 10 ? 1 : 1 - seg(v, 10, 11.4); j.ex = ex;
    j.mods.forEach(m => m.obj.position.copy(m.base).addScaledVector(m.dir, ex * m.dist));
  }
  function shake(){ const el = document.querySelector(".hudR"); if (!el) return; el.animate([{ transform: "translate(0,0)" }, { transform: "translate(-5px,3px)" }, { transform: "translate(5px,-3px)" },
    { transform: "translate(-3px,-2px)" }, { transform: "translate(0,0)" }], { duration: 420, easing: "ease-out" }); }

  /* ---------------- draw every screen with one renderer */
  function render(){
    const vis = el => el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null;
    const list = Object.values(S).filter(s => s.el && s.el.clientWidth > 20 && vis(s.el));
    if (!list.length) return;
    const dpr = Math.min(devicePixelRatio || 1, 1.6);
    let W = 0, H = 0; for (const s of list) { s.w = Math.round(s.el.clientWidth * dpr); s.h = Math.round(s.el.clientHeight * dpr); W = Math.max(W, s.w); H += s.h; }
    if (glc.width !== W || glc.height !== H) R.setSize(W, H, false);
    R.setScissorTest(false); R.setViewport(0, 0, W, H); R.clear(true, true, true);
    R.setScissorTest(true);
    let y = 0;
    for (const s of list) {
      R.setViewport(0, H - y - s.h, s.w, s.h); R.setScissor(0, H - y - s.h, s.w, s.h); R.clear(true, true, true);
      s.cam.aspect = s.w / s.h; s.cam.updateProjectionMatrix(); R.render(s.sc, s.cam); s.y = y; y += s.h;
    }
    R.setScissorTest(false);
    for (const s of list) {
      if (s.el.width !== s.w || s.el.height !== s.h) { s.el.width = s.w; s.el.height = s.h; }
      const x = s.el.getContext("2d"); x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, s.w, s.h);
      x.drawImage(glc, 0, s.y, s.w, s.h, 0, 0, s.w, s.h);
      overlay(s, x, dpr);
    }
  }
  const proj = (s, obj) => { const p = new T.Vector3(); obj.getWorldPosition(p); p.project(s.cam); return [(p.x + 1) / 2 * s.w, (1 - p.y) / 2 * s.h, p.z]; };
  function txt(x, s, px, py, size, col, align = "left", w = 600){ x.font = `${w} ${size}px "JetBrains Mono",monospace`; x.textAlign = align; x.fillStyle = col; x.fillText(s, px, py); }
  function overlay(s, x, dpr){
    const k = dpr, C1 = "rgba(150,215,255,.95)", C2 = "rgba(110,190,255,.6)", A = "rgba(255,214,140,.95)";
    if (s === S.center) {
      const u = now_t % 15;
      txt(x, `PIPING SPOOL SP-4587 · ${s.phase} · ROT ${String(Math.round((s.root.rotation.y * 180 / Math.PI) % 360)).padStart(3, "0")}°`, s.w / 2, s.h - 66 * k, 10 * k, C2, "center");
      const ba = u < 8.3 ? seg(u, 7.6, 8.3) : u < 11.5 ? 1 : 1 - seg(u, 11.5, 12.2);
      if (ba > 0) {
        const seen = new Set();                                          // numbered balloons on the parts
        x.globalAlpha = ba;
        for (const p of s.parts) { if (seen.has(p.n) || p.e < .6) continue; seen.add(p.n); const [px, py] = proj(s, p.obj), bx = px + 22 * k, by = py - 20 * k;
          x.strokeStyle = C2; x.lineWidth = k; x.beginPath(); x.moveTo(px, py); x.lineTo(bx - 7 * k, by + 5 * k); x.stroke();
          x.fillStyle = "rgba(3,12,28,.85)"; x.beginPath(); x.arc(bx, by, 9 * k, 0, 7); x.fill(); x.strokeStyle = C1; x.stroke();
          x.textBaseline = "middle"; txt(x, String(p.n), bx, by + .5, 10 * k, A, "center", 700); x.textBaseline = "alphabetic"; }
        const bw = Math.min(290 * k, s.w * .34), bx = s.w - bw - 12 * k, lh = 26 * k, hh = 22 * k, by = Math.max(14 * k, s.h - 96 * k - hh - SPOOL_BOM.length * lh);   // bill of materials table
        x.fillStyle = "rgba(3,12,28,.8)"; x.fillRect(bx, by, bw, hh + SPOOL_BOM.length * lh + 6 * k);
        x.strokeStyle = C2; x.strokeRect(bx + .5, by + .5, bw, hh + SPOOL_BOM.length * lh + 6 * k);
        x.fillStyle = "rgba(79,179,255,.22)"; x.fillRect(bx, by, bw, hh);
        txt(x, "BILL OF MATERIALS · SP-4587", bx + 8 * k, by + 15 * k, 10 * k, A, "left", 700);
        SPOOL_BOM.forEach(([n, d, m, q], i) => { const yy = by + hh + 14 * k + i * lh;
          txt(x, String(n), bx + 8 * k, yy, 10 * k, A, "left", 700); txt(x, d, bx + 24 * k, yy, 9.5 * k, C1); txt(x, "×" + q, bx + bw - 8 * k, yy, 9.5 * k, C1, "right");
          txt(x, m, bx + 24 * k, yy + 11 * k, 8.5 * k, C2, "left", 500); });
        x.globalAlpha = 1;
      }
    } else if (s === S.hudNet) {
      const v = now_t % 12;
      txt(x, v < 4 ? "F-X1 · BARREL ROLL" : v < 6 ? "MACH 1.0 · SONIC BOOM" : "MODULES · BILL OF MATERIALS", 10 * k, 16 * k, 9.5 * k, A, "left", 700);
      if (s.ex > .3) { x.globalAlpha = Math.min(1, (s.ex - .3) / .4);
        x.fillStyle = "rgba(3,12,28,.7)"; x.fillRect(6 * k, 24 * k, Math.min(s.w * .62, 210 * k), JET_BOM.length * 12 * k + 8 * k);
        JET_BOM.forEach((l, i) => txt(x, `${i + 1}  ${l}`, 12 * k, 38 * k + i * 12 * k, 8.5 * k, C1)); x.globalAlpha = 1; }
      if (v > 4 && v < 5.8) { x.globalAlpha = 1 - (v - 4) / 1.8; txt(x, "BOOM", s.w - 12 * k, s.h - 14 * k, 20 * k, "rgba(230,245,255,.95)", "right", 800); x.globalAlpha = 1; }
    } else {
      const lab = { hudRadar: "SEAMLESS PIPE BUNDLE · TP316L", hudGlobe: "COIL REEL · TUBE ON SPOOL", hudWave: "BW FITTINGS · ASME B16.9" }[Object.keys(S).find(k2 => S[k2] === s)];
      txt(x, lab, 10 * k, s.h - 10 * k, 9 * k, C2);
    }
  }
  function loop(){
    if (on() && ready) { const now = performance.now(); if (now - lastF > 30) { lastF = now; now_t = typeof window.__forgeT === "number" ? window.__forgeT : (now - t0) / 1000; animate(now_t); render(); } }
    requestAnimationFrame(loop);
  }
  // start when Forge is chosen (Three.js is loaded only then)
  const check = () => { if (document.body.classList.contains("theme-forge")) load(); };
  new MutationObserver(check).observe(document.body, { attributes: true, attributeFilter: ["class"] }); check();
  return { get active(){ return ready && on(); }, get phase(){ return S.center ? S.center.phase : ""; }, get jetT(){ return now_t % 12; } };
})();
