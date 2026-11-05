// Rotas por hash. Modulo puro: sem DOM, sem location, sem imports.
// Unico lugar que conhece o formato do hash: parseRoute le, os construtores escrevem.
//
//   #/            tela de escolha
//   #/<slug>      campeao
//   #/<slug>/vs/<id>  confronto com o oponente de id numerico
//
// Qualquer outra forma vira "notfound", nunca excecao nem tela vazia.

export function parseRoute(hash) {
  if (typeof hash !== "string") return { screen: "notfound", hash };
  const path = hash.replace(/^#/, "").replace(/^\//, "");
  if (path === "") return { screen: "choose" };

  const parts = path.split("/");
  if (parts.length === 1 && parts[0] !== "") {
    return { screen: "champion", slug: parts[0] };
  }
  if (parts.length === 3 && parts[0] !== "" && parts[1] === "vs" && /^\d+$/.test(parts[2])) {
    return { screen: "matchup", slug: parts[0], opponentId: Number(parts[2]) };
  }
  return { screen: "notfound", hash };
}

export function championHash(slug) {
  return `#/${slug}`;
}

export function matchupHash(slug, opponentId) {
  return `#/${slug}/vs/${opponentId}`;
}
