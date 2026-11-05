// Tela 2: campeao. Recebe o JSON do alvo ja lido e devolve HTML.
// Modulo puro: sem DOM, sem I/O.
//
// O nome do alvo vem do proprio JSON (champion_name); o dos oponentes vem do
// Data Dragon, porque o arquivo so traz opponent_champion_id.

import {
  championIcon,
  championName,
  itemIcon,
  itemName,
  runeIcon,
  runeName,
  shardName,
  spellIcon,
  spellName,
} from "./ddragon.js";
import { escapeHtml, iconImg, pct, sample } from "./format.js";
import { matchupHash } from "./route.js";

// Espelha _SKILL_KEYS de src/lolmono/aggregate.py; slot desconhecido vira o proprio numero.
const TECLAS = { 1: "Q", 2: "W", 3: "E", 4: "R" };

function partidas(n) {
  return n === 1 ? "partida" : "partidas";
}

// Dado ausente (ex.: timelines ainda nao coletadas) e dito como ausente,
// com o denominador ao lado, em vez de escondido ou de derrubar a tela.
function ouSemDado(valor, formata) {
  return valor == null ? "Sem dado" : escapeHtml(formata(valor));
}

function lista(nomes) {
  return nomes.map(escapeHtml).join(", ");
}

function ordemDeHabilidades(ordem) {
  return ordem.map((n) => TECLAS[n] ?? String(n)).join(" > ");
}

// Nome sempre em texto; o icone, quando existe, vem antes e nunca o substitui.
function comIcone(url, classe, nome) {
  return `<span class="com-icone">${iconImg(url, classe)}${escapeHtml(nome)}</span>`;
}

function runaComIcone(dict, id) {
  return comIcone(runeIcon(dict, id), "icon icon-rune", runeName(dict, id));
}

function itemComIcone(dict, id) {
  return comIcone(itemIcon(dict, id), "icon icon-item", itemName(dict, id));
}

function paginaDeRunas(runas, dict) {
  const varias = (ids) => ids.map((id) => runaComIcone(dict, id)).join(" ");
  return `<dl class="runes">
      <dt>Runa-chave</dt><dd>${runaComIcone(dict, runas.keystone)}</dd>
      <dt>${runaComIcone(dict, runas.primary_style)}</dt><dd>${varias(runas.primary_perks)}</dd>
      <dt>${runaComIcone(dict, runas.secondary_style)}</dt><dd>${varias(runas.secondary_perks)}</dd>
      <dt>Fragmentos</dt><dd>${lista(runas.shards.map(shardName))}</dd>
    </dl>`;
}

// O exportador entrega a lista inteira de itens; escolher quanto mostrar e desta tela.
// Piso de 5% das partidas do grupo (comparacao em inteiros: games/total >= 1/20) e teto de 12.
const ITENS_PISO_PERCENTUAL = 5;
const ITENS_TETO = 12;

function itensVisiveis(b) {
  const acima = b.item_frequency.filter((i) =>
    i.games * 100 >= b.games * ITENS_PISO_PERCENTUAL
  );
  return { mostrados: acima.slice(0, ITENS_TETO), total: b.item_frequency.length };
}

function base(b, dict) {
  const { mostrados, total } = itensVisiveis(b);
  const truncamento = mostrados.length === total ? "" : `
    <p class="note">Mostrando ${mostrados.length} de ${total} itens: só os que aparecem em pelo menos
    ${ITENS_PISO_PERCENTUAL}% das ${b.games} ${partidas(b.games)}, até ${ITENS_TETO}. Os demais ficam de fora.</p>`;
  const itens = mostrados.map((i) =>
    `<li>${itemComIcone(dict, i.item_id)} <span class="n">${i.games} de ${b.games} ${partidas(b.games)}</span></li>`
  ).join("\n      ");
  return `<section class="baseline">
    <h2>O que os monos fazem por padrão</h2>
    <p class="note">Cada bloco é a configuração mais frequente entre as partidas do grupo,
    vitórias e derrotas juntas: descreve o que se faz por padrão, não o que ganha.
    Taxa de vitória do grupo: ${pct(b.group_win_rate)} ${sample(b.games)}.</p>
    <h3>Runas <span class="n">${sample(b.runes_games)}</span></h3>
    ${paginaDeRunas(b.runes, dict)}
    <p class="aside">Taxa de vitória dessa página exata: ${pct(b.runes_win_rate)} ${sample(b.runes_games)}.
    É informação ao lado; não foi o critério que a escolheu.</p>
    <h3>Feitiços <span class="n">${sample(b.spells_games)}</span></h3>
    <p class="feiticos">${
      b.spells.map((id) => comIcone(spellIcon(dict, id), "icon icon-feitico", spellName(dict, id))).join(" ")
    }</p>
    <h3>Itens no inventário ao fim da partida</h3>
    <p class="note">Item por item, não a build completa: é o que estava nos seis espaços
    quando o jogo acabou, incluindo componente que não foi evoluído e consumível ainda
    na mão. Por isso difere do que um site de meta chama de build.</p>
    <ul class="items">
      ${itens}
    </ul>${truncamento}
    <h3>Itens iniciais <span class="n">${sample(b.starting_items_games)}</span></h3>
    <p class="iniciais">${
      b.starting_items == null
        ? "Sem dado"
        : b.starting_items.map((id) => itemComIcone(dict, id)).join(" ")
    }</p>
    <h3>Ordem de habilidades <span class="n">${sample(b.skill_order_games)}</span></h3>
    <p>${ouSemDado(b.skill_order, ordemDeHabilidades)}</p>
  </section>`;
}

// O slug pertence ao exportador: sai do nome do arquivo do confronto.
function slugDoConfronto(file) {
  return file.replace(/-vs-\d+\.json$/, "");
}

function nomeDoOponente(m, dict) {
  const id = m.opponent_champion_id;
  const url = championIcon(dict, id);
  const icone = url == null
    ? ""
    : `<img class="portrait" src="${escapeHtml(url)}" alt="" width="32" height="32"> `;
  return `${icone}<span class="name">${escapeHtml(championName(dict, id))}</span>`;
}

function resumoDoConfronto(m) {
  // Abaixo do piso o exportador entrega win_rate, mas a tela nao o manchete:
  // abaixo do piso nao afirmamos taxa, so dizemos quantas partidas existem.
  if (m.below_floor) return sample(m.games);
  return `${pct(m.win_rate)} de vitórias ${sample(m.games)}`;
}

function confronto(m, dict) {
  const corpo = `${nomeDoOponente(m, dict)} <span class="n">${resumoDoConfronto(m)}</span>`;
  if (m.below_floor || m.file == null) return `<li class="matchup">${corpo}</li>`;
  const href = escapeHtml(matchupHash(slugDoConfronto(m.file), m.opponent_champion_id));
  return `<li class="matchup"><a href="${href}">${corpo}</a></li>`;
}

// Ordem do JSON: o exportador ja pos o pior primeiro e os abaixo do piso depois.
function confrontos(matchups, dict) {
  const acima = matchups.filter((m) => !m.below_floor);
  const abaixo = matchups.filter((m) => m.below_floor);
  const secaoAbaixo = abaixo.length === 0 ? "" : `
    <h3>Dados insuficientes</h3>
    <p class="note">Poucas partidas para comparar: sem página de confronto.</p>
    <details class="matchups-below-floor-details">
      <summary>${abaixo.length} ${abaixo.length === 1 ? "confronto" : "confrontos"} com poucas partidas</summary>
      <ul class="matchups matchups-below-floor">
        ${abaixo.map((m) => confronto(m, dict)).join("\n        ")}
      </ul>
    </details>`;
  const listaAcima = acima.length === 0
    ? `<p class="note">Nenhum confronto atingiu o piso de partidas, então nenhum ganhou página própria.</p>`
    : `<ul class="matchups">
      ${acima.map((m) => confronto(m, dict)).join("\n      ")}
    </ul>`;
  return `<section class="matchups-section">
    <h2>Confrontos, do pior para o melhor</h2>
    ${listaAcima}${secaoAbaixo}
  </section>`;
}

function jogadores(players) {
  const linhas = players.map((p) =>
    `<li>${escapeHtml(p.riot_id)} <span class="n">${escapeHtml(p.platform)}: ` +
    `${p.games} ${partidas(p.games)}, ${pct(p.share)} do que jogou foi este campeão, ` +
    `${pct(p.win_rate)} de vitórias</span></li>`
  ).join("\n      ");
  return `<details class="reference-players">
    <summary>Jogadores de referência (${players.length})</summary>
    <ul>
      ${linhas}
    </ul>
  </details>`;
}

export function renderChampion(target, dict) {
  return `<section class="champion">
  <h1>${escapeHtml(target.champion_name)} <span class="role">${escapeHtml(target.role)}</span></h1>
  ${base(target.baseline, dict)}
  ${confrontos(target.matchups, dict)}
  ${jogadores(target.reference_players)}
</section>`;
}
