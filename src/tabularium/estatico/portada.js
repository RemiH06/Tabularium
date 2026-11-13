// Portada de Tabularium: cada pieza se imprime en una tinta con trama de puntos y una luz que la
// recorre. La textura trae normal x e y, oclusión y alfa; el sombreado es el de `portada/tinta.py`
// (si cambia uno, cambia el otro). Sin WebGL, o si algo falla, queda la imagen fija.
"use strict";

const VERT = `attribute vec2 p; varying vec2 uv;
void main() { uv = p * .5 + .5; gl_Position = vec4(p, 0., 1.); }`;

const FRAG = `precision highp float;
uniform sampler2D tex; uniform vec3 luz; uniform float celda, claro, aparecer;
uniform vec3 papel, tinta, hondo; varying vec2 uv;
void main() {
  vec4 t = texture2D(tex, uv);
  vec2 nxy = t.rg * 2. - 1.;
  vec3 n = vec3(nxy, sqrt(clamp(1. - dot(nxy, nxy), 0., 1.)));
  float lam = clamp(dot(n, normalize(luz)), 0., 1.);
  float v = (.10 + .90 * lam) * (1. - .65 * (1. - t.b));
  float tono = claro > .5 ? clamp((1. - v - .28) / .52, 0., 1.) : clamp((v - .18) / .5, 0., 1.);
  tono *= aparecer;
  float a = radians(15.);
  vec2 q = mat2(cos(a), -sin(a), sin(a), cos(a)) * gl_FragCoord.xy / celda;
  float d = length(q - floor(q + .5));
  float punto = clamp((sqrt(tono) * .75 - d) * celda + .5, 0., 1.);
  float h = claro > .5
    ? clamp((.30 - t.b) / .12, 0., 1.) * clamp((1. - v - .6) / .2, 0., 1.)
    : clamp((lam - .9) / .06, 0., 1.) * clamp((t.b - .8) / .1, 0., 1.);
  vec3 c = mix(mix(papel, tinta, punto), hondo, h * aparecer);
  gl_FragColor = vec4(c * t.a, t.a);
}`;

const quieto = matchMedia("(prefers-reduced-motion: reduce)");
const oscuro = matchMedia("(prefers-color-scheme: dark)");

function color(nombre) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
  return [1, 3, 5].map(i => parseInt(v.slice(i, i + 2), 16) / 255);
}

function respaldo(lienzo) {
  if (lienzo.querySelector("img")) return;
  const img = document.createElement("img");
  img.alt = lienzo.dataset.alt || "";
  img.src = lienzo.dataset[oscuro.matches ? "fijaOscuro" : "fijaClaro"];
  img.onload = () => { lienzo.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`; };
  lienzo.querySelector("canvas")?.remove();
  lienzo.append(img);
}

function compilar(gl) {
  const prog = gl.createProgram();
  for (const [tipo, src] of [[gl.VERTEX_SHADER, VERT], [gl.FRAGMENT_SHADER, FRAG]]) {
    const s = gl.createShader(tipo);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    gl.attachShader(prog, s);
  }
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const p = gl.getAttribLocation(prog, "p");
  gl.enableVertexAttribArray(p);
  gl.vertexAttribPointer(p, 2, gl.FLOAT, false, 0, 0);
  const u = {};
  for (const n of ["tex", "luz", "celda", "claro", "aparecer", "papel", "tinta", "hondo"]) u[n] = gl.getUniformLocation(prog, n);
  return u;
}

function cargar(src) {
  return new Promise((ok, mal) => {
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = mal;
    img.src = src;
  });
}

async function montar(lienzo) {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  const gl = canvas.getContext("webgl", { premultipliedAlpha: true, antialias: false });
  if (!gl) return respaldo(lienzo);
  let u, img;
  try {
    u = compilar(gl);
    img = await cargar(lienzo.dataset.textura);
  } catch (e) {
    return respaldo(lienzo);
  }
  gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);  // son datos, no color
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
  gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
  for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
                        [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
  lienzo.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`;
  lienzo.append(canvas);

  const tintaVar = lienzo.dataset.tinta || "--rubrica";
  const celdaCss = Number(lienzo.dataset.celda || 4.5);
  let colores, dpr = 1;
  const leerColores = () => {
    colores = { papel: color("--papel"), tinta: color(tintaVar), hondo: color("--hondo"), claro: oscuro.matches ? 0 : 1 };
  };
  const medir = () => {
    dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(canvas.clientWidth * dpr);
    canvas.height = Math.round(canvas.clientHeight * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
  };
  leerColores();
  medir();

  // La luz: un sol que va y viene sobre la pieza; si alguien apunta, la luz va hacia ese punto.
  const luz = [-.55, .55, .62];
  let meta = luz.slice(), puntero = null, ultimoPuntero = -1e9, inicio = performance.now(), visible = true, pedido = 0;
  const dibujar = (ahora) => {
    pedido = 0;
    const t = (ahora - inicio) / 1000;
    const aparecer = quieto.matches ? 1 : Math.min(1, Math.max(0, t / 1.4));  // el primer cuadro puede ser anterior a inicio
    if (quieto.matches) {
      meta = [-.55, .55, .62];
    } else if (puntero && ahora - ultimoPuntero < 4000) {
      meta = puntero;
    } else {
      const f = Math.sin(t * 2 * Math.PI / 22);  // 22 s de ida y vuelta
      meta = [f * .85, .5 + .12 * Math.cos(t * 2 * Math.PI / 11), .62];
    }
    for (let i = 0; i < 3; i++) luz[i] += (meta[i] - luz[i]) * (quieto.matches ? 1 : .05);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1i(u.tex, 0);
    gl.uniform3fv(u.luz, luz);
    gl.uniform1f(u.celda, celdaCss * dpr);
    gl.uniform1f(u.claro, colores.claro);
    gl.uniform1f(u.aparecer, aparecer * aparecer * (3 - 2 * aparecer));
    gl.uniform3fv(u.papel, colores.papel);
    gl.uniform3fv(u.tinta, colores.tinta);
    gl.uniform3fv(u.hondo, colores.hondo);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    if (!quieto.matches && visible && !document.hidden) pedido = requestAnimationFrame(dibujar);
  };
  const pedir = () => { if (!pedido) pedido = requestAnimationFrame(dibujar); };

  addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    const x = (e.clientX - (r.left + r.width / 2)) / (r.width / 2);
    const y = ((r.top + r.height / 2) - e.clientY) / (r.height / 2);
    puntero = [Math.max(-1.6, Math.min(1.6, x)), Math.max(-1.2, Math.min(1.6, y)), .62];
    ultimoPuntero = performance.now();
    pedir();
  }, { passive: true });
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) pedir(); }).observe(canvas);
  document.addEventListener("visibilitychange", pedir);
  new ResizeObserver(() => { medir(); pedir(); }).observe(canvas);
  oscuro.addEventListener("change", () => { leerColores(); pedir(); });
  quieto.addEventListener("change", pedir);
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); respaldo(lienzo); });
  pedir();
}

// Lo último entra renglón por renglón. Visible por defecto: la clase `js` solo se pone aquí.
function revelar() {
  const renglones = [...document.querySelectorAll(".revela")];
  if (!renglones.length || quieto.matches || !("IntersectionObserver" in window)) return;
  document.documentElement.classList.add("js");
  const io = new IntersectionObserver((entradas) => {
    for (const e of entradas) {
      if (!e.isIntersecting) continue;
      const i = renglones.indexOf(e.target);
      setTimeout(() => e.target.classList.add("visto"), Math.min(i, 6) * 90);
      io.unobserve(e.target);
    }
  }, { rootMargin: "0px 0px -8% 0px" });
  renglones.forEach(r => io.observe(r));
}

for (const lienzo of document.querySelectorAll(".lienzo[data-textura]")) montar(lienzo).catch(() => respaldo(lienzo));
revelar();
