// 黒宇宙: 星層(遠/中/近) + 低彩度ネビュラ + 微弱瞬き。ビーム無し。
(function () {
  const THREE_URL = "https://unpkg.com/three@0.160.0/build/three.min.js";
  const THREE_SCRIPT_ID = "space-bg-threejs";

  let threePromise = null;
  let activeBackground = null;
  let ensureScheduled = false;

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

  function ensureBackground() {
    if (document.readyState === "loading") {
      return;
    }

    loadThree()
      .then((THREE) => {
        if (activeBackground && activeBackground.canvas && activeBackground.canvas.isConnected) {
          return;
        }
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
        scheduleEnsure();
      }
    });
    const target = document.documentElement || document;
    observer.observe(target, { childList: true, subtree: true });
  }

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  onReady(() => {
    ensureBackground();
    watchDom();
  });
})();
  
