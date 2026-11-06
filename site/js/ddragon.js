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
  const nomes = new Map();
  const imagens = new Map();
  const precos = new Map();
  for (const [id, item] of Object.entries(payload.data)) {
    nomes.set(Number(id), item.name);
    if (item.image?.full) imagens.set(Number(id), item.image.full);
    if (typeof item.gold?.total === "number") precos.set(Number(id), item.gold.total);
  }
  return { nomes, imagens, precos };
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

// A chave do JSON e um slug ("SummonerFlash"); o id numerico vem em `key`, string.
function indexarFeiticos(payload) {
  const nomes = new Map();
  const imagens = new Map();
  for (const feitico of Object.values(payload.data)) {
    nomes.set(Number(feitico.key), feitico.name);
    if (feitico.image?.full) imagens.set(Number(feitico.key), feitico.image.full);
  }
  return { nomes, imagens };
}

// Indexa a arvore em si (primary_style/secondary_style) e cada runa dos slots.
function indexarRunas(arvores) {
  const nomes = new Map();
  const icones = new Map();
  const anota = (r) => {
    nomes.set(r.id, r.name);
    if (r.icon) icones.set(r.id, r.icon);
  };
  for (const arvore of arvores) {
    anota(arvore);
    for (const slot of arvore.slots) {
      for (const runa of slot.runes) anota(runa);
    }
  }
  return { nomes, icones };
}

export async function loadDdragon(version, fetchFn) {
  const base = `${CDN}/${version}/data/pt_BR`;
  const [itens, campeoes, runas, feiticos] = await Promise.all([
    carregarJson(fetchFn, `${base}/item.json`),
    carregarJson(fetchFn, `${base}/champion.json`),
    carregarJson(fetchFn, `${base}/runesReforged.json`),
    carregarJson(fetchFn, `${base}/summoner.json`),
  ]);
  const i = indexarItens(itens);
  const r = indexarRunas(runas);
  const f = indexarFeiticos(feiticos);
  return {
    version,
    items: i.nomes,
    itemImages: i.imagens,
    itemGold: i.precos,
    runes: r.nomes,
    runeIcons: r.icones,
    champions: indexarCampeoes(campeoes),
    spells: f.nomes,
    spellImages: f.imagens,
  };
}

export function itemName(dict, id) {
  return dict.items.get(id) ?? String(id);
}

// Custo total em ouro. Devolve null, e nao 0, para id desconhecido: 0 e um
// preco valido (itens de inicio de temporada ja tiveram) e ordenar por ele
// poria o desconhecido antes do mais barato de verdade.
export function itemGold(dict, id) {
  return dict.itemGold?.get(id) ?? null;
}

export function runeName(dict, id) {
  return dict.runes.get(id) ?? SHARDS.get(id) ?? String(id);
}

// ATENCAO: estes nove nomes NAO vem do Data Dragon, que nao publica nome
// nenhum para fragmentos de atributo (ausentes de runesReforged, perkstyles,
// perks, runes e statmods). A fonte e o dono do projeto, que leu os nomes no
// cliente do jogo. Envelhecem diferente de todo o resto deste modulo: o
// Data Dragon e versionado por patch, esta tabela e manual. Se um nome parecer
// errado, desconfie primeiro daqui, nao da CDN.
// So nomes, nunca o valor ("+6 de Armadura"): a magnitude muda a cada patch,
// nao esta nos nossos dados e o site nao tem como verifica-la.
const SHARDS = new Map([
  [5008, "Força Adaptativa"],
  [5011, "Vida"],
  [5005, "Velocidade de Ataque"],
  [5001, "Vida escalando por nível"],
  [5013, "Tenacidade e Resistência a Lentidão"],
  [5007, "Aceleração de Habilidade"],
  [5010, "Velocidade de Movimento"],
  [5002, "Armadura"],
  [5003, "Resistência Mágica"],
]);

export function shardName(id) {
  return SHARDS.get(id) ?? String(id);
}

export function spellName(dict, id) {
  return dict.spells.get(id) ?? String(id);
}

export function championName(dict, id) {
  return dict.champions.get(id)?.name ?? String(id);
}

export function championIcon(dict, id) {
  const campeao = dict.champions.get(id);
  if (!campeao) return null;
  return `${CDN}/${dict.version}/img/champion/${campeao.image}`;
}

export function itemIcon(dict, id) {
  const imagem = dict.itemImages?.get(id);
  if (!imagem) return null;
  return `${CDN}/${dict.version}/img/item/${imagem}`;
}

export function spellIcon(dict, id) {
  const imagem = dict.spellImages?.get(id);
  if (!imagem) return null;
  return `${CDN}/${dict.version}/img/spell/${imagem}`;
}

// ATENCAO: ao contrario de item, feitico e campeao, o icone de runa NAO e
// versionado. O caminho (`icon` do runesReforged.json) vive em /cdn/img/, e a
// forma com versao responde 403. Fragmentos de atributo nao tem icone: nenhum
// arquivo do Data Dragon mapeia id de fragmento para imagem.
export function runeIcon(dict, id) {
  const caminho = dict.runeIcons?.get(id);
  if (!caminho) return null;
  return `${CDN}/img/${caminho}`;
}
