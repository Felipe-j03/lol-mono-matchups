// Traduz ids numericos (item, runa, campeao) em nome e icone via Data Dragon.
// Modulo ES puro: roda igual no navegador e no Deno.

const CDN = "https://ddragon.leagueoflegends.com/cdn";

async function carregarJson(fetchFn, url) {
  const resposta = await fetchFn(url);
  if (!resposta.ok) {
    throw new Error(`Data Dragon: ${url} respondeu ${resposta.status}`);
  }
  return resposta.json();
}

function indexarItens(payload) {
  const itens = new Map();
  for (const [id, item] of Object.entries(payload.data)) {
    itens.set(Number(id), item.name);
  }
  return itens;
}

function indexarCampeoes(payload) {
  const campeoes = new Map();
  for (const campeao of Object.values(payload.data)) {
    campeoes.set(Number(campeao.key), {
      name: campeao.name,
      image: campeao.image.full,
    });
  }
  return campeoes;
}

// Indexa a arvore em si (primary_style/secondary_style) e cada runa dos slots.
function indexarRunas(arvores) {
  const runas = new Map();
  for (const arvore of arvores) {
    runas.set(arvore.id, arvore.name);
    for (const slot of arvore.slots) {
      for (const runa of slot.runes) {
        runas.set(runa.id, runa.name);
      }
    }
  }
  return runas;
}

export async function loadDdragon(version, fetchFn) {
  const base = `${CDN}/${version}/data/en_US`;
  const [itens, campeoes, runas] = await Promise.all([
    carregarJson(fetchFn, `${base}/item.json`),
    carregarJson(fetchFn, `${base}/champion.json`),
    carregarJson(fetchFn, `${base}/runesReforged.json`),
  ]);
  return {
    version,
    items: indexarItens(itens),
    runes: indexarRunas(runas),
    champions: indexarCampeoes(campeoes),
  };
}

export function itemName(dict, id) {
  return dict.items.get(id) ?? String(id);
}

export function runeName(dict, id) {
  return dict.runes.get(id) ?? String(id);
}

export function championName(dict, id) {
  return dict.champions.get(id)?.name ?? String(id);
}

export function championIcon(dict, id) {
  const campeao = dict.champions.get(id);
  if (!campeao) return null;
  return `${CDN}/${dict.version}/img/champion/${campeao.image}`;
}
