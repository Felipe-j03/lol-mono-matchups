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

// A chave do JSON e um slug ("SummonerFlash"); o id numerico vem em `key`, string.
function indexarFeiticos(payload) {
  const feiticos = new Map();
  for (const feitico of Object.values(payload.data)) {
    feiticos.set(Number(feitico.key), feitico.name);
  }
  return feiticos;
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
  const [itens, campeoes, runas, feiticos] = await Promise.all([
    carregarJson(fetchFn, `${base}/item.json`),
    carregarJson(fetchFn, `${base}/champion.json`),
    carregarJson(fetchFn, `${base}/runesReforged.json`),
    carregarJson(fetchFn, `${base}/summoner.json`),
  ]);
  return {
    version,
    items: indexarItens(itens),
    runes: indexarRunas(runas),
    champions: indexarCampeoes(campeoes),
    spells: indexarFeiticos(feiticos),
  };
}

export function itemName(dict, id) {
  return dict.items.get(id) ?? String(id);
}

export function runeName(dict, id) {
  return dict.runes.get(id) ?? String(id);
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
