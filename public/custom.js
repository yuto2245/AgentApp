// 黒宇宙: 星層(遠/中/近) + 低彩度ネビュラ + 微弱瞬き。ビーム無し。
(function () {
  const THREE_URL = "https://unpkg.com/three@0.160.0/build/three.min.js";
  const THREE_SCRIPT_ID = "space-bg-threejs";

  const STYLE_ID = "space-bg-style";
  const SHELL_ID = "space-shell";
  const SIDEBAR_ID = "space-sidebar";

  let threePromise = null;
  let activeBackground = null;
  let ensureScheduled = false;
  let heartbeatId = null;
  let layoutListenerAttached = false;

  function loadThree() {
    if (window.THREE) {
      return Promise.resolve(window.THREE);
    }
    if (threePromise) {
      return threePromise;
    }

    threePromise = new Promise((resolve, reject) => {
      let script = document.getElementById(THREE_SCRIPT_ID);
      const onLoad = () => resolve(window.THREE);
      const onError = (err) => reject(err);

      if (!script) {
        script = document.createElement("script");
        script.id = THREE_SCRIPT_ID;
        script.src = THREE_URL;
        script.async = true;
        script.addEventListener("load", onLoad, { once: true });
        script.addEventListener("error", onError, { once: true });
        document.head.appendChild(script);
      } else {
        script.addEventListener("load", onLoad, { once: true });
        script.addEventListener("error", onError, { once: true });
      }
    }).catch((err) => {
      threePromise = null;
      throw err;
    });

    return threePromise;
  }

  function destroyActiveBackground() {
    if (activeBackground && typeof activeBackground.cleanup === "function") {
      activeBackground.cleanup();
    }
    activeBackground = null;
  }

  function initBackground(THREE) {
    if (!document.body) {
      return null;
    }

    const existing = document.getElementById("space-bg");
    if (existing && existing.isConnected) {
      return activeBackground;
    }

    destroyActiveBackground();

    // ---- renderer / scene
    const canvas = document.createElement("canvas");
    canvas.id = "space-bg";
    canvas.setAttribute("data-space-bg", "");
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    canvas.style.width = "100vw";
    canvas.style.height = "100vh";
    canvas.style.pointerEvents = "none";
    canvas.style.zIndex = "-1";
    document.body.appendChild(canvas);

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const quad = new THREE.PlaneGeometry(2, 2);

    // ---- full-screen shader (nebula + twinkle mask)
    const vert = `void main(){ gl_Position = vec4(position,1.0); }`;

    const frag = `
      precision highp float;
      uniform vec2 iRes;
      uniform float iTime;

      float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453123); }
      float noise(vec2 p){
        vec2 i = floor(p), f = fract(p);
        float a = hash(i), b = hash(i+vec2(1.,0.));
        float c = hash(i+vec2(0.,1.)), d = hash(i+vec2(1.,1.));
        vec2 u = f*f*(3.-2.*f);
        return mix(mix(a,b,u.x), mix(c,d,u.x), u.y);
      }
      float fbm(vec2 p){
        float v=0., a=0.5;
        for(int i=0;i<6;i++){ v += a*noise(p); p*=2.03; a*=0.5; }
        return v;
      }

      void main(){
        vec2 uv = gl_FragCoord.xy / iRes.xy;
        vec2 p  = (uv - 0.5) * vec2(iRes.x/iRes.y, 1.0);

        // 背景: ほぼ純黒
        vec3 col = vec3(0.0);

        // ネビュラ: 低彩度の青灰。極めて控えめ。
        float n1 = fbm(p*2.2 + vec2(0.0, iTime*0.01));
        float n2 = fbm(p*1.1 - vec2(iTime*0.006, 0.0));
        float neb = smoothstep(0.55, 0.95, 0.5*n1 + 0.5*n2);
        vec3 nebCol = mix(vec3(0.0), vec3(0.08,0.09,0.12), neb); // 彩度低
        col += nebCol * 0.35; // 0.35→下げると更に黒寄せ

        // 薄い周辺減光で中央を僅かに持ち上げる
        float r = length(p);
        col *= 1.0 - 0.08 * smoothstep(0.4, 1.1, r);

        // 微弱な瞬き(星用のマスク)。星そのものは別レイヤで追加。
        float twinkle = 0.5 + 0.5*sin(iTime*2.0 + fbm(p*8.0)*6.2831);
        col += vec3(0.02)*twinkle*0.02;

        gl_FragColor = vec4(col, 1.0);
      }`;

    const bgMat = new THREE.ShaderMaterial({
      vertexShader: vert,
      fragmentShader: frag,
      uniforms: { iRes: { value: new THREE.Vector2(1,1) }, iTime: { value: 0 } }
    });
    const bg = new THREE.Mesh(quad, bgMat);
    scene.add(bg);

    // ---- star layers (parallax)
    const starLayers = [];
    addStarLayer(50, 0.2); // 遠
    addStarLayer(20, 0.5); // 中
    addStarLayer(20, 1.0, true); // 近 + ランダム瞬き

    function addStarLayer(count, parallax, twinkle=false){
      const g = new THREE.BufferGeometry();
      const positions = new Float32Array(count*3);
      const sizes = new Float32Array(count);
      for(let i=0;i<count;i++){
        positions[3*i+0] = (Math.random()*2-1);   // x in [-1,1]
        positions[3*i+1] = (Math.random()*2-1);   // y
        positions[3*i+2] = 0;
        // 小さめ基調。近層ほど大きく
        sizes[i] = (Math.random()*1.25 + 0.4) * (1 + parallax*1);
      }
      g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      g.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

      const starVert = `
          attribute float size;
          uniform float iRatio;
          uniform float iParallax;
          varying float vSize;
          void main(){
            vSize = size;
            vec3 pos = position;
            // 超わずかなドリフトで生っぽさ
            pos.x += 0.002 * iParallax;
            gl_Position = vec4(pos, 1.0);
            gl_PointSize = vSize * 2.0 * iRatio;
          }`;

      const starFrag = `
          precision mediump float;
          uniform float iTime;
          uniform bool iTwinkle;
          varying float vSize;
          void main(){
            vec2 uv = gl_PointCoord - 0.5;
            float d = length(uv);
            float disk = smoothstep(0.5, 0.0, d);     // ソフト円
            float core = smoothstep(0.12, 0.0, d);    // 明るい芯
            float t = iTwinkle ? (0.75 + 0.25*sin(iTime*3.0 + vSize*13.0)) : 1.0;
            vec3 col = vec3(0.85) * disk + vec3(1.0) * core;
            gl_FragColor = vec4(col * t, disk);
          }`;

      const m = new THREE.ShaderMaterial({
        vertexShader: starVert,
        fragmentShader: starFrag,
        transparent: true,
        depthTest: false,
        uniforms: {
          iTime: { value: 0 },
          iRatio: { value: 1 },
          iParallax: { value: parallax },
          iTwinkle: { value: !!twinkle }
        }
      });

      const pts = new THREE.Points(g, m);
      scene.add(pts);
      starLayers.push({ mesh: pts, mat: m, parallax, geom: g });
    }

    // ---- resize
    function resize() {
      const w = window.innerWidth, h = window.innerHeight;
      renderer.setSize(w, h, false);
      bgMat.uniforms.iRes.value.set(w, h);
      const ratio = Math.max(1, Math.min(2, (w+h)/1000));
      starLayers.forEach(l => l.mat.uniforms.iRatio.value = ratio);
    }
    window.addEventListener("resize", resize, { passive: true });
    resize();

    // ---- animation
    const t0 = performance.now();
    let animationId = null;
    function loop() {
      const t = (performance.now() - t0) * 0.001;
      bgMat.uniforms.iTime.value = t;
      starLayers.forEach(l => l.mat.uniforms.iTime.value = t);

      // ごく僅かなパララックス・ドリフト
      const driftX = Math.sin(t*0.02)*0.002;
      const driftY = Math.cos(t*0.015)*0.002;
      starLayers.forEach(l => {
        l.mesh.position.x = driftX * l.parallax;
        l.mesh.position.y = driftY * l.parallax;
      });

      renderer.render(scene, camera);
      animationId = requestAnimationFrame(loop);
    }
    animationId = requestAnimationFrame(loop);

    function cleanup() {
      window.removeEventListener("resize", resize);
      if (animationId !== null) {
        cancelAnimationFrame(animationId);
      }
      starLayers.forEach(l => {
        if (l.mesh && l.mesh.parent) {
          l.mesh.parent.remove(l.mesh);
        }
        l.mat.dispose();
        if (l.geom) {
          l.geom.dispose();
        }
      });
      starLayers.length = 0;
      bgMat.dispose();
      quad.dispose();
      renderer.dispose();
      if (canvas.parentNode) {
        canvas.parentNode.removeChild(canvas);
      }
    }

    return { canvas, cleanup };
  }

  function ensureTransparentBackground() {
    const targets = [document.documentElement, document.body, document.getElementById("root")];
    targets.forEach((el) => {
      if (!el) {
        return;
      }
      el.style.background = "transparent";
      el.style.backgroundColor = "transparent";
    });
  }

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      :root, body, #root {
        background: transparent !important;
        color: #f5f7fb;
      }
      body {
        font-family: "Inter", "Noto Sans JP", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      #${SHELL_ID} {
        position: fixed;
        inset: 0;
        display: flex;
        align-items: stretch;
        justify-content: flex-start;
        pointer-events: none;
        z-index: 6;
      }
      #${SIDEBAR_ID} {
        pointer-events: auto;
        display: flex;
        flex-direction: column;
        gap: 16px;
        width: min(320px, 28vw);
        max-width: 360px;
        margin: 72px 0 32px 24px;
        padding: 24px;
        border-radius: 18px;
        background: linear-gradient(160deg, rgba(20,22,30,0.82), rgba(24,26,34,0.65));
        backdrop-filter: blur(14px);
        border: 1px solid rgba(88,120,255,0.25);
        box-shadow: 0 32px 60px rgba(0,0,0,0.45);
      }
      #${SIDEBAR_ID} h2 {
        font-size: 1.25rem;
        margin: 0;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #a8c6ff;
      }
      #${SIDEBAR_ID} p {
        margin: 0;
        font-size: 0.9rem;
        color: rgba(229,235,255,0.72);
        line-height: 1.5;
      }
      #${SIDEBAR_ID} .sidebar-divider {
        height: 1px;
        background: linear-gradient(90deg, rgba(88,120,255,0.15), rgba(88,120,255,0));
        border: none;
      }
      #${SIDEBAR_ID} .sidebar-links {
        display: grid;
        gap: 10px;
      }
      #${SIDEBAR_ID} .sidebar-link {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 12px;
        border-radius: 12px;
        background: rgba(255,255,255,0.03);
        color: inherit;
        text-decoration: none;
        transition: background 0.2s ease, transform 0.2s ease;
      }
      #${SIDEBAR_ID} .sidebar-link:hover {
        background: rgba(105, 143, 255, 0.18);
        transform: translateY(-1px);
      }
      #${SIDEBAR_ID} .sidebar-link span {
        font-size: 0.85rem;
      }
      #${SIDEBAR_ID} .sidebar-tag {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        font-size: 0.75rem;
        color: rgba(173,198,255,0.95);
        border-radius: 999px;
        background: rgba(88,120,255,0.18);
      }
      #${SIDEBAR_ID} .sidebar-footer {
        font-size: 0.72rem;
        color: rgba(211,219,255,0.55);
      }
      @media (max-width: 1023px) {
        #${SIDEBAR_ID} {
          position: fixed;
          inset: auto 16px 16px 16px;
          width: auto;
          margin: 0;
          padding: 20px;
          z-index: 8;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureSidebar() {
    if (!document.body) {
      return;
    }

    injectStyles();

    let shell = document.getElementById(SHELL_ID);
    if (!shell) {
      shell = document.createElement("div");
      shell.id = SHELL_ID;
      shell.setAttribute("data-space-shell", "");
      document.body.appendChild(shell);
    } else if (!shell.isConnected) {
      document.body.appendChild(shell);
    }

    let sidebar = document.getElementById(SIDEBAR_ID);
    if (!sidebar) {
      sidebar = document.createElement("aside");
      sidebar.id = SIDEBAR_ID;
      sidebar.innerHTML = `
        <div class="sidebar-tag">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7.53 4.35a1 1 0 0 1 .47.86v8.58a1 1 0 0 1-.47.86L12 21l-7.53-4.35a1 1 0 0 1-.47-.86V8.21a1 1 0 0 1 .47-.86L12 3z"/><path d="M12 12l7.5-4.35"/><path d="M12 12v9"/><path d="M12 12L4.5 7.65"/></svg>
          SPACE OPS
        </div>
        <h2>Agent Mission Brief</h2>
        <p>
          認証後も背景と補助UIを維持するための実験的なサイドバーです。操作チュートリアルや外部リンクをここに集約できます。
        </p>
        <hr class="sidebar-divider" />
        <div class="sidebar-links">
          <a class="sidebar-link" href="https://github.com/yuto2245/AgentApp" target="_blank" rel="noreferrer">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 2.64 1.78 4.87 4.19 5.72-.27.23-.44.57-.44.95v2.33"/><path d="M9.75 18c-2.33.5-4.35-.8-4.35-3.5"/><path d="M15.44 13.72C17.85 12.87 19.63 10.64 19.63 8"/><path d="M14.25 18v-2.33c0-.38-.17-.72-.44-.95"/></svg>
            <span>Repository</span>
          </a>
          <a class="sidebar-link" href="https://docs.chainlit.io" target="_blank" rel="noreferrer">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h10a2 2 0 0 1 2 2v14l-7-3-7 3V5a2 2 0 0 1 2-2z"/></svg>
            <span>Chainlit Docs</span>
          </a>
          <a class="sidebar-link" href="https://threejs.org" target="_blank" rel="noreferrer">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9.5 5.5v11L12 21l-9.5-5.5v-11L12 3z"/><path d="M12 3v18"/></svg>
            <span>Three.js</span>
          </a>
        </div>
        <hr class="sidebar-divider" />
        <div class="sidebar-footer">
          UIレイアウトはJavaScriptから直接注入されており、ChainlitのDOMが再構築されても自動的に復元されます。
        </div>
      `;
      shell.appendChild(sidebar);
    } else if (!sidebar.isConnected) {
      shell.appendChild(sidebar);
    }

    shell.style.pointerEvents = "none";
    if (sidebar) {
      sidebar.style.pointerEvents = "auto";
    }
  }

  function layoutRoot() {
    const root = document.getElementById("root");
    if (!root) {
      return;
    }
    const width = window.innerWidth || 0;
    const offset = width >= 1440 ? 380 : width >= 1280 ? 340 : width >= 1120 ? 300 : width >= 960 ? 260 : 0;
    root.style.transition = root.style.transition || "padding 0.3s ease";
    root.style.paddingLeft = offset ? `${offset}px` : "";
    root.style.paddingRight = width >= 960 ? "40px" : "";
  }

  function ensureLayoutListener() {
    if (layoutListenerAttached) {
      return;
    }
    layoutListenerAttached = true;
    window.addEventListener("resize", layoutRoot, { passive: true });
  }

  function ensureCustomUI() {
    ensureSidebar();
    ensureLayoutListener();
    layoutRoot();
  }

  function ensureBackground() {
    if (document.readyState === "loading") {
      return;
    }

    loadThree()
      .then((THREE) => {
        ensureCustomUI();
        if (activeBackground && activeBackground.canvas && activeBackground.canvas.isConnected) {
          ensureTransparentBackground();
          return;
        }
        ensureTransparentBackground();
        activeBackground = initBackground(THREE);
      })
      .catch(() => {
        // 読み込み失敗時は次のDOM変化で再試行
      });
  }

  function scheduleEnsure() {
    if (ensureScheduled) {
      return;
    }
    ensureScheduled = true;
    requestAnimationFrame(() => {
      ensureScheduled = false;
      ensureBackground();
    });
  }

  function watchDom() {
    if (typeof MutationObserver === "undefined") {
      return;
    }
    const observer = new MutationObserver(() => {
      const canvas = document.getElementById("space-bg");
      if (!canvas || !canvas.isConnected) {
        destroyActiveBackground();
      }
      ensureCustomUI();
      scheduleEnsure();
    });
    const target = document.documentElement || document;
    observer.observe(target, { childList: true, subtree: true });
  }

  function startHeartbeat() {
    if (heartbeatId !== null) {
      return;
    }
    heartbeatId = window.setInterval(() => {
      const canvas = document.getElementById("space-bg");
      const ready = canvas && canvas.isConnected;
      if (!ready) {
        destroyActiveBackground();
        ensureBackground();
      } else {
        ensureTransparentBackground();
        ensureCustomUI();
      }
    }, 2000);
  }

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  onReady(() => {
    ensureCustomUI();
    ensureBackground();
    watchDom();
    startHeartbeat();
  });
})();
  
