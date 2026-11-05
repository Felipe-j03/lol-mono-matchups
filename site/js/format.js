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

// null/undefined significam "sem dado": o contrato anula medias aos pares
// e alguns arquivos nem trazem o campo.
export function pct(x) {
  if (x == null) return "—";
  return `${Math.round(x * 100)}%`;
}

export function sample(n) {
  return `em ${n} ${n === 1 ? "partida" : "partidas"}`;
}

// Icone decorativo ao lado de um nome que continua em texto: alt vazio, para o
// leitor de tela nao dizer o nome duas vezes. Sem URL, nada: o nome basta.
export function iconImg(url, classe = "icon") {
  if (url == null) return "";
  return `<img class="${escapeHtml(classe)}" src="${escapeHtml(url)}" alt="" width="24" height="24" loading="lazy"> `;
}
