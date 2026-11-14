// Formulario de consulta a Gayo: Enter envía, Mayús + Enter inserta un salto de línea. Sin este
// script el formulario funciona igual, con el botón.
"use strict";

for (const forma of document.querySelectorAll("form.preguntar")) {
  const campo = forma.querySelector("textarea");
  const boton = forma.querySelector("button[type=submit]");
  forma.querySelector(".atajo")?.removeAttribute("hidden");
  campo?.addEventListener("keydown", (e) => {
    // isComposing: el Enter que cierra un acento o un carácter compuesto no envía
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    if (campo.value.trim()) forma.requestSubmit();
  });
  forma.addEventListener("submit", () => {  // un solo envío por clic o por Enter
    if (boton) { boton.disabled = true; boton.textContent = "Enviando…"; }
  });
}
