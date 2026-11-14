// Portada de Tabularium. La estatua gira despacio en diagonal y se imprime con trama de puntos:
// la tinta es la sombra (en oscuro, la luz) y la luz rasante de atrás deja un filo dorado. Al
// llegar al tope del giro entra la siguiente. Las monedas del corpus usan la misma trama sobre
// una textura de normales (ver `portada/tinta.py`). Sin WebGL queda la imagen fija.
"use strict";

const quieto = matchMedia("(prefers-reduced-motion: reduce)");
const oscuro = matchMedia("(prefers-color-scheme: dark)");

// La trama y el sombreado, iguales para la estatua y las monedas.
const TRAMA = `
uniform vec3 luz; uniform float celda, claro, aparecer; uniform vec3 papel, tinta, oro;
vec3 imprimir(vec3 n, float ao, float filo) {
  float lam = clamp(dot(n, normalize(luz)), 0., 1.);
  float v = (.10 + .90 * lam) * (1. - .65 * (1. - ao));
  float tono = claro > .5 ? clamp((1. - v - .28) / .52, 0., 1.) : clamp((v - .18) / .5, 0., 1.);
  float a = radians(15.);
  vec2 q = mat2(cos(a), -sin(a), sin(a), cos(a)) * gl_FragCoord.xy / celda;
  float d = length(q - floor(q + .5));
  float punto = clamp((sqrt(tono * aparecer) * .75 - d) * celda + .5, 0., 1.);
  vec3 c = mix(papel, tinta, punto);
  return mix(c, oro, filo * aparecer);
}`;

const VERT_3D = `
attribute vec4 pos; attribute vec3 nrm; attribute float ao;
uniform mat4 proy; uniform mat3 giro; uniform float dist;
varying vec3 vn; varying float vao;
void main() {
  vec3 p = giro * pos.xyz;
  vn = giro * nrm; vao = ao;
  gl_Position = proy * vec4(p.xy, p.z - dist, 1.);
}`;
const FRAG_3D = `precision highp float;
varying vec3 vn; varying float vao;` + TRAMA + `
void main() {
  vec3 n = normalize(gl_FrontFacing ? vn : -vn);
  // filo: luz rasante desde atrás a la derecha, solo en los bordes que miran de lado
  float filo = pow(1. - abs(n.z), 2.5) * clamp(dot(n, normalize(vec3(.85, .35, -.4))), 0., 1.);
  gl_FragColor = vec4(imprimir(n, vao, smoothstep(.18, .42, filo)), 1.);
}`;

const VERT_2D = `attribute vec2 p; varying vec2 uv;
void main() { uv = p * .5 + .5; gl_Position = vec4(p, 0., 1.); }`;
const FRAG_2D = `precision highp float;
uniform sampler2D tex; varying vec2 uv;` + TRAMA + `
void main() {
  vec4 t = texture2D(tex, uv);
  vec2 nxy = t.rg * 2. - 1.;
  vec3 n = vec3(nxy, sqrt(clamp(1. - dot(nxy, nxy), 0., 1.)));
  gl_FragColor = vec4(imprimir(n, t.b, 0.) * t.a, t.a);
}`;

function color(nombre) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
  return [1, 3, 5].map(i => parseInt(v.slice(i, i + 2), 16) / 255);
}

function programa(gl, vert, frag) {
  const prog = gl.createProgram();
  for (const [tipo, src] of [[gl.VERTEX_SHADER, vert], [gl.FRAGMENT_SHADER, frag]]) {
    const s = gl.createShader(tipo);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    gl.attachShader(prog, s);
  }
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  gl.useProgram(prog);
  const u = new Proxy({}, { get: (c, k) => (k in c ? c[k] : (c[k] = gl.getUniformLocation(prog, k))) });
  return { prog, u };
}

function respaldo(lienzo) {
  if (lienzo.querySelector("img")) return;
  const img = document.createElement("img");
  img.alt = "";
  img.src = lienzo.dataset[oscuro.matches ? "fijaOscuro" : "fijaClaro"];
  lienzo.querySelector("canvas")?.remove();
  lienzo.append(img);
}

// Lo común a los dos lienzos: tamaño, colores, cuándo dibujar.
function lienzoGL(lienzo, opciones) {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  const gl = canvas.getContext("webgl", { antialias: true, ...opciones });
  if (!gl) return null;
  const estado = { gl, canvas, dpr: 1, colores: null, visible: true, pedido: 0, dibujar: null };
  estado.leerColores = () => {
    estado.colores = { papel: color("--fondo"), tinta: color(lienzo.dataset.tinta || "--tinta"),
                       oro: color("--oro"), claro: oscuro.matches ? 0 : 1 };
  };
  estado.medir = () => {
    estado.dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(canvas.clientWidth * estado.dpr);
    canvas.height = Math.round(canvas.clientHeight * estado.dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
  };
  estado.pedir = () => {
    // antes de que cargue la pieza, o si se cayó al respaldo, no hay nada que dibujar
    if (!estado.pedido && estado.dibujar && estado.canvas.isConnected)
      estado.pedido = requestAnimationFrame((t) => { estado.pedido = 0; estado.dibujar(t); });
  };
  estado.seguir = () => !quieto.matches && estado.visible && !document.hidden;
  estado.comunes = (u, luz, celda, aparecer) => {
    const c = estado.colores;
    gl.uniform3fv(u.luz, luz);
    gl.uniform1f(u.celda, celda * estado.dpr);
    gl.uniform1f(u.claro, c.claro);
    gl.uniform1f(u.aparecer, aparecer);
    gl.uniform3fv(u.papel, c.papel);
    gl.uniform3fv(u.tinta, c.tinta);
    gl.uniform3fv(u.oro, c.oro);
  };
  lienzo.append(canvas);
  estado.leerColores();
  new IntersectionObserver(([e]) => { estado.visible = e.isIntersecting; if (estado.visible) estado.pedir(); }).observe(canvas);
  new ResizeObserver(() => { estado.medir(); estado.pedir(); }).observe(canvas);
  document.addEventListener("visibilitychange", () => estado.pedir());
  oscuro.addEventListener("change", () => { estado.leerColores(); estado.pedir(); });
  quieto.addEventListener("change", () => estado.pedir());
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); respaldo(lienzo); });
  return estado;
}

// Luz desde arriba a la izquierda; si alguien apunta, se inclina hacia allá.
const LUZ = [-.55, .55, .62];
const luzPuntero = { meta: LUZ.slice(), hasta: 0 };
addEventListener("pointermove", (e) => {
  const x = e.clientX / innerWidth * 2 - 1, y = 1 - e.clientY / innerHeight * 2;
  luzPuntero.meta = [x * 1.1, .35 + y * .6, .62];
  luzPuntero.hasta = performance.now() + 4000;
}, { passive: true });

async function leerMalla(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  const b = await r.arrayBuffer();
  if (new TextDecoder().decode(new Uint8Array(b, 0, 4)) !== "TAB1") throw new Error(`${url}: formato`);
  const [nv, ni] = new Uint32Array(b, 4, 2);
  return { vertices: new Uint8Array(b, 12, nv * 12), indices: new Uint16Array(b, 12 + nv * 12, ni), ni };
}

function perspectiva(aspecto, fov, cerca, lejos) {
  const f = 1 / Math.tan(fov / 2), r = 1 / (cerca - lejos);
  return new Float32Array([f / aspecto, 0, 0, 0, 0, f, 0, 0, 0, 0, (cerca + lejos) * r, -1, 0, 0, 2 * cerca * lejos * r, 0]);
}

function rotacion(yaw, pitch) {  // Ry(yaw) · Rx(pitch), por columnas como la pide WebGL
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  return new Float32Array([cy, 0, -sy, sy * sp, cp, cy * sp, sy * cp, -sp, cy * cp]);
}

// La estatua: barre en diagonal de un tope al otro y cambia por la siguiente.
const BARRIDO = 10000, CAMBIO = 700, YAW = .8, PITCH = .22;

async function montarEscena(lienzo) {
  const urls = lienzo.dataset.mallas.split(" ");
  const pies = JSON.parse(lienzo.dataset.pies || "[]");
  const pie = lienzo.closest("figure")?.querySelector("figcaption");
  const e = lienzoGL(lienzo, { alpha: true, premultipliedAlpha: true });
  if (!e) return respaldo(lienzo);
  const { gl } = e;
  let p;
  try {
    p = programa(gl, VERT_3D, FRAG_3D);
  } catch (err) {
    e.canvas.remove();
    return respaldo(lienzo);
  }
  const atributos = { pos: gl.getAttribLocation(p.prog, "pos"), nrm: gl.getAttribLocation(p.prog, "nrm"),
                      ao: gl.getAttribLocation(p.prog, "ao") };
  Object.values(atributos).forEach(a => gl.enableVertexAttribArray(a));
  gl.enable(gl.DEPTH_TEST);
  e.medir();

  const cache = new Map();
  const cargar = (i) => {
    if (!cache.has(i)) cache.set(i, leerMalla(urls[i]).then(m => {
      const vb = gl.createBuffer(), ib = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, vb);
      gl.bufferData(gl.ARRAY_BUFFER, m.vertices, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, m.indices, gl.STATIC_DRAW);
      return { vb, ib, ni: m.ni };
    }));
    return cache.get(i);
  };
  let actual = 0, malla, inicio = performance.now(), sentido = 1, pausa = null, cambiando = false;
  try {
    malla = await cargar(0);
  } catch (err) {
    e.canvas.remove();
    return respaldo(lienzo);
  }
  if (urls.length > 1) cargar(1).catch(() => {});
  const luz = LUZ.slice();

  // Algo que se mueve solo por más de 5 s necesita cómo detenerlo (WCAG 2.2.2).
  const boton = lienzo.closest("figure")?.querySelector(".pausa");
  if (boton) {
    boton.hidden = quieto.matches;
    boton.addEventListener("click", () => {
      if (pausa === null) { pausa = performance.now(); boton.textContent = "Reanudar el giro"; }
      else { inicio += performance.now() - pausa; pausa = null; boton.textContent = "Pausar el giro"; e.pedir(); }
      boton.setAttribute("aria-pressed", String(pausa !== null));
    });
  }

  const siguiente = async () => {
    cambiando = true;
    const i = (actual + 1) % urls.length;
    try {
      malla = await cargar(i);
      actual = i;
      if (pie && pies[i]) pie.firstChild.textContent = pies[i];
      cargar((i + 1) % urls.length).catch(() => {});
    } catch (err) { /* se queda la que estaba */ }
    sentido = -sentido;
    inicio = performance.now();
    cambiando = false;
    e.pedir();
  };

  e.dibujar = (ahora) => {
    const t = quieto.matches ? .3 : (Math.max(pausa ?? ahora, inicio) - inicio) / BARRIDO;
    // ida suave de un tope al otro (coseno), en diagonal: yaw y pitch a la vez
    const s = -Math.cos(Math.PI * Math.min(t, 1));  // de -1 a 1
    const yaw = sentido * s * YAW, pitch = -sentido * s * PITCH + .05;
    const fin = Math.max(0, (t - 1) * BARRIDO / CAMBIO);  // 0..1 mientras se borra la tinta
    const entrada = Math.min(1, t * BARRIDO / CAMBIO);
    const a = quieto.matches ? 1 : Math.min(entrada, 1 - Math.min(fin, 1));
    const meta = performance.now() < luzPuntero.hasta ? luzPuntero.meta : LUZ;
    for (let k = 0; k < 3; k++) luz[k] += (meta[k] - luz[k]) * (quieto.matches ? 1 : .05);

    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const aspecto = e.canvas.width / e.canvas.height, fov = .32;
    // Encuadre por eje: la pieza mide 2 de alto y, girada, hasta ~1.5 de ancho. Con un solo radio
    // quedaba chica en una columna alta.
    const dist = Math.max(1.04 / Math.tan(fov / 2), .78 / (Math.tan(fov / 2) * aspecto));
    gl.uniformMatrix4fv(p.u.proy, false, perspectiva(aspecto, fov, dist - 3, dist + 3));
    gl.uniformMatrix3fv(p.u.giro, false, rotacion(yaw, pitch));
    gl.uniform1f(p.u.dist, dist);
    e.comunes(p.u, luz, Number(lienzo.dataset.celda || 4), a * a * (3 - 2 * a));
    gl.bindBuffer(gl.ARRAY_BUFFER, malla.vb);
    gl.vertexAttribPointer(atributos.pos, 4, gl.SHORT, true, 12, 0);
    gl.vertexAttribPointer(atributos.nrm, 3, gl.BYTE, true, 12, 8);
    gl.vertexAttribPointer(atributos.ao, 1, gl.UNSIGNED_BYTE, true, 12, 11);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, malla.ib);
    gl.drawElements(gl.TRIANGLES, malla.ni, gl.UNSIGNED_SHORT, 0);

    if (fin >= 1 && !cambiando && urls.length > 1) siguiente();
    else if (e.seguir() && pausa === null) e.pedir();
  };
  e.pedir();
}

// Las monedas: una textura de normales con la misma trama; la luz es la que sigue al puntero.
async function montarMoneda(lienzo) {
  const e = lienzoGL(lienzo, { premultipliedAlpha: true, antialias: false });
  if (!e) return respaldo(lienzo);
  const { gl } = e;
  let p, img;
  try {
    p = programa(gl, VERT_2D, FRAG_2D);
    img = await new Promise((ok, mal) => { const i = new Image(); i.onload = () => ok(i); i.onerror = mal; i.src = lienzo.dataset.textura; });
  } catch (err) {
    e.canvas.remove();
    return respaldo(lienzo);
  }
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const a = gl.getAttribLocation(p.prog, "p");
  gl.enableVertexAttribArray(a);
  gl.vertexAttribPointer(a, 2, gl.FLOAT, false, 0, 0);
  gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);  // son datos, no color
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
  gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
  for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
                        [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
  e.medir();
  const luz = LUZ.slice();
  e.dibujar = () => {
    const meta = performance.now() < luzPuntero.hasta ? luzPuntero.meta : LUZ;
    for (let k = 0; k < 3; k++) luz[k] += (meta[k] - luz[k]) * (quieto.matches ? 1 : .08);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1i(p.u.tex, 0);
    e.comunes(p.u, luz, Number(lienzo.dataset.celda || 2.5), 1);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    if (e.seguir() && Math.abs(meta[0] - luz[0]) + Math.abs(meta[1] - luz[1]) > .002) e.pedir();
  };
  addEventListener("pointermove", () => e.pedir(), { passive: true });
  e.pedir();
}

// Los cambios recientes entran renglón por renglón. Visibles por defecto: la clase `js` solo se pone aquí.
function revelar() {
  const renglones = [...document.querySelectorAll(".revela")];
  if (!renglones.length || quieto.matches || !("IntersectionObserver" in window)) return;
  document.documentElement.classList.add("js");
  const io = new IntersectionObserver((entradas) => {
    for (const en of entradas) {
      if (!en.isIntersecting) continue;
      setTimeout(() => en.target.classList.add("visto"), Math.min(renglones.indexOf(en.target), 6) * 90);
      io.unobserve(en.target);
    }
  }, { rootMargin: "0px 0px -5% 0px" });
  renglones.forEach(r => io.observe(r));
}

for (const l of document.querySelectorAll(".lienzo[data-mallas]")) montarEscena(l).catch(() => respaldo(l));
for (const l of document.querySelectorAll(".lienzo[data-textura]")) montarMoneda(l).catch(() => respaldo(l));
revelar();
