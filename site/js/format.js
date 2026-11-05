// Formatacao e escape. Modulo puro: sem DOM, sem I/O, sem imports.

// O & vem primeiro; trocado depois, reescaparia as entidades dos demais.
export function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// null significa "sem dado": o contrato anula medias aos pares.
export function pct(x) {
  if (x === null) return "—";
  return `${Math.round(x * 100)}%`;
}

export function sample(n) {
  return `em ${n} ${n === 1 ? "partida" : "partidas"}`;
}
